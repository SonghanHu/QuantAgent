"""
Tool runner: registry + ``run_tool`` for ReAct / agent loops.

Implementation modules live alongside this package (``data``, ``features``, …).
Read ``scripts/docs/tools.md`` for LLM-oriented tool descriptions and typical order.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .analysis import run_data_analysis
from .backtest import run_backtest
from .data_analyst_tool import run_data_analyst
from .data import load_data
from .evaluation import evaluate_strategy
from .features import build_features
from .regressor import train_model

ToolFn = Callable[..., dict[str, Any]]

TOOL_REGISTRY: dict[str, ToolFn] = {
    "load_data": load_data,
    "run_data_analysis": run_data_analysis,
    "run_data_analyst": run_data_analyst,
    "build_features": build_features,
    "train_model": train_model,
    "run_backtest": run_backtest,
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
