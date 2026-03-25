"""
End-to-end demo: NL goal → decompose → topo-order subtasks → LLM tool routing → execution log.

Run from repo root:

    uv run python scripts/workflow_demo.py "your natural-language goal"
"""

from __future__ import annotations

import argparse
import inspect
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
from agent.report_gen import build_fallback_report, generate_report
from agent.state import AgentState, ExecutionRecord
from agent.tool_routing import filter_kwargs_for_tool
from agent.workspace import Workspace
from llm.task_decompose import decompose_task
from storage.agent_log_db import add_log, create_run, open_initialized, save_final_state, save_plan, set_run_status
from tools import TOOL_REGISTRY, run_tool

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
    interactive: bool = False,
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

    if interactive:
        from agent.clarifier import run_interactive_clarification

        goal = run_interactive_clarification(goal, model=model)
        log(f"[clarified goal] {goal}\n")

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
        if kind == "data_loader_round":
            event_bus.emit("data_loader_round", run_id=resolved_app_run_id, **payload)
        elif kind is not None:
            event_bus.emit(kind, run_id=resolved_app_run_id, **payload)
        else:
            event_bus.emit("data_analyst_round", run_id=resolved_app_run_id, **payload)

    previous_artifacts = ws.list_artifacts()
    total_subtasks = len(order)
    failed_subtask_ids: set[int] = set()

    def tool_output_indicates_failure(output: Any) -> bool:
        if not isinstance(output, dict):
            return False
        if output.get("error") not in (None, ""):
            return True
        rc = output.get("returncode")
        return rc is not None and rc != 0

    def emit_workspace_updates(previous: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
        current = ws.list_artifacts()
        if event_bus is not None:
            for artifact_name, meta in current.items():
                if previous.get(artifact_name) != meta:
                    event_bus.emit(
                        "workspace_update",
                        run_id=resolved_app_run_id,
                        artifact_name=artifact_name,
                        artifact=meta,
                    )
        return current

    def run_recovery_step(
        *,
        owner_subtask: Subtask,
        tool_name: str,
        raw_kwargs: dict[str, Any],
        reason: str = "",
    ) -> tuple[dict[str, Any], bool]:
        fn = TOOL_REGISTRY.get(tool_name)
        if fn is None:
            return {"error": "unknown_recovery_tool", "message": f"Unknown recovery tool: {tool_name}"}, True
        kwargs = filter_kwargs_for_tool(tool_name, dict(raw_kwargs))
        sig_params = inspect.signature(fn).parameters
        if ws is not None and "workspace" in sig_params:
            kwargs["workspace"] = ws
        if tool_event_callback is not None and "event_callback" in sig_params:
            kwargs["event_callback"] = tool_event_callback
        if "goal" in sig_params and "goal" not in kwargs:
            kwargs["goal"] = f"{owner_subtask.title}\n\nOverall objective: {state.goal}"
        if "query" in sig_params and "query" not in kwargs:
            kwargs["query"] = owner_subtask.description or owner_subtask.title
        if event_bus is not None:
            event_bus.emit(
                "recovery_step",
                run_id=resolved_app_run_id,
                subtask_id=owner_subtask.id,
                tool_name=tool_name,
                reason=reason,
                kwargs={k: str(v) for k, v in kwargs.items()},
            )
        try:
            output = run_tool(tool_name, **kwargs)
        except Exception as exc:  # noqa: BLE001
            return {"error": "recovery_exception", "message": str(exc)}, True
        return output, tool_output_indicates_failure(output)

    def emit_step_think(
        completed: Subtask,
        record: ExecutionRecord,
        next_st: Subtask | None,
        *,
        artifacts_for_prompt: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        if event_bus is None:
            return
        if os.environ.get("STEP_THINKING", "1").strip().lower() in ("0", "false", "no"):
            return
        from agent.step_thinking import think_after_subtask
        from tools import list_tools

        arts = artifacts_for_prompt if artifacts_for_prompt is not None else ws.list_artifacts()
        tw = think_after_subtask(
            goal=state.goal,
            workspace_artifacts=arts,
            completed=completed,
            record=record,
            next_subtask=next_st,
            allowed_tools=list_tools(),
            model=model,
        )
        event_bus.emit(
            "step_think",
            run_id=resolved_app_run_id,
            subtask_id=completed.id,
            subtask_title=completed.title,
            next_subtask_id=next_st.id if next_st else None,
            next_subtask_title=next_st.title if next_st else None,
            reasoning=str(tw.get("reasoning", "")),
            tools_to_consider=list(tw.get("tools_to_consider") or []),
            note_for_next_step=str(tw.get("note_for_next_step", "")),
            think_error=tw.get("error"),
        )

    for i, st in enumerate(order):
        idx = i + 1
        next_st = order[i + 1] if i + 1 < len(order) else None
        log(f"-- subtask {st.id}: {st.title[:60]}...")

        upstream_failures = failed_subtask_ids & set(st.dependencies)
        if upstream_failures:
            skip_msg = f"Skipped: upstream subtask(s) {sorted(upstream_failures)} failed"
            log(f"   SKIP — {skip_msg}\n")
            failed_subtask_ids.add(st.id)
            record = ExecutionRecord(
                subtask_id=st.id,
                tool_name="(skipped)",
                status="error",
                result_summary=skip_msg,
                output=None,
            )
            done = list(state.completed_subtasks)
            if st.id not in done:
                done.append(st.id)
            log_list = list(state.execution_log)
            log_list.append(record)
            state = state.model_copy(update={"completed_subtasks": done, "execution_log": log_list, "status": "failed"})
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
                event_bus.emit(
                    "subtask_done",
                    run_id=resolved_app_run_id,
                    subtask_id=st.id,
                    subtask_title=st.title,
                    tool_name="(skipped)",
                    status="skipped",
                    result_summary=skip_msg,
                    output=None,
                )
            if conn is not None and run_id is not None:
                add_log(conn, run_id, "tool_execution", f"subtask {st.id}", record.model_dump())
            emit_step_think(st, record, next_st)
            continue

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
        if last.status == "error":
            recovered = False
            if os.environ.get("DEBUG_AGENT_ON_FAILURE", "0").strip().lower() in ("1", "true", "yes"):
                try:
                    from agent.debug_agent import run_debug_analysis

                    dbg_model = os.environ.get("OPENAI_TASK_MODEL") or model
                    analysis = run_debug_analysis(
                        goal=state.goal,
                        workspace=ws,
                        query=last.result_summary,
                        subtask=st,
                        record=last,
                        model=dbg_model,
                    )
                    if not analysis.get("error"):
                        ws.save_json(
                            "debug_notes",
                            analysis,
                            description="Automatic debug analysis after subtask failure",
                        )
                        if event_bus is not None:
                            event_bus.emit(
                                "workspace_update",
                                run_id=resolved_app_run_id,
                                artifact_name="debug_notes",
                                artifact=ws.list_artifacts().get("debug_notes", {}),
                            )
                    if event_bus is not None:
                        event_bus.emit(
                            "debug_agent_done",
                            run_id=resolved_app_run_id,
                            subtask_id=st.id,
                            tool_name=last.tool_name,
                            summary=str(analysis.get("summary", ""))[:800],
                            category=str(analysis.get("category", "")),
                            debug_error=analysis.get("error"),
                        )
                    if not analysis.get("error") and analysis.get("should_retry_upstream"):
                        recovery_steps = list(analysis.get("recovery_steps") or [])
                        recovery_ok = True
                        for step in recovery_steps:
                            if not isinstance(step, dict):
                                recovery_ok = False
                                break
                            tool_name = str(step.get("tool_name") or "").strip()
                            step_kwargs = step.get("kwargs") if isinstance(step.get("kwargs"), dict) else {}
                            output, failed = run_recovery_step(
                                owner_subtask=st,
                                tool_name=tool_name,
                                raw_kwargs=step_kwargs,
                                reason=str(step.get("reason") or ""),
                            )
                            if conn is not None and run_id is not None:
                                add_log(
                                    conn,
                                    run_id,
                                    "recovery_step",
                                    f"subtask {st.id} -> {tool_name}",
                                    {"output": output, "failed": failed},
                                )
                            if failed:
                                recovery_ok = False
                                break
                            previous_artifacts = emit_workspace_updates(previous_artifacts)
                        if recovery_ok and analysis.get("retry_failed_subtask", True):
                            state = state.model_copy(update={"status": "running"})
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
                            log(f"   retry tool={last.tool_name} status={last.status} {last.result_summary}\n")
                            if last.status != "error":
                                recovered = True
                except Exception as dbg_exc:  # noqa: BLE001
                    if event_bus is not None:
                        event_bus.emit(
                            "debug_agent_done",
                            run_id=resolved_app_run_id,
                            subtask_id=st.id,
                            tool_name=last.tool_name,
                            summary="",
                            category="",
                            debug_error=str(dbg_exc),
                        )
            if not recovered:
                failed_subtask_ids.add(st.id)
        if conn is not None and run_id is not None:
            add_log(
                conn,
                run_id,
                "tool_execution",
                f"subtask {st.id}",
                last.model_dump(),
            )
        previous_artifacts = emit_workspace_updates(previous_artifacts)
        emit_step_think(st, last, next_st, artifacts_for_prompt=previous_artifacts)

    failed = bool(failed_subtask_ids)
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
        report = build_fallback_report(state, ws, error=str(exc))

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
        "--interactive", "-i",
        action="store_true",
        help="Run interactive clarification dialog before execution",
    )
    p.add_argument(
        "goal",
        nargs="*",
        default=[
            "Weekly futures momentum study: load data, engineer features, train a linear regression, backtest, "
            "then evaluate (focus on Sharpe and max drawdown)."
        ],
        help="Natural-language goal",
    )
    args = p.parse_args()
    goal = " ".join(args.goal).strip()
    if not goal:
        p.print_help()
        return 1
    result = run_workflow(goal, use_db=not args.no_db, interactive=args.interactive)
    return int(result["exit_code"])


if __name__ == "__main__":
    raise SystemExit(main())
