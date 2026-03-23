"""Portfolio / strategy simulation (stub — will become a sub-agent)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from agent.workspace import Workspace

# TODO: convert to a sub-agent that reads engineered_data + trained model
# from workspace, generates a backtest script via skills/backtest.md,
# and produces real PnL / risk metrics.


def run_backtest(workspace: Workspace | None = None) -> dict[str, Any]:
    """
    Run a backtest using the current trained model and features (stub).

    Will be replaced by an LLM-driven sub-agent that generates and executes
    a backtest script using workspace artifacts (engineered_data, model).
    """
    return {"sharpe": 0.84, "max_drawdown": -0.09, "turnover": 0.31, "stub": True}
