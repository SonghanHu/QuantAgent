"""Qualitative / next-step evaluation (dummy implementation)."""

from __future__ import annotations

from typing import Any


def evaluate_strategy() -> dict[str, Any]:
    """
    Summarize strategy quality and suggest next research steps (stub).

    Use when the subtask is interpretation, reporting, or deciding what to try next.
    In ReAct: call *after* ``run_backtest`` when you need a verdict + follow-up.

    Args:
        None.

    Returns:
        Dict with ``verdict`` and ``next_step``.
    """
    return {"verdict": "promising", "next_step": "test robustness"}
