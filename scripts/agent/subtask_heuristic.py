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
    if any(k in t for k in ("回测", "sharpe", "drawdown", "turnover", "pnl", "净值", "backtest")):
        return "run_backtest"
    if any(
        k in t
        for k in (
            "数据分析并建特征",
            "分析数据然后特征",
            "iterative analysis",
            "分析+特征",
            "data analyst",
            "analyze and engineer",
            "analyze then feature",
        )
    ):
        return "run_data_analyst"
    if any(
        k in t
        for k in (
            "eda",
            "exploratory",
            "数据探索",
            "描述性统计",
            "数据质量",
            "缺失值",
            "profiling",
            "相关性",
            "分布",
            "histogram",
            "correlation",
            "data analysis",
            "analyze the data",
            "explore data",
        )
    ):
        return "run_data_analysis"
    if any(k in t for k in ("训练", "拟合", "模型", "回归", "train", "regression", "fit", "estimate")):
        return "train_model"
    if any(
        k in t
        for k in ("特征", "因子", "feature", "factor", "momentum", "signal", "工程", "构建因子")
    ):
        return "build_features"
    if any(k in t for k in ("数据", "加载", "dataset", "universe", "panel", "load data", "csv")):
        return "load_data"
    if any(k in t for k in ("评估", "结论", "总结", "报告", "下一步", "evaluate", "verdict", "robustness")):
        return "evaluate_strategy"
    return "evaluate_strategy"
