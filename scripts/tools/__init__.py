"""
Tool runner: registry + ``run_tool`` for ReAct / agent loops.

Implementation modules live alongside this package (``data``, ``features``, …).
Read ``scripts/docs/tools.md`` for LLM-oriented tool descriptions and typical order.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .alpha import build_alphas
from .analysis import run_data_analysis
from .backtest import run_backtest
from .data_analyst_tool import run_data_analyst
from .data import load_data
from .data_loader_tool import run_data_loader
from .debug_agent_tool import run_debug_agent
from .evaluation import evaluate_strategy
from .features import build_features
from .regressor import train_model
from .search import web_search
from .sp500 import fetch_sp500_tickers_tool

ToolFn = Callable[..., dict[str, Any]]

TOOL_REGISTRY: dict[str, ToolFn] = {
    "load_data": load_data,
    "run_data_loader": run_data_loader,
    "web_search": web_search,
    "fetch_sp500_tickers": fetch_sp500_tickers_tool,
    "run_data_analysis": run_data_analysis,
    "run_data_analyst": run_data_analyst,
    "build_features": build_features,
    "build_alphas": build_alphas,
    "train_model": train_model,
    "run_backtest": run_backtest,
    "run_debug_agent": run_debug_agent,
    "evaluate_strategy": evaluate_strategy,
}


def run_tool(name: str, **kwargs: Any) -> dict[str, Any]:
    """Dispatch by tool name; raises ``KeyError`` if unknown."""
    fn = TOOL_REGISTRY.get(name)
    if fn is None:
        raise KeyError(f"Unknown tool: {name!r}; known: {sorted(TOOL_REGISTRY)}")
    return fn(**kwargs)


def list_tools() -> list[str]:
    return sorted(TOOL_REGISTRY)
