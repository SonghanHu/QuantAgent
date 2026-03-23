"""Background runner for browser-triggered agent runs."""

from __future__ import annotations

import sys
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPTS_ROOT = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from agent.events import EventBus
from workflow_demo import run_workflow


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class RunContext:
    run_id: str
    goal: str
    model: str | None
    event_bus: EventBus
    thread: threading.Thread | None = None
    status: str = "queued"
    workspace_dir: str | None = None
    db_run_id: int | None = None
    error: str | None = None
    started_at: str = field(default_factory=utc_now_iso)
    finished_at: str | None = None


class RunManager:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._runs: dict[str, RunContext] = {}

    def start_run(self, goal: str, *, model: str | None = None) -> RunContext:
        run_id = uuid.uuid4().hex[:12]
        ctx = RunContext(run_id=run_id, goal=goal, model=model, event_bus=EventBus())
        thread = threading.Thread(target=self._run_target, args=(ctx,), daemon=True, name=f"agent-run-{run_id}")
        ctx.thread = thread
        with self._lock:
            self._runs[run_id] = ctx
        thread.start()
        return ctx

    def get_run(self, run_id: str) -> RunContext | None:
        with self._lock:
            return self._runs.get(run_id)

    def _run_target(self, ctx: RunContext) -> None:
        ctx.status = "running"
        try:
            result = run_workflow(
                ctx.goal,
                model=ctx.model,
                use_db=True,
                event_bus=ctx.event_bus,
                app_run_id=ctx.run_id,
                workspace_name=ctx.run_id,
                verbose=False,
            )
            ctx.status = result["state"].status
            ctx.workspace_dir = result["workspace_dir"]
            ctx.db_run_id = result["db_run_id"]
        except Exception as exc:  # noqa: BLE001
            ctx.status = "failed"
            ctx.error = str(exc)
            ctx.event_bus.emit(
                "run_done",
                run_id=ctx.run_id,
                db_run_id=ctx.db_run_id,
                status="failed",
                error=str(exc),
                workspace_dir=ctx.workspace_dir,
                workspace_summary="",
            )
        finally:
            ctx.finished_at = utc_now_iso()


run_manager = RunManager()


__all__ = ["RunContext", "RunManager", "run_manager"]
