"""Portfolio / strategy simulation (dummy implementation)."""

from __future__ import annotations

from typing import Any


def run_backtest() -> dict[str, Any]:
    """
    Run a backtest using the current trained model and features (stub).

    Use when the subtask is PnL simulation, turnover, drawdowns, Sharpe, etc.
    In ReAct: call *after* ``train_model`` when evaluation requires path-dependent returns.

    Args:
        None (stub uses implicit in-memory state).

    Returns:
        Dict with ``sharpe``, ``max_drawdown``, ``turnover``.
    """
    return {"sharpe": 0.84, "max_drawdown": -0.09, "turnover": 0.31}
