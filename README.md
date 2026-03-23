# QuantAgent

Natural-language **research agent** for quant workflows: decompose a goal into subtasks, route tools, load data, run feature engineering, train models, backtest, evaluate, and emit an LLM-written final report. Progress streams to a **real-time dashboard** (WebSocket) with workflow visualization.

---

## Architecture overview

```
┌───────────────────────────────────────────────────────────────────┐
│  Browser  (React 19 + Tailwind v4 + Vite 8)                      │
│                                                                   │
│  GoalInput ──▶ POST /api/run ──▶ run_id                          │
│  useAgentSocket ◀── WebSocket /ws/{run_id} ◀── EventBus          │
│  ArtifactPanel ──▶ GET /api/workspace/{run_id}/{artifact}        │
│  ProgressBar · LogPanel · WorkflowGraph · ReportPanel            │
└──────────────────────────┬────────────────────────────────────────┘
                           │  Vite proxy (dev) / same origin (prod)
┌──────────────────────────▼────────────────────────────────────────┐
│  FastAPI  (server/app.py)                                         │
│                                                                   │
│  POST /api/run ──▶ RunManager.start_run (daemon thread)          │
│  WS   /ws/{run_id} ──▶ EventBus.subscribe(replay=True)          │
│  GET  /api/workspace/… ──▶ Workspace.list_artifacts / load       │
│  GET  /api/health                                                │
│  Static: frontend/dist (prod) or proxy to :5173 (dev)            │
└──────────────────────────┬────────────────────────────────────────┘
                           │
┌──────────────────────────▼────────────────────────────────────────┐
│  Orchestration  (scripts/workflow_demo.py)                        │
│                                                                   │
│  decompose_task (LLM) ──▶ TaskBreakdown ──▶ topo sort            │
│  for subtask in plan:                                            │
│      resolve_subtask_tool (LLM / heuristic)                      │
│      run_tool(tool_name, **kwargs)                               │
│      emit events ──▶ EventBus ──▶ WebSocket ──▶ Browser          │
│  generate_report (LLM) ──▶ final_report.json + run_done.report │
│  save final state ──▶ SQLite + Workspace                         │
└──────────────────────────┬────────────────────────────────────────┘
                           │
┌──────────────────────────▼────────────────────────────────────────┐
│  Tool layer  (scripts/tools/)                                     │
│                                                                   │
│  load_data ──▶ yfinance ──▶ raw_data.parquet                     │
│  run_data_analyst ──▶ sub-agent loop (skill → judge → plan)      │
│  build_features ──▶ feature_skill code-gen ──▶ engineered.parquet│
│  train_model ──▶ sklearn ──▶ model_output.json                    │
│  run_backtest ──▶ backtest skill ──▶ backtest_results.json       │
│  evaluate_strategy ──▶ LLM verdict ──▶ evaluation.json             │
└──────────────────────────┬────────────────────────────────────────┘
                           │
┌──────────────────────────▼────────────────────────────────────────┐
│  Persistence                                                      │
│                                                                   │
│  Workspace: data/workspaces/{run_id}/                            │
│    ├── manifest.json                                              │
│    ├── raw_data.parquet, feature_plan.json, engineered_data.parquet│
│    ├── model_output.json, backtest_results.json, evaluation.json │
│    └── final_report.json                                          │
│  SQLite: data/agent.db  (runs + log_entries)                     │
│  Skills output: data/analysis_runs/ · data/feature_runs/         │
└───────────────────────────────────────────────────────────────────┘
```

---

## Stack

| Layer    | Technology                     | Versions        |
|----------|--------------------------------|-----------------|
| Frontend | React, TypeScript, Tailwind    | 19 / 5.9 / 4.2  |
| Build    | Vite                           | 8.0             |
| Backend  | FastAPI, Uvicorn               | 0.135+ / 0.42+  |
| LLM      | OpenAI (structured output)    | SDK 2.29+       |
| Data     | pandas, numpy, pyarrow, yfinance | 3.0 / 2.4 / 23 / 1.2 |
| ML       | scikit-learn                   | 1.8+            |
| Storage  | SQLite, Parquet, JSON          | —               |
| Packages | uv (Python), npm (frontend)    | —               |

---

## Repository layout

```
.
├── frontend/                   # React SPA
│   ├── src/
│   │   ├── App.tsx             # Main shell: goal, progress, logs, artifacts, report
│   │   ├── hooks/
│   │   │   └── useAgentSocket.ts   # WebSocket + event stream
│   │   ├── components/
│   │   │   ├── GoalInput.tsx       # Goal + run button
│   │   │   ├── ProgressBar.tsx     # Subtask progress + connection status
│   │   │   ├── LogPanel.tsx        # Live event log
│   │   │   ├── WorkflowGraph.tsx   # Agent pipeline / collaboration view
│   │   │   ├── ArtifactPanel.tsx   # Workspace browser + preview
│   │   │   └── ReportPanel.tsx     # LLM final report + metrics
│   │   └── types.ts            # AgentEvent, WorkspaceManifest, etc.
│   ├── vite.config.ts          # Dev proxy: /api → :8000, /ws → ws://:8000
│   └── dist/                   # Production build (served by FastAPI)
│
├── server/                     # FastAPI app
│   ├── app.py                  # HTTP + WebSocket + static files
│   └── agent_runner.py         # RunManager: thread pool for agent runs
│
├── scripts/                    # Agent core
│   ├── workflow_demo.py        # End-to-end: decompose → topo run → DB + report
│   ├── dashboard_dev.py        # Dev: backend + frontend together
│   ├── agent/
│   │   ├── models.py           # Subtask, TaskBreakdown (Pydantic)
│   │   ├── state.py            # AgentState, ExecutionRecord
│   │   ├── events.py           # EventBus: thread-safe pub/sub + replay
│   │   ├── workspace.py        # Workspace: parquet/JSON artifacts
│   │   ├── executor.py         # run_subtask: route → tool → log
│   │   ├── tool_routing.py     # LLM SubtaskToolChoice + keyword fallback
│   │   ├── subtask_heuristic.py# Keyword routing fallback
│   │   ├── analysis_skill.py   # LLM-generated EDA scripts + subprocess
│   │   ├── feature_skill.py    # LLM-generated feature scripts + subprocess
│   │   ├── backtest_skill.py   # LLM-generated backtest scripts + subprocess
│   │   ├── data_analyst.py     # Sub-agent: analyze → judge → feature plan
│   │   ├── report_gen.py       # LLM final report → final_report.json
│   │   └── plan_revision.py    # revise_plan (NotImplementedError placeholder)
│   ├── llm/
│   │   ├── task_decompose.py   # NL → TaskBreakdown
│   │   └── yfinance_spec.py    # NL → YFinanceFetchSpec
│   ├── tools/
│   │   ├── __init__.py         # TOOL_REGISTRY + run_tool
│   │   ├── data.py             # load_data (yfinance)
│   │   ├── analysis.py         # run_data_analysis
│   │   ├── data_analyst_tool.py# run_data_analyst
│   │   ├── features.py         # build_features
│   │   ├── regressor.py        # train_model (sklearn)
│   │   ├── backtest.py         # run_backtest (skill-driven)
│   │   └── evaluation.py       # evaluate_strategy (LLM verdict)
│   ├── storage/
│   │   └── agent_log_db.py     # SQLite: runs + log_entries
│   └── docs/
│       ├── tools.md            # Tool catalog for LLM routing
│       └── yfinance_guide.md   # yfinance parameter guide for LLMs
│
├── skills/                     # Markdown specs for code-generating skills
│   ├── data_analysis.md
│   ├── feature_engineering.md
│   └── backtest.md
│
├── data/                       # Runtime (gitignored)
│   ├── agent.db
│   ├── workspaces/{run_id}/
│   ├── analysis_runs/{id}/
│   └── feature_runs/{id}/
│
├── pyproject.toml
└── .env.example
```

---

## Quick start

### 1. Setup

```bash
# Python
uv sync

# Frontend
cd frontend && npm install && cd ..

# Environment
cp .env.example .env
# Set OPENAI_API_KEY (and optional OPENAI_BASE_URL, OPENAI_SMALL_MODEL)
```

### 2. Dashboard (development)

**Option A — one command**

```bash
uv run python scripts/dashboard_dev.py
```

Starts:

- Backend `http://127.0.0.1:8000` (FastAPI + Uvicorn)
- Frontend `http://127.0.0.1:5173` (Vite; proxies `/api` and `/ws` to the backend)

Open `http://127.0.0.1:5173`.

**Option B — separate terminals**

```bash
# Terminal 1 — backend
uv run uvicorn server.app:app --host 127.0.0.1 --port 8000 --reload

# Terminal 2 — frontend
cd frontend && npm run dev -- --host 127.0.0.1 --port 5173
```

### 3. Production (single port)

```bash
cd frontend && npm run build && cd ..
uv run uvicorn server.app:app --host 0.0.0.0 --port 8000
```

Open `http://localhost:8000` (API + static UI, no dev proxy).

### 4. CLI only (no UI)

```bash
# Full pipeline (LLM, data, training, backtest, report, etc.)
uv run python scripts/workflow_demo.py "Download SPY daily for 1y, EDA, features, Ridge, backtest, evaluate"

# Decompose only
uv run python scripts/llm/task_decompose.py "Your research goal"

# yfinance kwargs from natural language
uv run python scripts/llm/yfinance_spec.py "S&P 500 ETF, 2 years daily"
```

---

## Data flow

```
User goal
    │
    ▼
POST /api/run { goal }
    │
    ▼
RunManager.start_run ──▶ daemon thread
    │
    ▼
workflow_demo.run_workflow
    ├── Workspace (data/workspaces/{run_id}/)
    ├── optional SQLite run row
    ├── emit("run_start")
    ├── decompose_task → TaskBreakdown → emit("decompose_done")
    ├── topo sort → emit("workflow_topo_order")
    ├── each subtask:
    │   ├── emit("subtask_start")
    │   ├── resolve_subtask_tool → emit("subtask_tool_resolved")
    │   ├── run_tool (reads/writes workspace)
    │   ├── emit("subtask_done")
    │   └── emit("workspace_update") when artifacts change
    ├── emit("report_generating") → generate_report → final_report.json
    ├── emit("workspace_update") for final_report (if saved)
    └── emit("run_done", report=...) ──▶ UI shows ReportPanel
```

---

## Events

`EventBus` (`scripts/agent/events.py`) backs real-time updates:

- **Thread-safe** history and subscriber queues  
- **`emit(type, **payload)`** appends history and notifies subscribers  
- **`subscribe(replay=True)`** returns `(id, queue, history)` for reconnect replay  
- **WebSocket bridge** in `server/app.py` (`asyncio.to_thread` on the queue)

| Event | When | Notable payload |
|-------|------|-----------------|
| `run_start` | Run begins | `run_id`, `goal` |
| `decompose_done` | Plan ready | `total_subtasks`, `subtasks` |
| `workflow_topo_order` | Topo order fixed | `order` |
| `subtask_start` | Subtask starts | `subtask_title`, … |
| `subtask_tool_resolved` | Tool chosen | `tool_name`, `kwargs` |
| `subtask_done` | Subtask ends | `status`, `summary`, `output` |
| `workspace_update` | Artifact changed | `artifact_name`, … |
| `data_analyst_round` | Analyst loop | round summaries (when used) |
| `report_generating` | Final report LLM started | `run_id` |
| `run_done` | Run finished | `status`, `workspace_summary`, `report` (structured final report) |

---

## Workspace

Each run uses `data/workspaces/{run_id}/`:

- **`manifest.json`** — artifact metadata (name, type, shape, timestamps)
- **Types** — `dataframe` (`.parquet`), `json`, generic `file`
- **HTTP** — `GET /api/workspace/{run_id}`, `GET /api/workspace/{run_id}/{name}` (JSON or dataframe preview)
- **Tools** — functions with a `workspace` parameter get it injected from `executor.py`

Typical artifact chain: `raw_data` → `feature_plan` → `engineered_data` → `model_output` → `backtest_results` → `evaluation` → `final_report`.

---

## Tools (summary)

| Tool | Role | Workspace |
|------|------|-------------|
| `load_data` | yfinance download (or demo stub) | writes `raw_data` |
| `run_data_analysis` | One-shot EDA skill | reads `raw_data` |
| `run_data_analyst` | Iterative analyst → feature plan | writes `feature_plan` |
| `build_features` | Feature skill from plan | reads `raw_data` + `feature_plan`, writes `engineered_data` |
| `train_model` | sklearn regression / tuning | reads data, writes `model_output` |
| `run_backtest` | Skill-driven backtest (hyperparameters) | reads data + `model_output`, writes `backtest_results` |
| `evaluate_strategy` | LLM strategy verdict | reads `backtest_results`, `model_output`, `feature_plan`; writes `evaluation` |

**Registry** — `scripts/tools/__init__.py` → `TOOL_REGISTRY`.  
**Routing** — `tool_routing.py` reads `docs/tools.md`; on failure, `subtask_heuristic.py`.  
**Injection** — `workspace` and `event_callback` injected when present in the tool signature.

---

## LLM usage

- **Client** — OpenAI Python SDK; optional `OPENAI_BASE_URL`
- **Default model** — `OPENAI_SMALL_MODEL` (e.g. small/mini model for routing, decomposition, skills, report)
- **Pattern** — `chat.completions.parse` + Pydantic `response_format` where applicable
- **Call sites** — task decomposition, tool choice, yfinance spec, analysis/feature/backtest script generation, data analyst judge/plan, strategy evaluation, final report

---

## Environment variables

```bash
# Required
OPENAI_API_KEY=sk-...

# Optional
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_SMALL_MODEL=gpt-4o-mini
ANTHROPIC_API_KEY=...
AGENT_DB_PATH=./data/agent.db
```

---

## Roadmap / gaps

| Item | Status |
|------|--------|
| Mid-run `revise_plan` | Placeholder only |
| Full multi-step ReAct loop | Plan-and-execute today; deeper replanning TBD |
| Metric-driven auto-iteration | e.g. Sharpe threshold → retry features |
| Tests & CI | To add |

---

## Security & data

- Do **not** commit `.env`, `data/agent.db`, or `data/workspaces/`
- SQLite: `runs` (goal, plan, final state), `log_entries` (typed events + JSON payloads)
- Add deps: `uv add <pkg>` (Python), `cd frontend && npm install <pkg>` (frontend)

---

_Python package name in `pyproject.toml` is `tools-research`; the public repo is often referred to as **QuantAgent**._
