"""Tool: invoke the debug agent on workspace + optional natural-language context."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from agent.workspace import Workspace

from agent.debug_agent import run_debug_analysis


def run_debug_agent(
    workspace: Workspace | None = None,
    goal: str = "",
    query: str = "",
    *,
    model: str | None = None,
) -> dict[str, Any]:
    """
    Diagnose pipeline issues from the current workspace and free-text context.

    When called from the executor, ``goal`` and ``query`` are filled from the subtask.
    """
    if workspace is None:
        return {
            "error": "no_workspace",
            "message": "run_debug_agent requires a workspace.",
        }

    g = (goal or "").strip()
    q = (query or "").strip()
    if not g and not q:
        g = "Debug request"

    result = run_debug_analysis(
        goal=g or q,
        workspace=workspace,
        query=q or g,
        subtask=None,
        record=None,
        model=model or os.environ.get("OPENAI_TASK_MODEL") or os.environ.get("OPENAI_SMALL_MODEL"),
    )

    if result.get("error"):
        return result

    workspace.save_json(
        "debug_notes",
        result,
        description="Debug agent structured diagnosis",
    )
    result["workspace_artifact"] = "debug_notes"
    return result
