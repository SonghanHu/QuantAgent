"""
End-to-end demo: NL goal → decompose → topo-order subtasks → LLM tool routing → execution log.

Run from repo root:

    uv run python scripts/workflow_demo.py "你的任务描述"
"""

from __future__ import annotations

import argparse
import os
import sys
from collections import defaultdict, deque
from collections.abc import Callable
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from agent.events import EventBus
from agent.executor import run_subtask
from agent.models import Subtask
from agent.report_gen import generate_report
from agent.state import AgentState
from agent.workspace import Workspace
from llm.task_decompose import decompose_task
from storage.agent_log_db import add_log, create_run, open_initialized, save_final_state, save_plan, set_run_status

# Mid-run replan hook (not used yet): ``from agent.plan_revision import revise_plan``
# After a failed tool, bad backtest in ``state.artifacts``, or data checks, call:
#   new_plan = revise_plan(state.goal, state, model=model)
#   state = state.model_copy(update={
#       "plan": new_plan,
#       "plan_version": state.plan_version + 1,
#       "replan_triggers": [*state.replan_triggers, "sharpe_floor"],
#       "completed_subtasks": [],  # or keep done ids if you resume
#   })
#   order = topo_order(new_plan.subtasks)
#   ... continue execute loop


def topo_order(subtasks: list[Subtask]) -> list[Subtask]:
    """Dependency order; if cycle, fall back to id order."""
    by_id = {s.id: s for s in subtasks}
    ids = set(by_id)
    in_deg = {sid: 0 for sid in ids}
    children: dict[int, list[int]] = defaultdict(list)
    for s in subtasks:
        for d in s.dependencies:
            if d in ids:
                in_deg[s.id] += 1
                children[d].append(s.id)
    q = deque(sorted(sid for sid in ids if in_deg[sid] == 0))
    out: list[Subtask] = []
    while q:
        u = q.popleft()
        out.append(by_id[u])
        for v in sorted(children[u]):
            in_deg[v] -= 1
            if in_deg[v] == 0:
                q.append(v)
    if len(out) != len(ids):
        return sorted(subtasks, key=lambda s: s.id)
    return out


def run_workflow(
    goal: str,
    *,
    model: str | None = None,
    use_db: bool = True,
    event_bus: EventBus | None = None,
    app_run_id: str | None = None,
    workspace_name: str | None = None,
    verbose: bool = True,
) -> dict[str, Any]:
    load_dotenv()
    model = model or os.environ.get("OPENAI_SMALL_MODEL")
    if not model:
        raise RuntimeError("Missing OPENAI_SMALL_MODEL")
    if not os.environ.get("OPENAI_API_KEY"):
        raise RuntimeError("Missing OPENAI_API_KEY")

    def log(*parts: Any) -> None:
        if verbose:
            print(*parts)

    conn = None
    run_id: int | None = None
    if use_db:
        conn = open_initialized()
        run_id = create_run(
            conn,
            goal,
            metadata={"model": model, "script": "workflow_demo"},
        )
        add_log(conn, run_id, "user_input", "goal", {"text": goal})

    resolved_app_run_id = app_run_id or (f"db_{run_id}" if run_id is not None else "scratch")
    resolved_workspace_name = workspace_name or (f"run_{run_id}" if run_id is not None else resolved_app_run_id)
    ws_root = Path(__file__).resolve().parent.parent / "data" / "workspaces" / resolved_workspace_name
    ws = Workspace(ws_root, run_id=resolved_app_run_id)
    if event_bus is not None:
        event_bus.emit(
            "run_start",
            run_id=resolved_app_run_id,
            db_run_id=run_id,
            goal=goal,
            model=model,
            workspace_dir=str(ws.root),
        )

    log("=== 1. Decompose ===\n")
    plan = decompose_task(goal, model=model)
    log(plan.model_dump_json(indent=2, ensure_ascii=False))
    log()
    if conn is not None and run_id is not None:
        save_plan(conn, run_id, plan)
        add_log(conn, run_id, "decompose", "TaskBreakdown saved", plan.model_dump())
    if event_bus is not None:
        event_bus.emit(
            "decompose_done",
            run_id=resolved_app_run_id,
            goal_summary=plan.goal_summary,
            total_subtasks=len(plan.subtasks),
            subtasks=[s.model_dump() for s in plan.subtasks],
        )

    order = topo_order(plan.subtasks)
    log("=== 2. Subtask order (topo) ===\n", [s.id for s in order], "\n")
    if conn is not None and run_id is not None:
        add_log(conn, run_id, "workflow", "topo_order", {"order": [s.id for s in order]})
    if event_bus is not None:
        event_bus.emit("workflow_topo_order", run_id=resolved_app_run_id, order=[s.id for s in order])

    log(f"=== Workspace: {ws.root} ===\n")

    state = AgentState(goal=goal, plan=plan, workspace_dir=str(ws.root), status="running")
    log("=== 3. Execute (LLM routing) ===\n")

    def tool_event_callback(event: dict[str, Any]) -> None:
        if event_bus is None:
            return
        kind = event.get("type")
        payload = {k: v for k, v in event.items() if k != "type"}
        if kind is not None:
            event_bus.emit(kind, run_id=resolved_app_run_id, **payload)
        else:
            event_bus.emit("data_analyst_round", run_id=resolved_app_run_id, **payload)

    previous_artifacts = ws.list_artifacts()
    total_subtasks = len(order)
    for idx, st in enumerate(order, start=1):
        log(f"-- subtask {st.id}: {st.title[:60]}...")
        if event_bus is not None:
            event_bus.emit(
                "subtask_start",
                run_id=resolved_app_run_id,
                subtask_id=st.id,
                subtask_title=st.title,
                position=idx,
                total=total_subtasks,
                completed=len(state.completed_subtasks),
            )
        state = run_subtask(
            state,
            st,
            workspace=ws,
            use_llm_routing=True,
            routing_model=model,
            routing_retries=2,
            event_callback=tool_event_callback,
        )
        last = state.execution_log[-1]
        log(f"   tool={last.tool_name} status={last.status} {last.result_summary}\n")
        if conn is not None and run_id is not None:
            add_log(
                conn,
                run_id,
                "tool_execution",
                f"subtask {st.id}",
                last.model_dump(),
            )
        current_artifacts = ws.list_artifacts()
        if event_bus is not None:
            for artifact_name, meta in current_artifacts.items():
                if previous_artifacts.get(artifact_name) != meta:
                    event_bus.emit(
                        "workspace_update",
                        run_id=resolved_app_run_id,
                        artifact_name=artifact_name,
                        artifact=meta,
                    )
        previous_artifacts = current_artifacts

    failed = any(r.status == "error" for r in state.execution_log)
    state = state.model_copy(update={"status": "failed" if failed else "done"})

    if conn is not None and run_id is not None:
        save_final_state(conn, run_id, state)
        set_run_status(conn, run_id, "failed" if failed else "done")
        conn.close()

    log("=== 4. Generate final report ===\n")
    report: dict[str, Any] | None = None
    try:
        if event_bus is not None:
            event_bus.emit("report_generating", run_id=resolved_app_run_id)
        report = generate_report(state, ws, model=model)
        log(f"Report: {report.get('title', '?')}\n")
        if event_bus is not None:
            event_bus.emit(
                "workspace_update",
                run_id=resolved_app_run_id,
                artifact_name="final_report",
                artifact=ws.list_artifacts().get("final_report", {}),
            )
    except Exception as exc:  # noqa: BLE001
        log(f"Report generation failed: {exc}\n")
        report = None

    log("=== 5. Final AgentState ===\n")
    log(state.model_dump_json(indent=2, ensure_ascii=False))
    log(f"\n=== Workspace artifacts: {ws.summary()} ===\n")
    if run_id is not None:
        log(f"(run_id={run_id} logged to SQLite)\n")
    if event_bus is not None:
        event_bus.emit(
            "run_done",
            run_id=resolved_app_run_id,
            db_run_id=run_id,
            status=state.status,
            final_state=state.model_dump(mode="json"),
            workspace_dir=str(ws.root),
            workspace_summary=ws.summary(),
            report=report,
        )
    return {
        "exit_code": 0 if not failed else 2,
        "run_id": resolved_app_run_id,
        "db_run_id": run_id,
        "state": state,
        "workspace_dir": str(ws.root),
        "workspace_summary": ws.summary(),
    }


def main() -> int:
    p = argparse.ArgumentParser(description="Full agent workflow demo")
    p.add_argument(
        "--no-db",
        action="store_true",
        help="Do not write SQLite logs under data/agent.db",
    )
    p.add_argument(
        "goal",
        nargs="*",
        default=[
            "期货周频动量研究：加载数据、建特征、线性回归训练、回测，最后给出评估结论（关注Sharpe和回撤）。"
        ],
        help="Natural-language goal",
    )
    args = p.parse_args()
    goal = " ".join(args.goal).strip()
    if not goal:
        p.print_help()
        return 1
    result = run_workflow(goal, use_db=not args.no_db)
    return int(result["exit_code"])


if __name__ == "__main__":
    raise SystemExit(main())
