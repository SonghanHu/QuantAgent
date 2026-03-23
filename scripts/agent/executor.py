"""
Bridge: map a planned subtask → tool name (+ kwargs) → ``run_tool`` → ``ExecutionRecord``.

Routing: small LLM (structured output) with catalog + validation + retry, then keyword fallback.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Any

from tools import TOOL_REGISTRY, run_tool

from .models import Subtask
from .state import AgentState, ExecutionRecord
from .subtask_heuristic import subtask_to_tool_name
from .tool_routing import resolve_subtask_tool
from .workspace import Workspace


def run_subtask(
    state: AgentState,
    subtask: Subtask,
    *,
    workspace: Workspace | None = None,
    tool_kwargs: dict[str, Any] | None = None,
    use_llm_routing: bool = True,
    routing_client: Any | None = None,
    routing_model: str | None = None,
    max_catalog_chars: int = 6000,
    routing_retries: int = 2,
    event_callback: Callable[[dict[str, Any]], None] | None = None,
) -> AgentState:
    """
    Execute one subtask: resolve tool (LLM or heuristic), call ``run_tool``, append log.

    If *workspace* is provided and the target tool accepts a ``workspace`` parameter,
    it is automatically injected.  ``tool_kwargs`` merges on top (explicit overrides win).
    """
    resolved = resolve_subtask_tool(
        subtask,
        use_llm=use_llm_routing,
        client=routing_client,
        model=routing_model,
        max_catalog_chars=max_catalog_chars,
        max_retries=routing_retries,
    )
    name = resolved.tool_name
    kwargs = dict(resolved.kwargs)
    if event_callback is not None:
        event_callback(
            {
                "type": "subtask_tool_resolved",
                "subtask_id": subtask.id,
                "subtask_title": subtask.title,
                "tool_name": name,
                "source": resolved.source,
                "kwargs": {k: str(v) for k, v in kwargs.items()},
            }
        )

    if workspace is not None:
        fn = TOOL_REGISTRY.get(name)
        if fn is not None and "workspace" in inspect.signature(fn).parameters:
            kwargs.setdefault("workspace", workspace)
        if fn is not None and "event_callback" in inspect.signature(fn).parameters and event_callback is not None:
            kwargs.setdefault("event_callback", event_callback)

    if tool_kwargs:
        kwargs.update(tool_kwargs)

    try:
        output = run_tool(name, **kwargs)
        summary_bits = [
            f"{k}={v}"
            for k, v in output.items()
            if k
            in (
                "sharpe",
                "verdict",
                "dataset",
                "model",
                "train_r2",
                "test_r2",
                "test_rmse",
                "returncode",
                "run_id",
            )
        ]
        summary = ", ".join(summary_bits) if summary_bits else "ok"
        extra = f" [{resolved.source}]" if resolved.source else ""
        record = ExecutionRecord(
            subtask_id=subtask.id,
            tool_name=name,
            status="ok",
            result_summary=summary + extra,
            output=output,
        )
        status = state.status
    except Exception as exc:  # noqa: BLE001 — surface any tool failure to the log
        record = ExecutionRecord(
            subtask_id=subtask.id,
            tool_name=name,
            status="error",
            result_summary=str(exc),
            output=None,
        )
        status = "failed"
    if event_callback is not None:
        event_callback(
            {
                "type": "subtask_done",
                "subtask_id": subtask.id,
                "subtask_title": subtask.title,
                "tool_name": name,
                "status": record.status,
                "result_summary": record.result_summary,
                "output": record.output,
            }
        )

    done = list(state.completed_subtasks)
    if subtask.id not in done:
        done.append(subtask.id)
    log = list(state.execution_log)
    log.append(record)

    return state.model_copy(
        update={
            "completed_subtasks": done,
            "execution_log": log,
            "status": status,
        }
    )


__all__ = ["run_subtask", "subtask_to_tool_name"]
