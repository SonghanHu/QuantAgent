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


def _tool_output_indicates_failure(output: Any) -> bool:
    """
    Many tools signal failure via a dict instead of raising (workspace missing, subprocess rc, etc.).
    """
    if not isinstance(output, dict):
        return False
    if output.get("error") is not None and output.get("error") != "":
        return True
    rc = output.get("returncode")
    return rc is not None and rc != 0


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

    fn = TOOL_REGISTRY.get(name)
    if fn is not None:
        sig_params = inspect.signature(fn).parameters
        if workspace is not None and "workspace" in sig_params:
            kwargs.setdefault("workspace", workspace)
        if event_callback is not None and "event_callback" in sig_params:
            kwargs.setdefault("event_callback", event_callback)
        if "goal" in sig_params and "goal" not in kwargs:
            kwargs["goal"] = f"{subtask.title}\n\nOverall objective: {state.goal}"
        if "query" in sig_params and "query" not in kwargs:
            kwargs["query"] = subtask.description or subtask.title
        if "instruction" in sig_params and "instruction" not in kwargs:
            kwargs["instruction"] = subtask.description or subtask.title

    if tool_kwargs:
        kwargs.update(tool_kwargs)
    if fn is not None:
        if workspace is not None and "workspace" in sig_params:
            kwargs["workspace"] = workspace
        if event_callback is not None and "event_callback" in sig_params:
            kwargs["event_callback"] = event_callback

    try:
        output = run_tool(name, **kwargs)
        failed = _tool_output_indicates_failure(output)
        summary_bits = [
            f"{k}={v}"
            for k, v in output.items()
            if k
            in (
                "sharpe",
                "max_drawdown",
                "total_return",
                "annual_return",
                "win_rate",
                "verdict",
                "overall_rating",
                "deploy_ready",
                "dataset",
                "model",
                "train_r2",
                "test_r2",
                "test_rmse",
                "returncode",
                "run_id",
                "stopped_reason",
                "workspace_artifact",
                "error",
                "n",
            )
        ]
        summary = ", ".join(summary_bits) if summary_bits else "ok"
        extra = f" [{resolved.source}]" if resolved.source else ""
        if failed:
            err_msg = output.get("message") or output.get("error")
            if not err_msg and output.get("stderr"):
                err_msg = str(output["stderr"])[:300]
            if not err_msg:
                err_msg = f"tool reported failure: {summary}"
            record = ExecutionRecord(
                subtask_id=subtask.id,
                tool_name=name,
                status="error",
                result_summary=str(err_msg) + extra,
                output=output,
            )
            status = "failed"
        else:
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
