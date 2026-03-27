"""
Build a concise execution-context summary from prior steps + workspace artifacts.

Injected into both the **tool-routing LLM** and the **tool kwargs** (goal / query /
instruction) so that every subtask's LLM knows what happened before it.
"""

from __future__ import annotations

import json
from typing import Any

from .state import AgentState, ExecutionRecord
from .workspace import Workspace

_HIGHLIGHT_KEYS = (
    "rows", "columns", "tickers", "n", "source",
    "stopped_reason", "num_rounds",
    "features_created", "planned_features", "target_column",
    "train_r2", "test_r2", "test_rmse", "model",
    "sharpe", "max_drawdown", "total_return", "annual_return", "backtest_mode",
    "verdict", "overall_rating", "deploy_ready",
    "error", "message", "returncode",
    "skill_mode", "engineered_shape",
    "spec_deviated", "spec_deviation_reason",
)

_MAX_CONTEXT_CHARS = 4000


def _summarize_output(output: dict[str, Any] | None) -> str:
    """Extract key metrics from a tool output dict into a short string."""
    if not output or not isinstance(output, dict):
        return ""
    parts: list[str] = []
    for k in _HIGHLIGHT_KEYS:
        v = output.get(k)
        if v is None or v == "" or v is False:
            continue
        sv = str(v)
        if len(sv) > 120:
            sv = sv[:117] + "..."
        parts.append(f"{k}={sv}")
    return ", ".join(parts)


def _artifact_line(name: str, meta: dict[str, Any]) -> str:
    """One-line summary of a workspace artifact."""
    kind = meta.get("kind", "?")
    desc = meta.get("description", "")
    shape = meta.get("shape")
    parts = [f"{name} ({kind})"]
    if shape:
        parts.append(f"{shape[0]}×{shape[1]}")
    if desc:
        parts.append(desc[:80])
    return " — ".join(parts)


def build_execution_context(
    state: AgentState,
    workspace: Workspace | None,
    *,
    current_subtask_id: int | None = None,
) -> str:
    """
    Build a token-efficient text block summarizing everything that happened so far.

    Included in the tool-routing prompt and in tool kwargs (goal/query/instruction)
    so the LLM making decisions for the current subtask has full situational awareness.
    """
    lines: list[str] = []

    records = state.execution_log
    if not records and (workspace is None or not workspace.list_artifacts()):
        return ""

    ok_records = [r for r in records if r.status == "ok" and r.tool_name != "(skipped)"]
    err_records = [r for r in records if r.status == "error" and r.tool_name != "(skipped)"]

    if ok_records:
        lines.append("## Prior completed steps")
        for r in ok_records:
            highlights = _summarize_output(r.output)
            line = f"- subtask {r.subtask_id} [{r.tool_name}] ✓"
            if highlights:
                line += f" — {highlights}"
            lines.append(line)
        lines.append("")

    if err_records:
        lines.append("## Prior failed steps")
        for r in err_records:
            summary = (r.result_summary or "")[:200]
            lines.append(f"- subtask {r.subtask_id} [{r.tool_name}] ✗ — {summary}")
        lines.append("")

    if workspace is not None:
        artifacts = workspace.list_artifacts()
        if artifacts:
            lines.append("## Workspace artifacts available")
            for name, meta in artifacts.items():
                lines.append(f"- {_artifact_line(name, meta)}")

            for key in ("feature_plan", "alpha_plan"):
                if workspace.has(key):
                    try:
                        plan = workspace.load_json(key)
                        target = plan.get("target_column", "?")
                        items = plan.get("features") or plan.get("alphas") or []
                        names = [f.get("name", "?") for f in items[:8]]
                        lines.append(f"  └─ {key}: target={target}, features={names}")
                    except Exception:  # noqa: BLE001
                        pass

            if workspace.has("model_output"):
                try:
                    mo = workspace.load_json("model_output")
                    lines.append(
                        f"  └─ model_output: model={mo.get('model')}, "
                        f"train_r2={mo.get('train_r2')}, test_r2={mo.get('test_r2')}, "
                        f"target={mo.get('target_column')}"
                    )
                except Exception:  # noqa: BLE001
                    pass

            if workspace.has("backtest_results"):
                try:
                    bt = workspace.load_json("backtest_results")
                    lines.append(
                        f"  └─ backtest_results: sharpe={bt.get('sharpe')}, "
                        f"max_dd={bt.get('max_drawdown')}, mode={bt.get('backtest_mode')}"
                    )
                except Exception:  # noqa: BLE001
                    pass
            lines.append("")

    result = "\n".join(lines).strip()
    if len(result) > _MAX_CONTEXT_CHARS:
        result = result[:_MAX_CONTEXT_CHARS - 20] + "\n\n[...truncated...]"
    return result
