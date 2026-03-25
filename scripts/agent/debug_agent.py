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


class RecoveryStep(BaseModel):
    """A lightweight, machine-executable recovery action."""

    model_config = ConfigDict(extra="forbid")

    tool_name: str = Field(description="Registry tool name to run for recovery.")
    kwargs: dict[str, Any] = Field(
        default_factory=dict,
        description="Tool kwargs only; runtime fields like workspace are injected by the workflow.",
    )
    reason: str = Field(default="", description="Why this recovery step helps.")


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
    should_retry_upstream: bool = Field(
        default=False,
        description="True when a lightweight recovery sequence should run before retrying the failed subtask.",
    )
    recovery_steps: list[RecoveryStep] = Field(
        default_factory=list,
        description="Small ordered tool sequence to repair missing prerequisites before retrying.",
    )
    retry_failed_subtask: bool = Field(
        default=True,
        description="Whether the workflow should retry the failed subtask once after recovery.",
    )
    resume_from_subtask_id: int | None = Field(
        default=None,
        description="If set, indicates which subtask should be retried after recovery (usually the failed one).",
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
        "Do not invent files that are not mentioned; if uncertain, say so in root_cause.\n\n"
        "When useful, propose a SMALL recovery sequence using these tool names only: "
        "`web_search`, `run_data_loader`, `load_data`, `run_data_analyst`, `run_data_analysis`, `build_features`.\n"
        "Use `should_retry_upstream=true` only when upstream data/context is actually missing and a short tool sequence "
        "could repair it within the current run. Prefer 1-3 recovery steps. "
        "If the failure is just local code generation / syntax and existing artifacts are sufficient, leave "
        "`should_retry_upstream=false` and let the failed subtask be retried directly or fixed in place."
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
