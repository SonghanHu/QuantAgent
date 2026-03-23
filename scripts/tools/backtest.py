"""Backtest tool: workspace-aware wrapper around the backtest skill sub-agent."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from agent.workspace import Workspace


def run_backtest(
    strategy_type: str = "long_only",
    rebalance_freq: str = "daily",
    position_sizing: str = "signal_proportional",
    transaction_cost_bps: float = 5.0,
    max_position_pct: float = 1.0,
    initial_capital: float = 1_000_000.0,
    train_ratio: float = 0.7,
    workspace: Workspace | None = None,
    timeout_sec: int = 180,
) -> dict[str, Any]:
    """
    Run a skill-driven backtest on workspace data.

    Reads ``engineered_data`` (or ``raw_data``) and ``model_output`` from workspace,
    generates a backtest script via ``skills/backtest.md``, executes it, and saves
    ``backtest_results`` back to the workspace.

    The hyperparameters (``strategy_type``, ``rebalance_freq``, etc.) constrain the
    generated script; the LLM adapts the actual trading logic to the data.
    """
    if workspace is None:
        return {"error": "no_workspace", "message": "run_backtest requires a workspace."}

    if not workspace.has("model_output"):
        return {"error": "no_model_output", "message": "No model_output in workspace. Run train_model first."}

    has_engineered = workspace.has("engineered_data")
    has_raw = workspace.has("raw_data")
    if not has_engineered and not has_raw:
        return {"error": "no_data", "message": "No engineered_data or raw_data in workspace."}

    data_path = str(
        workspace.df_path("engineered_data") if has_engineered else workspace.df_path("raw_data")
    )

    model_output = workspace.load_json("model_output")

    backtest_config = {
        "strategy_type": strategy_type,
        "rebalance_freq": rebalance_freq,
        "position_sizing": position_sizing,
        "transaction_cost_bps": transaction_cost_bps,
        "max_position_pct": max_position_pct,
        "initial_capital": initial_capital,
        "train_ratio": train_ratio,
    }

    from agent.backtest_skill import execute_backtest_skill

    result = execute_backtest_skill(
        backtest_config,
        model_output,
        data_path=data_path,
        timeout_sec=timeout_sec,
    )

    if result.get("returncode") == 0 and result.get("summary"):
        summary = result["summary"]
        workspace.save_json(
            "backtest_results",
            summary,
            description="Backtest results: PnL metrics and equity curve",
        )
        result["workspace_artifact"] = "backtest_results"
        for key in ("sharpe", "max_drawdown", "total_return", "annual_return", "win_rate", "n_test_days"):
            if key in summary:
                result[key] = summary[key]

    result["backtest_config"] = backtest_config
    return result
