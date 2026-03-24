# QuantAgent

Natural-language **research agent** for quant workflows: decompose a goal into subtasks, route tools, load data, engineer features or WorldQuant-style alphas, train models, backtest strategies, evaluate performance, and emit an LLM-written final report (JSON + Markdown). Progress streams to a **real-time dashboard** via WebSocket.

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
│  POST /api/run      ──▶ RunManager.start_run (daemon thread)     │
│  POST /api/clarify  ──▶ Pre-execution goal clarification (LLM)   │
│  WS   /ws/{run_id}  ──▶ EventBus.subscribe(replay=True)         │
│  GET  /api/workspace/… ──▶ Workspace.list_artifacts / load       │
│  GET  /api/health                                                │
│  Static: frontend/dist (prod) or proxy to :5173 (dev)            │
└──────────────────────────┬────────────────────────────────────────┘
                           │
┌──────────────────────────▼────────────────────────────────────────┐
│  Orchestration  (scripts/workflow_demo.py)                        │
│                                                                   │
│  [optional] interactive clarification (--interactive / API)       │
│  decompose_task (LLM, 4-8 subtasks) ──▶ TaskBreakdown ──▶ topo  │
│  for subtask in plan:                                            │
│      resolve_subtask_tool (LLM / heuristic)                      │
│      run_tool(tool_name, **kwargs)                               │
│      emit events ──▶ EventBus ──▶ WebSocket ──▶ Browser          │
│  generate_report (LLM) ──▶ final_report.json + report.md        │
│  save final state ──▶ SQLite + Workspace                         │
└──────────────────────────┬────────────────────────────────────────┘
                           │
┌──────────────────────────▼────────────────────────────────────────┐
│  Tool layer  (scripts/tools/)                                     │
│                                                                   │
│  web_search     ──▶ Brave API ──▶ search_context.json            │
│  load_data      ──▶ yfinance ──▶ raw_data.parquet                │
│  run_data_analyst ──▶ sub-agent loop (skill → judge → plan)      │
│  build_features ──▶ feature_skill code-gen ──▶ engineered.parquet│
│  build_alphas   ──▶ alpha_skill (WorldQuant-style) ──▶ same     │
│  train_model    ──▶ sklearn ──▶ model_output.json                │
│  run_backtest   ──▶ backtest skill ──▶ backtest_results.json     │
│  evaluate_strategy ──▶ LLM verdict ──▶ evaluation.json           │
└──────────────────────────┬────────────────────────────────────────┘
                           │
┌──────────────────────────▼────────────────────────────────────────┐
│  Persistence                                                      │
│                                                                   │
│  Workspace: data/workspaces/{run_id}/                            │
│    ├── manifest.json                                              │
│    ├── raw_data.parquet, feature_plan.json, engineered_data.pqt  │
│    ├── model_output.json, backtest_results.json, evaluation.json │
│    ├── search_context.json                                        │
│    ├── final_report.json                                          │
│    └── report.md  ◀── human-readable final report                │
│  SQLite: data/agent.db  (runs + log_entries)                     │
│  Skills output: data/{analysis,feature,alpha,backtest}_runs/     │
└───────────────────────────────────────────────────────────────────┘
```

---

## Stack

| Layer    | Technology                     | Notes           |
|----------|--------------------------------|-----------------|
| Frontend | React, TypeScript, Tailwind    | 19 / 5.9 / v4   |
| Build    | Vite                           | 8.0             |
| Backend  | FastAPI, Uvicorn               | 0.135+ / 0.42+  |
| LLM      | OpenAI (structured output)    | SDK 2.29+       |
| Search   | Brave Search API              | Web context for alpha research |
| Data     | pandas, numpy, pyarrow, yfinance | 3.0+ / 2.4+ / 23+ / 1.2+ |
| ML       | scikit-learn                   | 1.8+            |
| Storage  | SQLite, Parquet, JSON, Markdown | —              |
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
│   │   └── components/
│   │       ├── GoalInput.tsx       # Goal + run button
│   │       ├── ProgressBar.tsx     # Subtask progress + connection status
│   │       ├── LogPanel.tsx        # Live event log
│   │       ├── WorkflowGraph.tsx   # Agent pipeline / collaboration view
│   │       ├── ArtifactPanel.tsx   # Workspace browser + preview
│   │       └── ReportPanel.tsx     # LLM final report + metrics
│   ├── vite.config.ts          # Dev proxy: /api → :8000, /ws → ws://:8000
│   └── dist/                   # Production build (served by FastAPI)
│
├── server/                     # FastAPI app
│   ├── app.py                  # HTTP + WebSocket + /api/clarify + static files
│   └── agent_runner.py         # RunManager: thread pool for agent runs
│
├── scripts/                    # Agent core
│   ├── workflow_demo.py        # End-to-end: [clarify →] decompose → topo run → report
│   ├── dashboard_dev.py        # Dev: backend + frontend together
│   ├── agent/
│   │   ├── models.py           # Subtask, TaskBreakdown (Pydantic)
│   │   ├── state.py            # AgentState, ExecutionRecord
│   │   ├── events.py           # EventBus: thread-safe pub/sub + replay
│   │   ├── workspace.py        # Workspace: parquet/JSON artifacts
│   │   ├── executor.py         # run_subtask: route → tool → log (error-aware)
│   │   ├── tool_routing.py     # LLM SubtaskToolChoice + keyword fallback
│   │   ├── subtask_heuristic.py# Keyword routing fallback
│   │   ├── clarifier.py        # Pre-execution goal clarification dialog
│   │   ├── analysis_skill.py   # LLM-generated EDA scripts + retry
│   │   ├── feature_skill.py    # LLM-generated feature scripts + retry
│   │   ├── alpha_skill.py      # LLM-generated WorldQuant alpha scripts + retry
│   │   ├── backtest_skill.py   # LLM-generated backtest scripts + retry
│   │   ├── data_analyst.py     # Sub-agent: analyze → judge → feature plan
│   │   ├── report_gen.py       # LLM final report → JSON + Markdown
│   │   └── plan_revision.py    # revise_plan (placeholder)
│   ├── llm/
│   │   ├── task_decompose.py   # NL → TaskBreakdown (4-8 tool-aligned subtasks)
│   │   └── yfinance_spec.py    # NL → YFinanceFetchSpec
│   ├── tools/
│   │   ├── __init__.py         # TOOL_REGISTRY + run_tool
│   │   ├── search.py           # web_search (Brave API)
│   │   ├── data.py             # load_data (yfinance)
│   │   ├── analysis.py         # run_data_analysis
│   │   ├── data_analyst_tool.py# run_data_analyst
│   │   ├── features.py         # build_features (validated)
│   │   ├── alpha.py            # build_alphas (WorldQuant-style)
│   │   ├── regressor.py        # train_model (sklearn, workspace-aligned target)
│   │   ├── backtest.py         # run_backtest (pre-checked data/model match)
│   │   └── evaluation.py       # evaluate_strategy (LLM verdict)
│   ├── storage/
│   │   └── agent_log_db.py     # SQLite: runs + log_entries
│   └── docs/
│       ├── tools.md            # Tool catalog for LLM routing (9 tools)
│       └── yfinance_guide.md   # yfinance parameter guide for LLMs
│
├── skills/                     # Markdown specs for code-generating skills
│   ├── data_analysis.md
│   ├── feature_engineering.md
│   ├── alpha_engineering.md    # WorldQuant-style alpha factor construction
│   └── backtest.md
│
├── data/                       # Runtime (gitignored)
│   ├── agent.db
│   ├── workspaces/{run_id}/
│   ├── analysis_runs/{id}/
│   ├── feature_runs/{id}/
│   ├── alpha_runs/{id}/
│   └── backtest_runs/{id}/
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
# Required: OPENAI_API_KEY
# Recommended: OPENAI_TASK_MODEL (code gen), OPENAI_SMALL_MODEL (routing/judge)
# Optional: BRAVE_API_KEY (web search)
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

### 4. CLI

```bash
# Full pipeline
uv run python scripts/workflow_demo.py "Download SPY 2y, build alpha factors, train ridge, backtest, evaluate"

# Interactive mode (clarification dialog before execution)
uv run python scripts/workflow_demo.py -i "Build me an alpha strategy"

# Decompose only
uv run python scripts/llm/task_decompose.py "Your research goal"
```

---

## Tool pipeline

| # | Tool | Role | Reads | Writes |
|---|------|------|-------|--------|
| 1 | `web_search` | Search web for research context (Brave API) | — | `search_context` |
| 2 | `load_data` | Download market data (yfinance) or demo stub | — | `raw_data` |
| 3 | `run_data_analyst` | Iterative EDA sub-agent → feature plan | `raw_data` | `feature_plan` |
| 4a | `build_features` | Feature engineering from plan | `raw_data` + `feature_plan` | `engineered_data` |
| 4b | `build_alphas` | WorldQuant-style alpha construction | `raw_data` + `feature_plan` + `search_context` | `engineered_data` |
| 5 | `train_model` | sklearn regression / tuning | `engineered_data` (or `raw_data`) | `model_output` |
| 6 | `run_backtest` | Skill-driven strategy backtest | `engineered_data` + `model_output` | `backtest_results` |
| 7 | `evaluate_strategy` | LLM strategy verdict | `backtest_results` + `model_output` | `evaluation` |

`run_data_analysis` is available as a single-shot EDA alternative to `run_data_analyst`.

**Registry** — `scripts/tools/__init__.py` → `TOOL_REGISTRY` (9 tools).  
**Routing** — `tool_routing.py` reads `docs/tools.md` for LLM routing; `subtask_heuristic.py` as fallback.  
**Injection** — `workspace` and `event_callback` auto-injected when present in a tool's signature.

### Validations

- `build_features` / `build_alphas` — rejects empty plans, sanitizes target column names, post-checks output contains target
- `train_model` — aligns with `feature_plan.target_column` from workspace; auto-derives target from price if missing; time-ordered split for datetime data
- `run_backtest` — pre-checks data/model column alignment before script generation
- `executor` — detects tool-returned error dicts (not just Python exceptions)

---

## LLM model tiers

| Role | Env var | Typical model | Used by |
|------|---------|---------------|---------|
| **Code generation** | `OPENAI_TASK_MODEL` | gpt-4o-mini / gpt-5.4-mini | analysis_skill, feature_skill, alpha_skill, backtest_skill |
| **Routing / judging** | `OPENAI_SMALL_MODEL` | gpt-4o-nano / gpt-5.4-nano | decomposition, tool routing, data analyst judge, feature planner, evaluation, report |

All skills use `parse_script_with_retry()` (up to 2 retries on JSON parse errors).

---

## Interactive clarification

Before execution, the agent can ask clarifying questions to understand the user's intent:

```
$ uv run python scripts/workflow_demo.py -i "Build me an alpha strategy"

I have a few questions before starting:

  1. Which assets should the strategy trade? (Default: S&P 500, daily)
  2. Are we predicting next-day returns or building a ranking? (Default: next-day return)
  3. Long-only or long-short? Transaction costs? (Default: long-short, 10bps)
  4. What metrics matter most? (Default: Sharpe, max drawdown)

Your answers: Use defaults, but make it long-only with SPY

Goal understood. Proceeding...
```

API: `POST /api/clarify { goal, conversation }` returns `{ understood, refined_goal, questions, assumptions }`.

---

## Output

Each run produces:

- **`final_report.json`** — structured report (title, sections, findings, recommendations, limitations)
- **`report.md`** — human-readable Markdown version of the same report
- **`evaluation.json`** — LLM strategy verdict (rating, strengths, weaknesses, next steps)
- **`backtest_results.json`** — Sharpe, drawdown, equity curve, turnover, etc.
- All workspace artifacts accessible via `GET /api/workspace/{run_id}/{name}`

---

## Events

`EventBus` backs real-time updates (thread-safe, replay-capable):

| Event | When | Notable payload |
|-------|------|-----------------|
| `run_start` | Run begins | `run_id`, `goal` |
| `decompose_done` | Plan ready | `total_subtasks`, `subtasks` |
| `subtask_start` | Subtask starts | `subtask_title`, `position`, `total` |
| `subtask_done` | Subtask ends | `status`, `summary`, `output` |
| `workspace_update` | Artifact changed | `artifact_name` |
| `debug_agent_done` | After automatic or tool debug analysis | `summary`, `category`, `subtask_id`, `debug_error` |
| `step_think` | After each subtask (incl. skip) | `reasoning`, `tools_to_consider`, `note_for_next_step`, `next_subtask_id` |
| `data_analyst_round` | Analyst loop | `stage`, `round`, `ready`, `reasoning` |
| `data_loader_round` | Data-ingest judge loop | `spec_propose` / `load_done` / `judge_done` |
| `report_generating` | Report LLM started | — |
| `run_done` | Run finished | `status`, `report` (structured) |

---

## Environment variables

```bash
# Required
OPENAI_API_KEY=sk-...

# Recommended
OPENAI_TASK_MODEL=gpt-4o-mini      # Code generation (larger, more capable)
OPENAI_SMALL_MODEL=gpt-4o-nano     # Routing, judging, planning (fast, cheap)

# Optional
OPENAI_BASE_URL=https://api.openai.com/v1
BRAVE_API_KEY=...                   # Web search tool
ANTHROPIC_API_KEY=...
AGENT_DB_PATH=./data/agent.db

# After each failed subtask, run the debug LLM and write debug_notes.json (optional)
# DEBUG_AGENT_ON_FAILURE=1

# After each subtask, run step reflection (which tools matter next, e.g. web_search before load_data). Default on.
# STEP_THINKING=0
```

---

## Roadmap

| Item | Status |
|------|--------|
| Mid-run `revise_plan` | Placeholder |
| Metric-driven auto-iteration (e.g. Sharpe threshold → retry) | Planned |
| Multi-asset panel support | Planned |
| Classification models (long/short signal) | Planned |
| Tests & CI | To add |

---

## Security & data

- Do **not** commit `.env`, `data/agent.db`, or `data/workspaces/`
- LLM-generated scripts run locally with a naive denylist — use in trusted environments only
- Add deps: `uv add <pkg>` (Python), `cd frontend && npm install <pkg>` (frontend)

---

_Python package name in `pyproject.toml` is `tools-research`; the public repo is **QuantAgent**._
