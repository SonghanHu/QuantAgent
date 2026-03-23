"""Runtime state for the agent loop (separate from the static plan `TaskBreakdown`)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from .models import TaskBreakdown


class ExecutionRecord(BaseModel):
    subtask_id: int
    tool_name: str
    status: str
    result_summary: str
    output: dict[str, Any] | None = None


class AgentState(BaseModel):
    """Single object you pass through parse → plan → tool calls → report."""

    goal: str
    plan: TaskBreakdown | None = None
    # --- replan / reflexion hooks (see ``plan_revision.revise_plan``) ---
    plan_version: int = Field(
        default=0,
        description="Increment whenever ``plan`` is replaced mid-run.",
    )
    replan_triggers: list[str] = Field(
        default_factory=list,
        description="Why a replan was requested (e.g. tool_error, sharpe_floor, missing_data).",
    )
    completed_subtasks: list[int] = Field(default_factory=list)
    execution_log: list[ExecutionRecord] = Field(default_factory=list)
    artifacts: dict[str, Any] = Field(default_factory=dict)
    workspace_dir: str | None = Field(
        default=None,
        description="Path to the run's workspace directory (data/workspaces/<run_id>).",
    )
    status: str = "initialized"
