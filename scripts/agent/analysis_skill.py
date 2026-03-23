"""
Skill-driven data analysis: LLM writes a short script from ``skills/<name>.md``, we inject paths and run it.

**Security:** runs model-generated code locally — use only in trusted environments; timeouts + naive denylist.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any, cast

from dotenv import load_dotenv
from openai import OpenAI
from pydantic import BaseModel, ConfigDict, Field

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SKILLS_DIR = REPO_ROOT / "skills"
ANALYSIS_RUNS = REPO_ROOT / "data" / "analysis_runs"


class GeneratedAnalysisScript(BaseModel):
    model_config = ConfigDict(extra="forbid")

    script: str = Field(description="Executable Python only; no markdown fences.")


FORBIDDEN_SNIPPETS = (
    "subprocess",
    "os.system",
    "socket",
    "__import__",
    "requests",
    "urllib",
    "http.client",
    "ftplib",
    "telnetlib",
    "pickle.loads",
    "yaml.load(",
)


def read_skill(skill_name: str) -> str:
    path = SKILLS_DIR / f"{skill_name}.md"
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8")


def _clean_script(raw: str) -> str:
    s = raw.strip()
    if s.startswith("```"):
        lines = s.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        s = "\n".join(lines)
    return s.strip()


def _validate_script(body: str) -> None:
    lower = body.lower()
    for bad in FORBIDDEN_SNIPPETS:
        if bad.lower() in lower:
            raise ValueError(f"Generated script contains forbidden pattern: {bad!r}")


def _openai_client() -> OpenAI:
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("OPENAI_API_KEY is not set.")
    base = os.environ.get("OPENAI_BASE_URL")
    kwargs: dict[str, Any] = {"api_key": key}
    if base:
        kwargs["base_url"] = base.rstrip("/")
    return OpenAI(**kwargs)


def execute_analysis_skill(
    instruction: str,
    *,
    data_path: str | None = None,
    skill_name: str = "data_analysis",
    model: str | None = None,
    client: OpenAI | None = None,
    timeout_sec: int = 120,
) -> dict[str, Any]:
    """
    Load skill markdown, ask the model for a script, write under ``data/analysis_runs/<id>/``, run with current interpreter.
    """
    load_dotenv()
    m = model or os.environ.get("OPENAI_SMALL_MODEL")
    if not m:
        raise RuntimeError("OPENAI_SMALL_MODEL is not set.")

    skill = read_skill(skill_name)
    if not skill.strip():
        raise FileNotFoundError(f"Skill not found: skills/{skill_name}.md")

    run_id = uuid.uuid4().hex[:12]
    run_dir = ANALYSIS_RUNS / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    output_json = run_dir / "summary.json"
    script_path = run_dir / "analysis.py"

    preamble = f'''# -*- injected: do not edit names -*-
from pathlib import Path
import json
DATA_PATH = {repr(data_path)}
OUTPUT_JSON = Path({repr(str(output_json))})
RUN_DIR = Path({repr(str(run_dir))})
'''

    system = (
        "You output structured JSON with a single field `script` — executable Python code only. "
        "Follow the skill specification exactly. Use only allowed imports. "
        "The preamble defining DATA_PATH, OUTPUT_JSON, RUN_DIR will be prepended for you."
    )
    user = (
        f"## Skill\n\n{skill}\n\n"
        f"## Analyst instruction\n\n{instruction.strip()}\n\n"
        f"## Resolved data file\n\n"
        f"{data_path or 'None (build synthetic or minimal demo data in-script).'}\n"
    )

    cli = client or _openai_client()
    completion = cli.chat.completions.parse(
        model=m,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        response_format=GeneratedAnalysisScript,
    )
    parsed = completion.choices[0].message.parsed
    if parsed is None:
        raise RuntimeError("Model returned no structured script.")
    body = _clean_script(cast(GeneratedAnalysisScript, parsed).script)
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

    summary: dict[str, Any] | None = None
    if output_json.is_file():
        try:
            summary = json.loads(output_json.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            summary = {"parse_error": True, "raw_head": output_json.read_text(encoding="utf-8")[:2000]}

    return {
        "skill": skill_name,
        "run_id": run_id,
        "script_path": str(script_path.relative_to(REPO_ROOT)),
        "returncode": proc.returncode,
        "stdout": _tail(proc.stdout, 8000),
        "stderr": _tail(proc.stderr, 4000),
        "summary": summary,
        "data_path": data_path,
    }


def _tail(s: str, max_len: int) -> str:
    if len(s) <= max_len:
        return s
    return s[-max_len:]
