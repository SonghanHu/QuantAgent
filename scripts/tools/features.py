"""Feature construction (dummy implementation)."""

from __future__ import annotations

from typing import Any


def build_features(method: str = "momentum") -> dict[str, Any]:
    """
    Build a feature matrix from loaded data (stub).

    Use when the subtask is about engineering signals (momentum, vol, etc.).
    In ReAct: call *after* ``load_data`` when the plan says factor / feature work.

    Args:
        method: Feature family name (e.g. ``"momentum"``, ``"carry"``). Controls stub output flavor.

    Returns:
        Dict with ``features`` (column names) and ``method``.
    """
    return {"features": ["ret_5d", "ret_20d", "vol_20d"], "method": method}
