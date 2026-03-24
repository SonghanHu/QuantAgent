"""Iterative data-ingestion sub-agent: propose download → load → judge → repeat."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from agent.workspace import Workspace


def run_data_loader(
    goal: str,
    max_rounds: int = 4,
    workspace: Workspace | None = None,
    event_callback: Any | None = None,
) -> dict[str, Any]:
    """
    LLM proposes ``YFinanceFetchSpec`` each round; ``load_data`` runs the fixed path; a judge
    decides if ``raw_data`` fits the goal. Requires ``workspace``.
    """
    if workspace is None:
        return {
            "error": "no_workspace",
            "message": "run_data_loader requires a workspace to store raw_data.",
            "returncode": 1,
        }

    from agent.data_loader import run_data_loader as _run

    result = _run(goal, workspace=workspace, max_rounds=max_rounds, event_callback=event_callback)

    if result.stopped_reason == "error" or not result.rounds:
        return {
            "stopped_reason": result.stopped_reason,
            "num_rounds": 0,
            "round_summaries": [],
            "returncode": 1,
            "error": "data_loader_error",
            "message": "Could not produce a valid yfinance download spec.",
        }

    round_summaries: list[dict[str, Any]] = []
    for r in result.rounds:
        round_summaries.append(
            {
                "round": r.round_num,
                "spec_tickers": (r.spec or {}).get("tickers"),
                "load_rows": r.load_meta.get("rows"),
                "workspace_artifact": r.load_meta.get("workspace_artifact"),
                "judge_ready": r.judge.ready if r.judge else None,
                "judge_reasoning": (r.judge.reasoning[:400] if r.judge else None),
            }
        )

    last = result.rounds[-1] if result.rounds else None
    judge_ready = last.judge.ready if last and last.judge else False
    has_raw = workspace.has("raw_data")

    out: dict[str, Any] = {
        "stopped_reason": result.stopped_reason,
        "num_rounds": len(result.rounds),
        "round_summaries": round_summaries,
        "returncode": 0,
    }
    if not judge_ready or not has_raw:
        out["returncode"] = 1
        out["error"] = "data_loader_not_ready"
        out["message"] = (
            (last.judge.reasoning if last and last.judge else "")
            or "Judge did not accept the download; check tickers, symbols, or date range."
        )
    if last and last.judge and last.judge.reasoning:
        out["judge_reasoning"] = last.judge.reasoning
    if result.rounds:
        out["last_spec"] = result.rounds[-1].spec
    return out
