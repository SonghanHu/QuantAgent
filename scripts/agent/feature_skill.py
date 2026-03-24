"""
Skill-driven feature engineering: LLM writes a script that implements a FeaturePlan.

Reuses the same safety/execution pattern as ``analysis_skill`` but injects
``OUTPUT_PATH`` (enriched parquet) and ``FEATURE_PLAN_JSON`` (serialised plan).
"""

from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any, cast

from dotenv import load_dotenv
from openai import OpenAI

from .analysis_skill import (
    FORBIDDEN_SNIPPETS,
    REPO_ROOT,
    GeneratedAnalysisScript,
    _clean_script,
    _tail,
    _validate_script,
    parse_script_with_retry,
    read_skill,
)

FEATURE_RUNS = REPO_ROOT / "data" / "feature_runs"


def _openai_client() -> OpenAI:
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("OPENAI_API_KEY is not set.")
    base = os.environ.get("OPENAI_BASE_URL")
    kwargs: dict[str, Any] = {"api_key": key}
    if base:
        kwargs["base_url"] = base.rstrip("/")
    return OpenAI(**kwargs)


def _validate_python_syntax(source: str) -> None:
    """Fail early on indentation / syntax errors before spawning Python."""
    ast.parse(source)


def execute_feature_skill(
    feature_plan: dict[str, Any],
    *,
    data_path: str,
    model: str | None = None,
    client: OpenAI | None = None,
    timeout_sec: int = 120,
) -> dict[str, Any]:
    """
    Given a FeaturePlan and input data path, generate and run a feature-engineering script.

    Returns dict with ``returncode``, ``output_path`` (enriched parquet), ``summary``, etc.
    """
    load_dotenv()
    m = model or os.environ.get("OPENAI_TASK_MODEL") or os.environ.get("OPENAI_SMALL_MODEL")
    if not m:
        raise RuntimeError("Neither OPENAI_TASK_MODEL nor OPENAI_SMALL_MODEL is set.")

    skill = read_skill("feature_engineering")
    if not skill.strip():
        raise FileNotFoundError("Skill not found: skills/feature_engineering.md")

    run_id = uuid.uuid4().hex[:12]
    run_dir = FEATURE_RUNS / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    output_json = run_dir / "summary.json"
    output_path = run_dir / "engineered.parquet"
    script_path = run_dir / "feature_eng.py"

    plan_json_str = json.dumps(feature_plan.get("features", []), ensure_ascii=False, indent=2, default=str)
    target_column = str(feature_plan.get("target_column", "target"))

    preamble = f'''# -*- injected: do not edit names -*-
from pathlib import Path
import json
DATA_PATH = {repr(data_path)}
OUTPUT_PATH = {repr(str(output_path))}
OUTPUT_JSON = Path({repr(str(output_json))})
RUN_DIR = Path({repr(str(run_dir))})
FEATURE_PLAN_JSON = {repr(plan_json_str)}
TARGET_COLUMN = {repr(target_column)}
'''

    system = (
        "You output structured JSON with a single field `script` — executable Python code only. "
        "Follow the skill specification exactly. Use only allowed imports. "
        "The preamble defining DATA_PATH, OUTPUT_PATH, OUTPUT_JSON, RUN_DIR, FEATURE_PLAN_JSON, TARGET_COLUMN "
        "will be prepended for you. "
        "Return one complete script with consistent 4-space indentation and no stray indented top-level lines."
    )
    user = (
        f"## Skill\n\n{skill}\n\n"
        f"## Feature plan\n\n{plan_json_str}\n\n"
        f"## Target column\n\n{feature_plan.get('target_column', 'target')}\n\n"
        f"## Data file\n\n{data_path}\n"
    )

    cli = client or _openai_client()
    messages: list[dict[str, str]] = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    last_syntax_error: str | None = None
    full_source = ""
    for attempt in range(3):
        parsed = parse_script_with_retry(cli, m, messages)
        body = _clean_script(parsed.script)
        _validate_script(body)
        full_source = preamble + "\n\n" + body + "\n"
        try:
            _validate_python_syntax(full_source)
            last_syntax_error = None
            break
        except SyntaxError as exc:
            last_syntax_error = f"{exc.__class__.__name__}: {exc}"
            if attempt == 2:
                return {
                    "skill": "feature_engineering",
                    "run_id": run_id,
                    "script_path": str(script_path.relative_to(REPO_ROOT)),
                    "output_path": None,
                    "returncode": 1,
                    "stdout": "",
                    "stderr": last_syntax_error,
                    "summary": {"error": "syntax_validation_failed", "detail": last_syntax_error},
                    "data_path": data_path,
                }
            messages.append(
                {
                    "role": "user",
                    "content": (
                        "Your previous script does not parse as Python. "
                        f"Fix this exact syntax problem and return a full corrected script only: {last_syntax_error}. "
                        "Pay special attention to indentation and top-level block structure."
                    ),
                }
            )
    script_path.write_text(full_source, encoding="utf-8")

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
        "skill": "feature_engineering",
        "run_id": run_id,
        "script_path": str(script_path.relative_to(REPO_ROOT)),
        "output_path": str(output_path) if output_path.is_file() else None,
        "returncode": proc.returncode,
        "stdout": _tail(proc.stdout, 8000),
        "stderr": _tail(proc.stderr, 4000),
        "summary": summary,
        "data_path": data_path,
    }
