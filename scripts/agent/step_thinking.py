"""
Post-subtask reflection: which registry tools matter next (e.g. web_search before run_data_loader for tickers).
"""

from __future__ import annotations

import json
import os
from typing import Any, cast

from dotenv import load_dotenv
from openai import OpenAI
from pydantic import BaseModel, ConfigDict, Field

from .models import Subtask
from .state import ExecutionRecord


class StepThink(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reasoning: str = Field(description="2–5 sentences: what just happened and why it matters.")
    tools_to_consider: list[str] = Field(
        default_factory=list,
        description="Registry tool names that are most relevant for the NEXT step (ordered by priority).",
    )
    note_for_next_step: str = Field(
        default="",
        description="One concrete hint, e.g. use web_search to pick tickers before run_data_loader.",
    )


def _client() -> OpenAI:
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("OPENAI_API_KEY is not set.")
    base = os.environ.get("OPENAI_BASE_URL")
    kwargs: dict[str, Any] = {"api_key": key}
    if base:
        kwargs["base_url"] = base.rstrip("/")
    return OpenAI(**kwargs)


def think_after_subtask(
    *,
    goal: str,
    workspace_artifacts: dict[str, Any],
    completed: Subtask,
    record: ExecutionRecord,
    next_subtask: Subtask | None,
    allowed_tools: list[str],
    model: str | None = None,
) -> dict[str, Any]:
    """
    Return a dict suitable for WebSocket ``step_think`` events; never raises (errors returned in dict).
    """
    load_dotenv()
    m = model or os.environ.get("OPENAI_SMALL_MODEL")
    if not m:
        return {"error": "no_model", "reasoning": "", "tools_to_consider": [], "note_for_next_step": ""}

    allowed_set = set(allowed_tools)
    tools_line = ", ".join(sorted(allowed_tools))
    has_debug_notes = "debug_notes" in workspace_artifacts

    next_block = "None (pipeline end or no further subtasks in plan)."
    if next_subtask is not None:
        next_block = (
            f"id={next_subtask.id}\ntitle: {next_subtask.title}\ndescription: {next_subtask.description}"
        )

    out_summary = record.result_summary[:1200] if record.result_summary else ""
    out_json = ""
    if record.output is not None:
        try:
            out_json = json.dumps(record.output, ensure_ascii=False, default=str)[:2500]
        except TypeError:
            out_json = repr(record.output)[:2500]

    user = (
        f"## Overall goal\n{goal[:3000]}\n\n"
        f"## Workspace artifacts (names + kinds)\n{json.dumps(workspace_artifacts, ensure_ascii=False)[:2000]}\n\n"
        f"## Debug already available\n{'yes' if has_debug_notes else 'no'}\n\n"
        f"## Completed subtask\nid={completed.id}\n{completed.title}\n{completed.description}\n\n"
        f"## Tool used: {record.tool_name}\nstatus: {record.status}\n"
        f"summary: {out_summary}\n\n"
        f"## Tool output (truncated)\n{out_json or '(none)'}\n\n"
        f"## Next planned subtask\n{next_block}\n"
    )

    system = (
        "You are the planning head of a quant research agent. One subtask just finished.\n"
        "Reflect briefly: what was achieved, what is still missing, and which **tools** from the allowed list "
        "are most important for the **next** step.\n\n"
        "Rules:\n"
        "- `tools_to_consider` must contain only names from the allowed list (subset), most important first.\n"
        "- If the next step needs symbols, universes, or data sources not yet in the workspace, "
        "usually prefer `web_search` before `run_data_loader`.\n"
        "- If the next step is `run_data_loader` but tickers/period are ambiguous, say so in `note_for_next_step`.\n"
        "- If the run failed or skipped, say what tool or data would unblock the pipeline.\n"
        "- If `debug_notes` already exists in the workspace, do NOT suggest `run_debug_agent` again unless the "
        "next planned subtask is explicitly debugging. Prefer the fix/retry step instead.\n"
        "- Prefer the immediate unblock for the next planned subtask over distant downstream tools.\n\n"
        f"Allowed tool names: {tools_line}."
    )

    try:
        cli = _client()
        resp = cli.chat.completions.parse(
            model=m,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            response_format=StepThink,
        )
        parsed = resp.choices[0].message.parsed
        if parsed is None:
            return {
                "error": "no_parse",
                "reasoning": "",
                "tools_to_consider": [],
                "note_for_next_step": "",
            }
        t = cast(StepThink, parsed)
        filtered = [x for x in t.tools_to_consider if x in allowed_set]
        if has_debug_notes and next_subtask is not None and "debug" not in next_subtask.title.lower():
            filtered = [x for x in filtered if x != "run_debug_agent"]
        return {
            "reasoning": t.reasoning.strip(),
            "tools_to_consider": filtered,
            "note_for_next_step": t.note_for_next_step.strip(),
            "model": m,
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "error": str(exc),
            "reasoning": "",
            "tools_to_consider": [],
            "note_for_next_step": "",
        }


__all__ = ["think_after_subtask", "StepThink"]
