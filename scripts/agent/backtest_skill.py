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
    GeneratedAnalysisScript,
    _clean_script,
    _tail,
    _validate_script,
    parse_script_with_retry,
    prior_script_revision_from_disk,
    read_skill,
)

BACKTEST_RUNS = REPO_ROOT / "data" / "backtest_runs"


class BacktestConfig(BaseModel):
    """Structured hyperparameters that constrain the backtest script."""

    model_config = ConfigDict(extra="forbid")

    strategy_type: Literal["long_only", "long_short"] = "long_only"
    rebalance_freq: Literal["daily", "weekly", "monthly"] = "daily"
    position_sizing: Literal["equal_weight", "signal_proportional", "volatility_scaled"] = (
        "signal_proportional"
    )
    transaction_cost_bps: float = Field(default=5.0, ge=0, description="Round-trip cost in bps")
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
'''

    system = (
        "You output structured JSON with a single field `script` — executable Python code only. "
        "Follow the skill specification exactly. Use only allowed imports. "
        "The preamble defines DATA_PATH, OUTPUT_JSON, RUN_DIR, BACKTEST_CONFIG_JSON, "
        "BACKTEST_MODE, STRATEGY_CONTEXT_JSON, MODEL_OUTPUT_JSON, plus parsed `_CFG`/`config` and "
        "`get_rebalance_freq()`, `effective_rebalance` (module level). Inside **nested functions**, call "
        "`get_rebalance_freq()` or use `config['rebalance_freq']` — do not rely on bare `effective_rebalance` "
        "inside `def` blocks (Python may treat it as a local and raise UnboundLocalError)."
    )
    user = (
        f"## Skill\n\n{skill}\n\n"
        f"## Backtest configuration\n\n{config_str}\n\n"
        f"## Strategy context\n\n{context_str}\n\n"
        f"## Data file\n\n{data_path}\n"
    )
    rev_block = (revision_context or "").strip() or prior_script_revision_from_disk(script_path)
    if rev_block:
        user += (
            "\n\n## Prior attempt (same backtest session)\n\n"
            f"{rev_block}\n\n"
            "Revise or extend the prior script for the configuration above; reuse working logic."
        )

    cli = client or _openai_client()
    parsed = parse_script_with_retry(
        cli, m, [{"role": "system", "content": system}, {"role": "user", "content": user}],
    )
    body = _clean_script(parsed.script)
    _validate_script(body)

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

    summary: dict[str, Any] | None = None
    if output_json.is_file():
        try:
            summary = json.loads(output_json.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            summary = {"parse_error": True, "raw_head": output_json.read_text(encoding="utf-8")[:2000]}

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
    }
