"""Keyword-based subtask → tool name (fallback when LLM routing fails)."""

from __future__ import annotations

from .models import Subtask


def _text(subtask: Subtask) -> str:
    return f"{subtask.title}\n{subtask.description}".lower()


def subtask_to_tool_name(subtask: Subtask) -> str:
    """
    Pick a registry tool from subtask wording.

    Order: more specific phrases before generic ones.
    """
    t = _text(subtask)
    if any(
        k in t
        for k in (
            "backtest",
            "sharpe",
            "drawdown",
            "turnover",
            "pnl",
            "equity",
            "nav",
        )
    ):
        return "run_backtest"
    if any(
        k in t
        for k in (
            "iterative analysis",
            "data analyst",
            "analyze and engineer",
            "analyze then feature",
            "analysis then feature",
            "eda then feature",
        )
    ):
        return "run_data_analyst"
    if any(
        k in t
        for k in (
            "eda",
            "exploratory",
            "data quality",
            "missing",
            "profiling",
            "correlation",
            "distribution",
            "histogram",
            "descriptive stats",
            "data analysis",
            "analyze the data",
            "explore data",
        )
    ):
        return "run_data_analysis"
    if any(
        k in t
        for k in (
            "train",
            "training",
            "regression",
            "fit model",
            "fit a",
            "estimate",
            "sklearn",
        )
    ):
        return "train_model"
    if any(
        k in t
        for k in (
            "feature",
            "factor",
            "momentum",
            "signal",
            "engineer features",
            "build features",
        )
    ):
        return "build_features"
    if any(
        k in t
        for k in (
            "load data",
            "download",
            "dataset",
            "universe",
            "panel",
            "csv",
            "yfinance",
            "yahoo",
        )
    ):
        return "load_data"
    if any(
        k in t
        for k in (
            "evaluate",
            "evaluation",
            "verdict",
            "robustness",
            "conclusion",
            "summary report",
            "next steps",
        )
    ):
        return "evaluate_strategy"
    return "evaluate_strategy"
