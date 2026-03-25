"""Backtest tool: workspace-aware wrapper around the backtest skill sub-agent."""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError

if TYPE_CHECKING:
    from agent.workspace import Workspace


def _infer_rebalance_freq_from_feature_plan(feature_plan: Any) -> str | None:
    """
    When the router omits ``rebalance_freq``, infer weekly/monthly from the feature plan text.

    The tool default used to be ``daily``, which often disagreed with plans that describe
    W-FRI / 周频 / weekly rebalance but never reached the tool kwargs.
    """
    if not isinstance(feature_plan, dict):
        return None
    blob = json.dumps(feature_plan, default=str, ensure_ascii=False).lower()
    if re.search(
        r"w[-_]?fri|weekly\s+rebal|rebal\w{0,16}\s+weekly|周频|周度调仓|每周\s*调仓|每周最后一个交易日",
        blob,
    ):
        return "weekly"
    if re.search(r"monthly\s+rebal|rebal\w{0,16}\s+monthly|月频|月度调仓", blob):
        return "monthly"
    return None


def run_backtest(
    strategy_type: str = "long_only",
    rebalance_freq: str | None = None,
    position_sizing: str = "signal_proportional",
    transaction_cost_bps: float = 0.0,
    max_position_pct: float = 1.0,
    initial_capital: float = 1_000_000.0,
    train_ratio: float | None = None,
    workspace: Workspace | None = None,
    timeout_sec: int = 180,
) -> dict[str, Any]:
    """
    Run a skill-driven backtest on workspace data.

    Reads ``engineered_data`` (or ``raw_data``) from workspace. If ``model_output``
    exists it runs in model-based mode; otherwise it falls back to rule-based mode
    using engineered signals / weights / returns plus optional feature-plan context.
    Generates a backtest script via ``skills/backtest.md``, executes it, and saves
    ``backtest_results`` back to the workspace.

    The hyperparameters (``strategy_type``, ``rebalance_freq``, etc.) constrain the
    generated script; the LLM adapts the actual trading logic to the data.
    Default ``transaction_cost_bps`` is ``0``; pass a positive value only when the user
    explicitly requested transaction costs.

    ``rebalance_freq``: if omitted (``None``), the tool may infer ``weekly`` / ``monthly`` from
    ``feature_plan`` (e.g. W-FRI / 周频). Otherwise defaults to ``daily``.

    ``train_ratio``: ``None`` (default) means **1.0** for ``rule_based`` (full-sample metrics)
    and **0.7** for ``model_based`` (time-ordered train/test). Pass an explicit value to override.
    """
    if workspace is None:
        return {"error": "no_workspace", "message": "run_backtest requires a workspace."}

    has_engineered = workspace.has("engineered_data")
    has_raw = workspace.has("raw_data")
    if not has_engineered and not has_raw:
        return {"error": "no_data", "message": "No engineered_data or raw_data in workspace."}

    data_path = str(
        workspace.df_path("engineered_data") if has_engineered else workspace.df_path("raw_data")
    )

    model_output = workspace.load_json("model_output") if workspace.has("model_output") else None
    feature_plan = workspace.load_json("feature_plan") if workspace.has("feature_plan") else None

    import pandas as pd

    data_df = pd.read_parquet(data_path)
    backtest_mode = "model_based" if model_output else "rule_based"
    # Rule-based strategies (signals already in engineered_data) should evaluate on the full aligned
    # history by default. train/test split is mainly for model_based walk-forward; a 70/30 split on rules
    # often leaves a short, misleading "test" window (and bad date metadata in generated scripts).
    effective_train_ratio = (
        train_ratio
        if train_ratio is not None
        else (1.0 if backtest_mode == "rule_based" else 0.7)
    )
    rf_arg = (rebalance_freq or "").strip().lower()
    inferred_rf = _infer_rebalance_freq_from_feature_plan(feature_plan) if not rf_arg else None
    effective_rebalance = rf_arg or inferred_rf or "daily"
    if model_output is not None:
        target_col = str(model_output.get("target_column", "target"))
        feature_cols = model_output.get("feature_columns", [])
        missing_target = target_col not in data_df.columns
        missing_feats = [c for c in feature_cols if c not in data_df.columns]
        if missing_target or missing_feats:
            parts = []
            if missing_target:
                parts.append(f"target '{target_col}' missing")
            if missing_feats:
                parts.append(f"features missing: {missing_feats[:10]}")
            return {
                "error": "data_model_mismatch",
                "message": (
                    f"Backtest data ({data_path}) does not match model_output: "
                    + "; ".join(parts)
                    + f". Data columns: {list(data_df.columns)[:15]}. "
                    "Re-run build_features to produce an engineered_data with target + features."
                ),
            }

    raw_config = {
        "strategy_type": strategy_type,
        "rebalance_freq": effective_rebalance,
        "position_sizing": position_sizing,
        "transaction_cost_bps": transaction_cost_bps,
        "max_position_pct": max_position_pct,
        "initial_capital": initial_capital,
        "train_ratio": effective_train_ratio,
    }

    from agent.backtest_skill import BacktestConfig, execute_backtest_skill

    config_validation_fallback = False
    try:
        backtest_config = BacktestConfig.model_validate(raw_config).model_dump()
    except ValidationError:
        # LLM router can pass invalid enums/ranges; fall back to skill defaults.
        backtest_config = BacktestConfig().model_dump()
        config_validation_fallback = True

    strategy_context = {
        "backtest_mode": backtest_mode,
        "model_output": model_output or {},
        "feature_plan": feature_plan or {},
        "data_columns": list(data_df.columns)[:200],
        "data_path": data_path,
        "has_engineered_data": has_engineered,
        "has_model_output": model_output is not None,
    }

    result = execute_backtest_skill(
        backtest_config,
        strategy_context,
        data_path=data_path,
        timeout_sec=timeout_sec,
        session_run_id=workspace.run_id,
        workspace=workspace,
    )

    # Persist any structured summary written by the script (including {"error": ...}).
    if result.get("returncode") == 0 and result.get("summary") is not None:
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
    result["backtest_mode"] = backtest_mode
    if config_validation_fallback:
        result["config_validation_fallback"] = True
    if not rf_arg and inferred_rf is not None:
        result["rebalance_freq_inferred_from_feature_plan"] = inferred_rf
    return result
