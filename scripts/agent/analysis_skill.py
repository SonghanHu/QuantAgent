"""
Skill-driven data analysis: LLM writes a short script from ``skills/<name>.md``, we inject paths and run it.

**Security:** runs model-generated code locally — use only in trusted environments; timeouts + naive denylist.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
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


def parse_script_with_retry(
    client: OpenAI,
    model: str,
    messages: list[dict[str, str]],
    *,
    retries: int = 2,
) -> GeneratedAnalysisScript:
    """Call ``chat.completions.parse`` with retries on JSON / validation errors."""
    last_exc: Exception | None = None
    for attempt in range(1 + retries):
        try:
            completion = client.chat.completions.parse(
                model=model,
                messages=messages,
                response_format=GeneratedAnalysisScript,
            )
            parsed = completion.choices[0].message.parsed
            if parsed is None:
                raise RuntimeError("Model returned no structured script.")
            return cast(GeneratedAnalysisScript, parsed)
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if attempt < retries:
                time.sleep(1.0 * (attempt + 1))
    raise last_exc  # type: ignore[misc]


def prior_script_revision_from_disk(script_path: Path) -> str | None:
    """If a script file already exists (e.g. retried subtask), load it so the LLM can revise instead of rewriting."""
    if not script_path.is_file():
        return None
    try:
        text = script_path.read_text(encoding="utf-8")
    except OSError:
        return None
    if len(text) > 7_000:
        text = text[:3_500] + "\n\n...[truncated]...\n\n" + text[-3_000:]
    return (
        "### Prior script from this session (on disk)\n\n```python\n"
        + text
        + "\n```\n\n"
        "Revise to fix runtime, logic, or schema errors; keep working structure when possible."
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


def execute_analysis_skill(
    instruction: str,
    *,
    data_path: str | None = None,
    skill_name: str = "data_analysis",
    model: str | None = None,
    client: OpenAI | None = None,
    timeout_sec: int = 120,
    session_run_id: str | None = None,
    revision_context: str | None = None,
    workspace: Any | None = None,
) -> dict[str, Any]:
    """
    Load skill markdown, ask the model for a script, write under ``data/analysis_runs/<id>/``, run with current interpreter.

    Pass ``session_run_id`` to reuse the same run directory across iterations (overwrites ``analysis.py``).
    Pass ``revision_context`` (e.g. prior script + stderr) so the model can fix instead of rewriting from scratch.
    """
    load_dotenv()
    m = model or os.environ.get("OPENAI_TASK_MODEL") or os.environ.get("OPENAI_SMALL_MODEL")
    if not m:
        raise RuntimeError("Neither OPENAI_TASK_MODEL nor OPENAI_SMALL_MODEL is set.")

    skill = read_skill(skill_name)
    if not skill.strip():
        raise FileNotFoundError(f"Skill not found: skills/{skill_name}.md")

    rid = (session_run_id or "").strip()
    run_id = rid[:12] if rid else uuid.uuid4().hex[:12]
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
    if revision_context and revision_context.strip():
        user += (
            "\n\n## Prior attempt (same analysis session)\n\n"
            f"{revision_context.strip()}\n\n"
            "Revise or extend the prior script to satisfy the instruction above. "
            "Reuse working logic; fix errors; do not discard useful code unless the instruction requires it."
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
                "analysis_generated",
                full_source,
                ext="py",
                description="Generated EDA script (mirror of data/analysis_runs/<run_id>/analysis.py)",
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
