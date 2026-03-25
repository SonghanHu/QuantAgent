"""
Skill-driven backtesting: LLM writes a backtest script from ``skills/backtest.md``.

Reuses the same safety/execution pattern as ``analysis_skill`` / ``feature_skill``
but injects ``BACKTEST_CONFIG_JSON`` plus model/rule strategy context.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any, Literal, cast

from dotenv import load_dotenv
from openai import OpenAI
from pydantic import BaseModel, ConfigDict, Field

from .analysis_skill import (
    REPO_ROOT,
    _clean_script,
    _tail,
    _validate_script,
    parse_script_with_retry,
    prior_script_revision_from_disk,
    read_skill,
)
from .backtest_review import format_review_feedback, review_backtest_script

BACKTEST_RUNS = REPO_ROOT / "data" / "backtest_runs"


class BacktestConfig(BaseModel):
    """Structured hyperparameters that constrain the backtest script."""

    model_config = ConfigDict(extra="forbid")

    strategy_type: Literal["long_only", "long_short"] = "long_only"
    rebalance_freq: Literal["daily", "weekly", "monthly"] = "daily"
    position_sizing: Literal["equal_weight", "signal_proportional", "volatility_scaled"] = (
        "signal_proportional"
    )
    transaction_cost_bps: float = Field(
        default=0.0,
        ge=0,
        description="Round-trip cost in bps; 0 unless user/planner explicitly requested costs",
    )
    max_position_pct: float = Field(default=1.0, gt=0, le=1.0, description="Max fraction per position")
    initial_capital: float = Field(default=1_000_000.0, gt=0)
    train_ratio: float = Field(
        default=0.7,
        ge=0.1,
        le=1.0,
        description="Train fraction for time-ordered split. Use 1.0 for full-sample evaluation (typical rule_based).",
    )


def _openai_client() -> OpenAI:
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("OPENAI_API_KEY is not set.")
    base = os.environ.get("OPENAI_BASE_URL")
    kwargs: dict[str, Any] = {"api_key": key}
    if base:
        kwargs["base_url"] = base.rstrip("/")
    return OpenAI(**kwargs)


def execute_backtest_skill(
    backtest_config: dict[str, Any],
    strategy_context: dict[str, Any],
    *,
    data_path: str,
    model: str | None = None,
    client: OpenAI | None = None,
    timeout_sec: int = 180,
    session_run_id: str | None = None,
    revision_context: str | None = None,
    workspace: Any | None = None,
) -> dict[str, Any]:
    """
    Generate and run a backtest script using the ``backtest`` skill.

    ``backtest_config`` holds strategy hyperparameters; ``strategy_context`` tells
    the script whether to run in model-based or rule-based mode.

    Use ``session_run_id`` so retries reuse the same ``backtest.py`` path.

    If ``workspace`` is set, the full script is also saved as ``backtest_generated.py`` in the
    workspace so the dashboard can open it under Artifacts (same content as ``data/backtest_runs/``).
    """
    load_dotenv()
    m = model or os.environ.get("OPENAI_TASK_MODEL") or os.environ.get("OPENAI_SMALL_MODEL")
    if not m:
        raise RuntimeError("Neither OPENAI_TASK_MODEL nor OPENAI_SMALL_MODEL is set.")

    skill = read_skill("backtest")
    if not skill.strip():
        raise FileNotFoundError("Skill not found: skills/backtest.md")

    rid = (session_run_id or "").strip()
    run_id = rid[:12] if rid else uuid.uuid4().hex[:12]
    run_dir = BACKTEST_RUNS / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    output_json = run_dir / "summary.json"
    script_path = run_dir / "backtest.py"

    config_str = json.dumps(backtest_config, ensure_ascii=False, indent=2, default=str)
    context_str = json.dumps(strategy_context, ensure_ascii=False, indent=2, default=str)
    backtest_mode = str(strategy_context.get("backtest_mode", "model_based"))
    model_str = json.dumps(strategy_context.get("model_output") or {}, ensure_ascii=False, indent=2, default=str)

    preamble = f'''# -*- injected: do not edit names -*-
from pathlib import Path
import json
DATA_PATH = {repr(data_path)}
OUTPUT_JSON = Path({repr(str(output_json))})
RUN_DIR = Path({repr(str(run_dir))})
BACKTEST_CONFIG_JSON = {repr(config_str)}
BACKTEST_MODE = {repr(backtest_mode)}
STRATEGY_CONTEXT_JSON = {repr(context_str)}
MODEL_OUTPUT_JSON = {repr(model_str)}
_CFG = json.loads(BACKTEST_CONFIG_JSON)
config = _CFG
effective_rebalance = str(_CFG.get("rebalance_freq") or "daily")

def get_rebalance_freq():
    return str(_CFG.get("rebalance_freq") or "daily")
'''

    system = (
        "You output structured JSON with a single field `script` — executable Python code only. "
        "Follow the skill specification exactly. Use only allowed imports. "
        "The preamble defines DATA_PATH, OUTPUT_JSON, RUN_DIR, BACKTEST_CONFIG_JSON, "
        "BACKTEST_MODE, STRATEGY_CONTEXT_JSON, MODEL_OUTPUT_JSON, plus parsed `_CFG`/`config`, "
        "`get_rebalance_freq()`, and `effective_rebalance` (module level). Inside **nested functions**, call "
        "`get_rebalance_freq()` or use `config['rebalance_freq']` — do not rely on bare `effective_rebalance` "
        "inside `def` blocks (Python may treat it as a local and raise UnboundLocalError)."
    )
    user_base = (
        f"## Skill\n\n{skill}\n\n"
        f"## Backtest configuration\n\n{config_str}\n\n"
        f"## Strategy context\n\n{context_str}\n\n"
        f"## Data file\n\n{data_path}\n"
    )
    rev_block = (revision_context or "").strip() or prior_script_revision_from_disk(script_path)
    if rev_block:
        user_base += (
            "\n\n## Prior attempt (same backtest session)\n\n"
            f"{rev_block}\n\n"
            "Revise or extend the prior script for the configuration above; reuse working logic."
        )

    _NA_AMBIG_HINT = (
        "\n\n**Mandatory fix for pandas:** If the error mentions `boolean value of NA is ambiguous`, "
        "use `.fillna(False)` on boolean masks before `df.loc[mask]`, ensure every part of `(a & b)` "
        "handles NA (e.g. `a.notna() & (a > 0)`), and never `if series:` on a Series with NA."
    )

    cli = client or _openai_client()
    max_exec_attempts = 3
    max_review_passes = max(1, int(os.environ.get("BACKTEST_REVIEW_MAX_PASSES", "4") or "4"))
    skip_code_review = os.environ.get("BACKTEST_CODE_REVIEW", "1").strip().lower() in (
        "0",
        "false",
        "no",
        "off",
    )

    failure_feedback: str | None = None
    proc: subprocess.CompletedProcess[str] | None = None
    summary: dict[str, Any] | None = None
    exec_attempts_used = 0
    code_review_log: list[dict[str, Any]] = []

    for exec_attempt in range(max_exec_attempts):
        exec_attempts_used = exec_attempt + 1
        review_feedback = ""
        body = ""
        code_review_approved = bool(skip_code_review)

        for rv in range(max_review_passes):
            user = user_base
            if failure_feedback:
                user += "\n\n## Prior attempt (execution failed)\n\n" + failure_feedback
            if review_feedback:
                user += "\n\n" + review_feedback

            parsed = parse_script_with_retry(
                cli, m, [{"role": "system", "content": system}, {"role": "user", "content": user}],
            )
            body = _clean_script(parsed.script)
            _validate_script(body)

            if skip_code_review:
                code_review_log.append(
                    {"exec_attempt": exec_attempt + 1, "review_round": rv + 1, "skipped": True}
                )
                code_review_approved = True
                break

            try:
                verdict = review_backtest_script(
                    script_body=body,
                    backtest_config=backtest_config,
                    backtest_mode=backtest_mode,
                    skill_markdown=skill,
                    client=cli,
                )
            except Exception as exc:  # noqa: BLE001
                code_review_log.append(
                    {
                        "exec_attempt": exec_attempt + 1,
                        "review_round": rv + 1,
                        "error": str(exc)[:800],
                        "approved_fallback": True,
                    }
                )
                code_review_approved = True
                break

            row = {
                "exec_attempt": exec_attempt + 1,
                "review_round": rv + 1,
                "approved": verdict.approved,
                "severity": verdict.severity,
                "issues": verdict.issues,
            }
            code_review_log.append(row)
            if verdict.approved:
                code_review_approved = True
                break
            review_feedback = format_review_feedback(verdict)

        full_source = preamble + "\n\n" + body + "\n"
        script_path.write_text(full_source, encoding="utf-8")

        if workspace is not None:
            try:
                workspace.save_text(
                    "backtest_generated",
                    full_source,
                    ext="py",
                    description="Generated backtest script (mirror of data/backtest_runs/<run_id>/backtest.py)",
                )
                workspace.save_json(
                    "backtest_code_reviews",
                    {
                        "approved_before_run": code_review_approved,
                        "skipped_review": skip_code_review,
                        "reviews": code_review_log,
                    },
                    description="Backtest code review agent verdicts (per generation round)",
                )
            except Exception:  # noqa: BLE001
                pass

        proc = subprocess.run(
            [sys.executable, str(script_path)],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=timeout_sec,
            env={**os.environ, "PYTHONUTF8": "1"},
        )

        summary = None
        if output_json.is_file():
            try:
                summary = json.loads(output_json.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                summary = {"parse_error": True, "raw_head": output_json.read_text(encoding="utf-8")[:2000]}

        ok_run = proc.returncode == 0
        summary_error = isinstance(summary, dict) and summary.get("error") is not None
        if ok_run and not summary_error:
            break
        if exec_attempt >= max_exec_attempts - 1:
            break

        err_blob = ((proc.stderr or "") + "\n" + (proc.stdout or "")).lower()
        na_ambiguous = "ambiguous" in err_blob or "boolean value of na" in err_blob
        body_snip = body if len(body) <= 14_000 else body[:7_000] + "\n\n...[truncated]...\n\n" + body[-7_000:]
        hint_extra = _NA_AMBIG_HINT if na_ambiguous else ""
        failure_feedback = (
            f"### Failed script (fix and resubmit)\n\n```python\n{body_snip}\n```\n\n"
            f"### Process exit code\n\n{proc.returncode}\n\n"
            f"### stderr\n\n```\n{_tail(proc.stderr, 6000)}\n```\n\n"
            f"### stdout (tail)\n\n```\n{_tail(proc.stdout, 2000)}\n```\n"
        )
        if summary_error and summary is not None:
            failure_feedback += f"\n### OUTPUT_JSON content\n\n```json\n{json.dumps(summary, ensure_ascii=False, default=str)[:4000]}\n```\n"
        failure_feedback += hint_extra

    assert proc is not None

    return {
        "skill": "backtest",
        "run_id": run_id,
        "script_path": str(script_path.relative_to(REPO_ROOT)),
        "returncode": proc.returncode,
        "stdout": _tail(proc.stdout, 8000),
        "stderr": _tail(proc.stderr, 4000),
        "summary": summary,
        "data_path": data_path,
        "backtest_config": backtest_config,
        "execution_attempts": exec_attempts_used,
        "code_review_approved_before_run": code_review_approved,
        "code_review_skipped": skip_code_review,
        "code_review_log": code_review_log,
    }
