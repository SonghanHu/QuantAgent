"""
Skill-driven alpha engineering: LLM writes a script that implements an AlphaPlan.

WorldQuant-style alpha factor construction. Reuses the same safety/execution
pattern as ``analysis_skill`` / ``feature_skill``.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from openai import OpenAI

from .analysis_skill import (
    REPO_ROOT,
    _clean_script,
    _tail,
    _validate_script,
    parse_script_with_retry,
    prior_script_revision_from_disk,
    read_skill,
)

ALPHA_RUNS = REPO_ROOT / "data" / "alpha_runs"


def _openai_client() -> OpenAI:
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("OPENAI_API_KEY is not set.")
    base = os.environ.get("OPENAI_BASE_URL")
    kwargs: dict[str, Any] = {"api_key": key}
    if base:
        kwargs["base_url"] = base.rstrip("/")
    return OpenAI(**kwargs)


def execute_alpha_skill(
    alpha_plan: dict[str, Any],
    *,
    data_path: str,
    search_context: str = "",
    model: str | None = None,
    client: OpenAI | None = None,
    timeout_sec: int = 150,
    session_run_id: str | None = None,
    revision_context: str | None = None,
) -> dict[str, Any]:
    """
    Given an AlphaPlan and data path, generate and run an alpha engineering script.

    Returns dict with ``returncode``, ``output_path`` (enriched parquet), ``summary``, etc.

    Use ``session_run_id`` (e.g. workspace run id) so retries overwrite the same script.
    Optional ``revision_context`` or an existing on-disk script seeds iterative fixes.
    """
    load_dotenv()
    m = model or os.environ.get("OPENAI_TASK_MODEL") or os.environ.get("OPENAI_SMALL_MODEL")
    if not m:
        raise RuntimeError("Neither OPENAI_TASK_MODEL nor OPENAI_SMALL_MODEL is set.")

    skill = read_skill("alpha_engineering")
    if not skill.strip():
        raise FileNotFoundError("Skill not found: skills/alpha_engineering.md")

    rid = (session_run_id or "").strip()
    run_id = rid[:12] if rid else uuid.uuid4().hex[:12]
    run_dir = ALPHA_RUNS / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    output_json = run_dir / "summary.json"
    output_path = run_dir / "alpha_features.parquet"
    script_path = run_dir / "alpha_eng.py"

    alphas = alpha_plan.get("alphas") or alpha_plan.get("features") or []
    plan_json_str = json.dumps(alphas, ensure_ascii=False, indent=2, default=str)
    target_column = str(alpha_plan.get("target_column", "target"))

    preamble = f'''# -*- injected: do not edit names -*-
from pathlib import Path
import json
DATA_PATH = {repr(data_path)}
OUTPUT_PATH = Path({repr(str(output_path))})
OUTPUT_JSON = Path({repr(str(output_json))})
RUN_DIR = Path({repr(str(run_dir))})
ALPHA_PLAN_JSON = {repr(plan_json_str)}
TARGET_COLUMN = {repr(target_column)}
SEARCH_CONTEXT = {repr(search_context[:4000])}
'''

    system = (
        "You output structured JSON with a single field `script` — executable Python code only. "
        "Follow the alpha_engineering skill specification exactly. Use only allowed imports. "
        "The preamble defining DATA_PATH, OUTPUT_PATH, OUTPUT_JSON, RUN_DIR, ALPHA_PLAN_JSON, "
        "TARGET_COLUMN, SEARCH_CONTEXT will be prepended for you."
    )
    user = (
        f"## Skill\n\n{skill}\n\n"
        f"## Alpha plan\n\n{plan_json_str}\n\n"
        f"## Target column\n\n{target_column}\n\n"
        f"## Data file\n\n{data_path}\n"
    )
    if search_context.strip():
        user += f"\n## Research context from web search\n\n{search_context[:3000]}\n"

    rev_block = (revision_context or "").strip() or prior_script_revision_from_disk(script_path)
    if rev_block:
        user += (
            "\n\n## Prior attempt (same alpha-engineering session)\n\n"
            f"{rev_block}\n\n"
            "Revise or extend the prior script for the alpha plan above; reuse working logic."
        )

    cli = client or _openai_client()
    messages: list[dict[str, str]] = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    max_runtime_fixes = 3
    proc: subprocess.CompletedProcess[str] | None = None
    full_source = ""

    for runtime_round in range(max_runtime_fixes):
        parsed = parse_script_with_retry(cli, m, messages)
        body = _clean_script(parsed.script)
        _validate_script(body)

        full_source = preamble + "\n\n" + body + "\n"
        script_path.write_text(full_source, encoding="utf-8")

        proc = subprocess.run(
            [sys.executable, str(script_path)],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=timeout_sec,
            env={**os.environ, "PYTHONUTF8": "1"},
        )
        if proc.returncode == 0:
            break
        if runtime_round < max_runtime_fixes - 1:
            tail_err = _tail(proc.stderr, 6_000)
            summary_hint = ""
            if output_json.is_file():
                try:
                    failed_summary = json.loads(output_json.read_text(encoding="utf-8"))
                    if isinstance(failed_summary, dict):
                        summary_hint = json.dumps(failed_summary, ensure_ascii=False, default=str)[:2_500]
                except json.JSONDecodeError:
                    summary_hint = output_json.read_text(encoding="utf-8")[:2_500]
            messages.append(
                {
                    "role": "user",
                    "content": (
                        "The script failed when executed. Return a full corrected script only.\n\n"
                        + (f"### stderr\n```\n{tail_err}\n```\n\n" if tail_err.strip() else "")
                        + (f"### summary.json\n```json\n{summary_hint}\n```\n\n" if summary_hint else "")
                    ),
                },
            )

    if proc is None:
        return {
            "skill": "alpha_engineering",
            "run_id": run_id,
            "script_path": str(script_path.relative_to(REPO_ROOT)),
            "output_path": None,
            "returncode": 1,
            "stdout": "",
            "stderr": "internal_error: no subprocess result",
            "summary": None,
            "data_path": data_path,
        }

    summary: dict[str, Any] | None = None
    if output_json.is_file():
        try:
            summary = json.loads(output_json.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            summary = {"parse_error": True, "raw_head": output_json.read_text(encoding="utf-8")[:2000]}

    return {
        "skill": "alpha_engineering",
        "run_id": run_id,
        "script_path": str(script_path.relative_to(REPO_ROOT)),
        "output_path": str(output_path) if output_path.is_file() else None,
        "returncode": proc.returncode,
        "stdout": _tail(proc.stdout, 8000),
        "stderr": _tail(proc.stderr, 4000),
        "summary": summary,
        "data_path": data_path,
    }
