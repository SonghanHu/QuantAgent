"""FastAPI app for real-time agent dashboard."""

from __future__ import annotations

import asyncio
import math
import sys
from pathlib import Path
from typing import Any

import pandas as pd
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

SCRIPTS_ROOT = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from agent.workspace import Workspace
from server.agent_runner import run_manager

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKSPACES_ROOT = REPO_ROOT / "data" / "workspaces"
FRONTEND_DIST = REPO_ROOT / "frontend" / "dist"

# LLM-generated scripts keyed by workspace run_id (same id as ``data/workspaces/<run_id>``).
_AGENT_SCRIPT_DEFS: tuple[tuple[str, Path, str, str], ...] = (
    ("analysis", REPO_ROOT / "data" / "analysis_runs", "analysis.py", "Data analysis"),
    ("feature_eng", REPO_ROOT / "data" / "feature_runs", "feature_eng.py", "Feature engineering"),
    ("alpha", REPO_ROOT / "data" / "alpha_runs", "alpha_eng.py", "Alpha factors"),
    ("backtest", REPO_ROOT / "data" / "backtest_runs", "backtest.py", "Backtest"),
)
_MAX_AGENT_SCRIPT_PREVIEW_CHARS = 400_000


def _list_agent_scripts(run_id: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for script_id, base, filename, label in _AGENT_SCRIPT_DEFS:
        p = (base / run_id / filename).resolve()
        base_r = base.resolve()
        if not p.is_relative_to(base_r) or p.name != filename:
            continue
        if p.is_file():
            st = p.stat()
            out.append(
                {
                    "id": script_id,
                    "filename": filename,
                    "label": label,
                    "size_bytes": st.st_size,
                }
            )
    return out


def _read_agent_script_file(run_id: str, script_id: str) -> str:
    for sid, base, filename, _label in _AGENT_SCRIPT_DEFS:
        if sid != script_id:
            continue
        p = (base / run_id / filename).resolve()
        base_r = base.resolve()
        if not p.is_relative_to(base_r) or p.name != filename or not p.is_file():
            raise HTTPException(status_code=404, detail=f"script not found: {script_id}")
        raw = p.read_text(encoding="utf-8", errors="replace")
        if len(raw) > _MAX_AGENT_SCRIPT_PREVIEW_CHARS:
            raw = raw[:_MAX_AGENT_SCRIPT_PREVIEW_CHARS] + "\n\n...[truncated for preview]..."
        return raw
    raise HTTPException(status_code=404, detail=f"unknown script id: {script_id}")

app = FastAPI(title="Agent Dashboard API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

if (FRONTEND_DIST / "assets").is_dir():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="frontend-assets")


class RunRequest(BaseModel):
    goal: str = Field(min_length=1)
    model: str | None = None


class ClarifyRequest(BaseModel):
    goal: str = Field(min_length=1)
    conversation: list[dict[str, str]] | None = None
    model: str | None = None


class PostRunChatRequest(BaseModel):
    """Follow-up chat after a run; server injects workspace context."""

    messages: list[dict[str, str]] = Field(min_length=1)
    model: str | None = None
    goal: str | None = Field(
        default=None,
        description="Optional original run goal (from UI); improves answers if not in artifacts.",
    )


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/run/{run_id}/chat")
def post_run_chat(run_id: str, req: PostRunChatRequest) -> dict[str, Any]:
    """Chat with an LLM grounded in the completed run's workspace (report, evaluation, etc.)."""
    from agent.post_run_chat import build_run_context_pack, chat_with_run_context

    ws = _open_workspace(run_id)
    try:
        pack = build_run_context_pack(ws, goal=req.goal)
        if len(pack) > 120_000:
            pack = pack[:119_000] + "\n\n...[context truncated for size]..."
        reply = chat_with_run_context(context_pack=pack, messages=req.messages, model=req.model)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"reply": reply, "run_id": run_id}


@app.post("/api/clarify")
def clarify(req: ClarifyRequest) -> dict[str, Any]:
    """Pre-execution clarification: ask LLM to understand the goal or ask questions."""
    from agent.clarifier import clarify_goal

    result = clarify_goal(req.goal, req.conversation, model=req.model)
    return result.model_dump()


@app.get("/")
def index() -> Any:
    index_path = FRONTEND_DIST / "index.html"
    if index_path.is_file():
        return FileResponse(index_path)
    return JSONResponse(
        {
            "message": "Frontend build not found.",
            "hint": "Run `npm run build` in `frontend/`, then open this URL again.",
        },
        status_code=503,
    )


@app.post("/api/run")
def start_run(req: RunRequest) -> dict[str, str]:
    ctx = run_manager.start_run(req.goal, model=req.model)
    return {"run_id": ctx.run_id, "status": ctx.status}


@app.websocket("/ws/{run_id}")
async def run_events(websocket: WebSocket, run_id: str) -> None:
    ctx = run_manager.get_run(run_id)
    if ctx is None:
        await websocket.close(code=4404, reason="run not found")
        return
    await websocket.accept()
    subscriber_id, queue, history = ctx.event_bus.subscribe(replay=True)
    try:
        for event in history:
            await websocket.send_json(event)
        while True:
            event = await asyncio.to_thread(queue.get)
            await websocket.send_json(event)
            if event.get("type") == "run_done":
                break
    except WebSocketDisconnect:
        pass
    finally:
        ctx.event_bus.unsubscribe(subscriber_id)


@app.get("/api/workspace/{run_id}")
def workspace_manifest(run_id: str) -> dict[str, Any]:
    ws = _open_workspace(run_id)
    return {
        "run_id": run_id,
        "workspace_dir": str(ws.root),
        "summary": ws.summary(),
        "artifacts": ws.list_artifacts(),
        "agent_scripts": _list_agent_scripts(run_id),
    }


@app.get("/api/workspace/{run_id}/agent-scripts/{script_id}")
def workspace_agent_script(run_id: str, script_id: str) -> dict[str, Any]:
    """Return generated Python for this run (analysis / features / alpha / backtest)."""
    _open_workspace(run_id)
    content = _read_agent_script_file(run_id, script_id)
    return {
        "artifact_name": f"script:{script_id}",
        "kind": "text",
        "language": "python",
        "content": content,
    }


@app.get("/api/workspace/{run_id}/report.md")
def workspace_report_md(run_id: str) -> Any:
    ws = _open_workspace(run_id)
    md_path = ws.root / "report.md"
    if not md_path.is_file():
        raise HTTPException(status_code=404, detail="report.md not found")
    return FileResponse(md_path, media_type="text/markdown", filename=f"report-{run_id}.md")


@app.get("/api/workspace/{run_id}/files/{artifact_name}")
def workspace_binary_file(run_id: str, artifact_name: str) -> FileResponse:
    """Serve workspace binary artifacts (e.g. PNG equity chart)."""
    ws = _open_workspace(run_id)
    artifacts = ws.list_artifacts()
    meta = artifacts.get(artifact_name)
    if meta is None or meta.get("kind") != "image":
        raise HTTPException(status_code=404, detail=f"image artifact not found: {artifact_name}")
    path = ws.artifact_path(artifact_name)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="file missing on disk")
    try:
        path.resolve().relative_to(ws.root.resolve())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid artifact path") from exc
    suffix = path.suffix.lower()
    media = "image/png" if suffix == ".png" else "application/octet-stream"
    return FileResponse(path, media_type=media, filename=path.name)


@app.get("/api/workspace/{run_id}/{artifact_name}")
def workspace_artifact(run_id: str, artifact_name: str) -> dict[str, Any]:
    ws = _open_workspace(run_id)
    artifacts = ws.list_artifacts()
    meta = artifacts.get(artifact_name)
    if meta is None:
        raise HTTPException(status_code=404, detail=f"artifact not found: {artifact_name}")
    if meta["kind"] == "json":
        return {
            "artifact_name": artifact_name,
            "kind": "json",
            "content": ws.load_json(artifact_name),
        }
    if meta["kind"] == "dataframe":
        df = ws.load_df(artifact_name)
        preview = (
            df.head(20)
            .reset_index()
            .rename(columns=str)
            .replace({math.nan: None})
        )
        preview.columns = [str(c) for c in preview.columns]
        return {
            "artifact_name": artifact_name,
            "kind": "dataframe",
            "shape": list(df.shape),
            "columns": [str(c) for c in df.columns],
            "preview_rows": preview.astype(object).where(pd.notnull(preview), None).to_dict(orient="records"),
        }
    if meta["kind"] == "image":
        return {
            "artifact_name": artifact_name,
            "kind": "image",
            "url": f"/api/workspace/{run_id}/files/{artifact_name}",
        }
    raise HTTPException(status_code=400, detail=f"unsupported artifact kind: {meta['kind']}")


def _open_workspace(run_id: str) -> Workspace:
    path = WORKSPACES_ROOT / run_id
    if not path.is_dir():
        raise HTTPException(status_code=404, detail=f"workspace not found for run_id={run_id}")
    return Workspace(path, run_id=run_id)


@app.get("/{full_path:path}")
def spa_fallback(full_path: str) -> Any:
    if full_path.startswith(("api/", "ws/")):
        raise HTTPException(status_code=404, detail="not found")
    index_path = FRONTEND_DIST / "index.html"
    if index_path.is_file():
        return FileResponse(index_path)
    raise HTTPException(status_code=404, detail=f"path not found: {full_path}")
