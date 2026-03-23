"""Wrapper tool: run the iterative data-analyst sub-agent and return its result."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from agent.workspace import Workspace


def run_data_analyst(
    goal: str,
    data_path: str | None = None,
    initial_instruction: str | None = None,
    max_rounds: int = 4,
    timeout_sec: int = 120,
    workspace: Workspace | None = None,
    event_callback: Any | None = None,
) -> dict[str, Any]:
    """
    Iterative sub-agent: analyze data in a loop until ready, then emit a feature plan.

    When *workspace* has ``raw_data`` and no explicit ``data_path``, the parquet is resolved.
    The resulting ``FeaturePlan`` is saved as ``feature_plan.json`` in the workspace.
    """
    if data_path is None and workspace is not None and workspace.has("raw_data"):
        data_path = str(workspace.df_path("raw_data"))

    from agent.data_analyst import run_data_analyst as _run

    result = _run(
        goal,
        data_path=data_path,
        initial_instruction=initial_instruction,
        max_rounds=max_rounds,
        timeout_sec=timeout_sec,
        event_callback=event_callback,
    )

    round_summaries = []
    for r in result.rounds:
        round_summaries.append({
            "round": r.round_num,
            "instruction": r.instruction[:200],
            "returncode": r.result.get("returncode"),
            "script_path": r.result.get("script_path"),
            "judge_ready": r.judge.ready if r.judge else None,
            "judge_reasoning": r.judge.reasoning[:300] if r.judge else None,
        })

    plan_dict: dict[str, Any] | None = None
    if result.feature_plan:
        plan_dict = json.loads(result.feature_plan.model_dump_json())
        if workspace is not None:
            workspace.save_json(
                "feature_plan",
                plan_dict,
                description="Feature engineering plan from data analyst sub-agent",
            )

    return {
        "stopped_reason": result.stopped_reason,
        "num_rounds": len(result.rounds),
        "round_summaries": round_summaries,
        "feature_plan": plan_dict,
    }
