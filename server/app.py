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


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


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
    }


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
