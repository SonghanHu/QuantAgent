"""
Debug agent: LLM-assisted diagnosis of tool failures using workspace context + error payloads.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, cast

from dotenv import load_dotenv
from openai import OpenAI
from pydantic import BaseModel, ConfigDict, Field

from .models import Subtask
from .state import ExecutionRecord
from .workspace import Workspace


class DebugAnalysis(BaseModel):
    """Structured output from the debug model."""

    model_config = ConfigDict(extra="forbid")

    summary: str = Field(description="One short paragraph for humans.")
    root_cause: str = Field(description="Most likely technical cause.")
    category: str = Field(
        description="Short label, e.g. pandas_index, missing_artifact, subprocess, schema, other"
    )
    suggested_fixes: list[str] = Field(
        default_factory=list,
        description="Concrete steps or code-level hints; max ~5 items.",
    )
    next_steps: str = Field(
        default="",
        description="What to run or change next (e.g. re-run build_features).",
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


def _truncate(s: str, max_len: int) -> str:
    s = s.strip()
    if len(s) <= max_len:
        return s
    return s[: max_len - 20] + "\n... [truncated]"


def _serialize_record_output(output: Any, max_chars: int = 6000) -> str:
    if output is None:
        return ""
    try:
        text = json.dumps(output, ensure_ascii=False, indent=2, default=str)
    except TypeError:
        text = repr(output)
    return _truncate(text, max_chars)


def run_debug_analysis(
    *,
    goal: str,
    workspace: Workspace,
    query: str = "",
    subtask: Subtask | None = None,
    record: ExecutionRecord | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    """
    Produce a structured diagnosis; does not mutate workspace (caller may persist).
    """
    load_dotenv()
    m = model or os.environ.get("OPENAI_TASK_MODEL") or os.environ.get("OPENAI_SMALL_MODEL")
    if not m:
        return {
            "error": "no_model",
            "message": "Set OPENAI_TASK_MODEL or OPENAI_SMALL_MODEL for debug_agent.",
        }

    artifacts = workspace.list_artifacts()
    parts: list[str] = [
        "## Overall goal\n",
        _truncate(goal, 4000),
        "\n## Workspace artifacts\n",
        json.dumps(artifacts, indent=2, ensure_ascii=False, default=str),
    ]
    if query.strip():
        parts.extend(["\n## User / subtask focus\n", _truncate(query, 2000)])
    if subtask is not None:
        parts.extend(
            [
                "\n## Failed subtask\n",
                f"id: {subtask.id}\ntitle: {subtask.title}\ndescription: {_truncate(subtask.description, 2000)}",
            ]
        )
    if record is not None:
        parts.extend(
            [
                "\n## Execution record\n",
                f"tool_name: {record.tool_name}\nstatus: {record.status}\n"
                f"result_summary: {_truncate(record.result_summary, 2000)}\n",
                "\n### tool output (JSON)\n",
                _serialize_record_output(record.output),
            ]
        )

    user_content = "".join(parts)
    system = (
        "You are a senior Python / quant pipeline debugger. "
        "Given the goal, workspace artifact list, and any tool error output, "
        "produce a concise diagnosis. Prefer concrete causes (e.g. pandas index alignment, "
        "missing parquet column, subprocess exit code). "
        "Do not invent files that are not mentioned; if uncertain, say so in root_cause."
    )

    try:
        cli = _openai_client()
        completion = cli.chat.completions.parse(
            model=m,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user_content},
            ],
            response_format=DebugAnalysis,
        )
        parsed = completion.choices[0].message.parsed
        if parsed is None:
            return {"error": "no_parse", "message": "Model returned no structured output."}
        data = parsed.model_dump()
        data["model"] = m
        data["analyzed_at"] = datetime.now(timezone.utc).isoformat()
        if subtask is not None:
            data["subtask_id"] = subtask.id
        if record is not None:
            data["tool_name"] = record.tool_name
        return cast(dict[str, Any], data)
    except Exception as exc:  # noqa: BLE001
        return {"error": "debug_failed", "message": str(exc)}


__all__ = ["run_debug_analysis", "DebugAnalysis"]
