"""
Mid-run plan revision: regenerate a ``TaskBreakdown`` after tool failure while preserving
completed subtasks (same ids) so the workflow can skip re-execution and continue.
"""

from __future__ import annotations

import json
import os
from typing import Any

from dotenv import load_dotenv
from openai import OpenAI

from agent.models import TaskBreakdown
from agent.state import AgentState


def _client() -> OpenAI:
    load_dotenv()
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("OPENAI_API_KEY is not set.")
    base = os.environ.get("OPENAI_BASE_URL")
    kwargs: dict[str, Any] = {"api_key": key}
    if base:
        kwargs["base_url"] = base.rstrip("/")
    return OpenAI(**kwargs)


def revise_plan(
    goal: str,
    state: AgentState,
    *,
    model: str,
    failure_summary: str,
    failed_subtask_id: int,
) -> TaskBreakdown:
    """
    Produce a revised full plan: keep successful subtasks unchanged (same ids), fix the failure and downstream.
    """
    if state.plan is None:
        raise ValueError("state.plan is required for revision")

    client = _client()
    log_tail = state.execution_log[-16:]
    system = (
        "You revise a quantitative research TaskBreakdown after a tool failure.\n"
        "Return a **full** TaskBreakdown (same schema as initial decomposition).\n\n"
        "Rules:\n"
        "- For every subtask that **already completed successfully** (see execution log: status ok), "
        "keep the **same id, title, description, and dependencies** so the runner can skip them.\n"
        "- Focus changes on the failed subtask id and any steps that must run after it (fix wording, deps, "
        "or split a step). Keep 4–8 subtasks total unless the user goal is narrower.\n"
        "- Dependencies must form a valid DAG. `run_backtest` must depend on feature/model steps; "
        "`evaluate_strategy` must depend on `run_backtest`.\n"
        "- Do not invent completed tools; align with what the log shows.\n"
        "- **Hard vs soft defaults (不可丢失约束):** Preserve HARD constraints from the ORIGINAL user goal exactly: "
        "asset/universe, prediction/target definition, strategy economics (e.g. long/flat with thresholding), "
        "rebalance cadence, transaction-cost assumption (0 unless explicitly requested), and requested model family. "
        "Only modify SOFT defaults (threshold when unspecified, hyperparameter tuning choices) when necessary.\n"
        "- If `train_model` is present and the user explicitly requested a model family, keep the `Requested model: ...` "
        "line in the `train_model` subtask description so the tool can pass `requested_model_name`.\n"
    )
    user = (
        f"## Goal\n{goal.strip()}\n\n"
        f"## Current plan\n{json.dumps(state.plan.model_dump(), ensure_ascii=False, indent=2)}\n\n"
        f"## Failed subtask id\n{failed_subtask_id}\n\n"
        f"## Failure summary\n{failure_summary[:8000]}\n\n"
        f"## Recent execution log\n"
        f"{json.dumps([r.model_dump() for r in log_tail], ensure_ascii=False)[:14000]}\n"
    )
    completion = client.chat.completions.parse(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        response_format=TaskBreakdown,
    )
    parsed = completion.choices[0].message.parsed
    if parsed is None:
        raise RuntimeError("Model returned no structured plan for revision.")
    return parsed


__all__ = ["revise_plan"]
