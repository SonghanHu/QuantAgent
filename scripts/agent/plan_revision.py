"""
Mid-run plan revision — **placeholder** for a reflexion / RePlan step.

Integrate when the current ``TaskBreakdown`` is no longer valid, for example:

- a **subtask** ends in ``ExecutionRecord.status == "error"``;
- **backtest** metrics fall below a floor (e.g. Sharpe, max drawdown);
- **data quality** checks report gaps or schema mismatch;
- you need to insert **robustness** or stress steps mid-pipeline.

Expected contract (when implemented):

- **Input:** original ``goal``, latest ``AgentState`` (``plan``, ``execution_log``,
  ``artifacts``, ``replan_triggers``), and ``model`` (typically ``OPENAI_SMALL_MODEL``
  or a stronger model for replanning).
- **Output:** a fresh ``TaskBreakdown``; the runner should bump ``state.plan_version``,
  replace ``state.plan``, optionally reset ``completed_subtasks`` / slice ``execution_log``,
  then **recompute** topo order and continue or restart from a safe checkpoint.

Persistence: log replan events under category ``plan_revision`` (see ``storage.agent_log_db.add_log``).
"""

from __future__ import annotations

from .models import TaskBreakdown
from .state import AgentState


def revise_plan(goal: str, state: AgentState, *, model: str) -> TaskBreakdown:
    """
    Regenerate a structured plan given accumulated runtime context.

    Not implemented yet — reserved so callers can import the name and type-check
    against this signature.
    """
    raise NotImplementedError(
        "revise_plan is not implemented. "
        "Wire LLM + structured output here; see module docstring for triggers."
    )


__all__ = ["revise_plan"]
