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
from pathlib import Path

from dotenv import load_dotenv

from agent.executor import run_subtask
from agent.models import Subtask
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


def main() -> int:
    load_dotenv()
    model = os.environ.get("OPENAI_SMALL_MODEL")
    if not model:
        print("Missing OPENAI_SMALL_MODEL", file=sys.stderr)
        return 1
    if not os.environ.get("OPENAI_API_KEY"):
        print("Missing OPENAI_API_KEY", file=sys.stderr)
        return 1

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

    conn = None
    run_id: int | None = None
    if not args.no_db:
        conn = open_initialized()
        run_id = create_run(
            conn,
            goal,
            metadata={"model": model, "script": "workflow_demo"},
        )
        add_log(conn, run_id, "user_input", "goal", {"text": goal})

    print("=== 1. Decompose ===\n")
    plan = decompose_task(goal, model=model)
    print(plan.model_dump_json(indent=2, ensure_ascii=False))
    print()
    if conn is not None and run_id is not None:
        save_plan(conn, run_id, plan)
        add_log(conn, run_id, "decompose", "TaskBreakdown saved", plan.model_dump())

    order = topo_order(plan.subtasks)
    print("=== 2. Subtask order (topo) ===\n", [s.id for s in order], "\n")
    if conn is not None and run_id is not None:
        add_log(conn, run_id, "workflow", "topo_order", {"order": [s.id for s in order]})

    ws_root = Path(__file__).resolve().parent.parent / "data" / "workspaces" / (f"run_{run_id}" if run_id else "scratch")
    ws = Workspace(ws_root, run_id=str(run_id) if run_id else None)
    print(f"=== Workspace: {ws.root} ===\n")

    state = AgentState(goal=goal, plan=plan, workspace_dir=str(ws.root), status="running")
    print("=== 3. Execute (LLM routing) ===\n")
    for st in order:
        print(f"-- subtask {st.id}: {st.title[:60]}...")
        state = run_subtask(
            state,
            st,
            workspace=ws,
            use_llm_routing=True,
            routing_model=model,
            routing_retries=2,
        )
        last = state.execution_log[-1]
        print(f"   tool={last.tool_name} status={last.status} {last.result_summary}\n")
        if conn is not None and run_id is not None:
            add_log(
                conn,
                run_id,
                "tool_execution",
                f"subtask {st.id}",
                last.model_dump(),
            )

    failed = any(r.status == "error" for r in state.execution_log)
    state = state.model_copy(update={"status": "failed" if failed else "done"})

    if conn is not None and run_id is not None:
        save_final_state(conn, run_id, state)
        set_run_status(conn, run_id, "failed" if failed else "done")
        conn.close()

    print("=== 4. Final AgentState ===\n")
    print(state.model_dump_json(indent=2, ensure_ascii=False))
    print(f"\n=== Workspace artifacts: {ws.summary()} ===\n")
    if run_id is not None:
        print(f"(run_id={run_id} logged to SQLite)\n")
    return 0 if not failed else 2


if __name__ == "__main__":
    raise SystemExit(main())
