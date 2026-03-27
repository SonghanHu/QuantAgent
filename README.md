# QuantAgent

Natural-language **research agent** for quant workflows: decompose a goal into subtasks, route tools, load data, engineer features or WorldQuant-style alphas, optionally train models, backtest rule-based or predictive strategies, evaluate performance, and emit an LLM-written final report (JSON + Markdown). Progress streams to a **real-time dashboard** via WebSocket. After a run finishes, the dashboard can **continue a grounded chat** with the same workspace context (reports, evaluation, backtest summary, feature plan, etc.).

---

## Architecture overview

QuantAgent has four layers:

1. A React dashboard submits a goal, streams progress, and uses **tabbed panels** (**Activity** = pipeline + live log, **Workspace** = artifacts + **LLM-generated Python scripts** preview + **interactive equity chart** when `equity_viz` exists, **Report** = final report + post-run Q&A). After `run_done`, **Ask about this run** stays grounded in workspace artifacts.
2. A FastAPI server starts runs, persists run metadata, and relays events over WebSocket.
3. The workflow orchestrator decomposes the goal into tool-shaped subtasks, executes them in dependency order, and records artifacts plus status.
4. The tool layer mixes fixed implementations (`yfinance`, sklearn, SQLite/workspace IO) with skill-driven code generation for analysis, feature engineering, alpha construction, and backtesting.

Two pipeline styles are first-class:

- **Predictive / ML**: `web_search` → `run_data_loader` → `run_data_analyst` → `build_features` or `build_alphas` → `train_model` → `run_backtest` → `evaluate_strategy`
- **Rule-based**: `web_search` → `run_data_loader` → `run_data_analyst` → `build_features` → `run_backtest` → `evaluate_strategy`

The orchestrator **repairs plan edges** after decomposition (e.g. ensures `run_backtest` depends on feature/model steps), **halts downstream subtasks** after a hard failure (configurable), runs **automatic subtask retries** with the error appended to the description, optionally **replans** with `revise_plan` (full `TaskBreakdown`, preserving successful step ids), and can still run the debug agent + recovery + one retry when `DEBUG_AGENT_ON_FAILURE=1`. After each step it may emit `step_think` hints.

```
┌───────────────────────────────────────────────────────────────────┐
│  Browser  (React 19 + Tailwind v4 + Vite 8)                      │
│                                                                   │
│  GoalInput ──▶ POST /api/run ──▶ run_id                          │
│  useAgentSocket ◀── WebSocket /ws/{run_id} ◀── EventBus          │
│  GET /api/workspace/{id} (manifest + agent_scripts)             │
│  ArtifactPanel ──▶ artifacts, equity_viz chart, …/files (PNG), scripts │
│  ReportPanel ──▶ POST /api/run/{run_id}/chat (after run_done)    │
│  Tabs: Activity · Workspace · Report (keys 1–3)                  │
└──────────────────────────┬────────────────────────────────────────┘
                           │  Vite proxy (dev) / same origin (prod)
┌──────────────────────────▼────────────────────────────────────────┐
│  FastAPI  (server/app.py)                                         │
│                                                                   │
│  POST /api/run      ──▶ RunManager.start_run (daemon thread)     │
│  POST /api/clarify  ──▶ Pre-execution goal clarification (LLM)   │
│  POST /api/run/{id}/chat ──▶ Post-run Q&A (workspace context)     │
│  WS   /ws/{run_id}  ──▶ EventBus.subscribe(replay=True)         │
│  GET  /api/workspace/{id} ──▶ manifest (+ agent_scripts list)      │
│  GET  /api/workspace/{id}/files/{artifact} ──▶ binary (e.g. PNG) │
│  GET  /api/workspace/{id}/{artifact} | …/agent-scripts/{key}    │
│  GET  /api/health                                                │
│  Static: frontend/dist (prod) or proxy to :5173 (dev)            │
└──────────────────────────┬────────────────────────────────────────┘
                           │
┌──────────────────────────▼────────────────────────────────────────┐
│  Orchestration  (scripts/workflow_demo.py)                        │
│                                                                   │
│  [optional] interactive clarification (--interactive / API)       │
│  decompose_task ──▶ repair_plan_dependencies ──▶ TaskBreakdown │
│  loop: topo order; skip subtasks already ok after replan          │
│  for subtask: resolve_subtask_tool → run_tool                     │
│  on failure: N× retry w/ error in description → [debug path] →   │
│      revise_plan (optional) → restart topo; else halt downstream  │
│  emit step_think after each step (unless STEP_THINKING=0)         │
│  generate_report (LLM) ──▶ final_report.json + report.md        │
│  equity_viz (if backtest_results) ──▶ equity_viz.json + chart PNG │
│  save final state ──▶ SQLite + Workspace                         │
└──────────────────────────┬────────────────────────────────────────┘
                           │
┌──────────────────────────▼────────────────────────────────────────┐
│  Tool layer  (scripts/tools/)                                     │
│                                                                   │
│  web_search       ──▶ Brave API ──▶ search_context.json          │
│  run_data_loader  ──▶ propose spec → load → judge → raw_data     │
│  load_data        ──▶ one-shot yfinance fetch → raw_data         │
│  run_data_analyst ──▶ sub-agent loop (skill → judge → plan)      │
│  build_features   ──▶ feature_skill code-gen ──▶ engineered_data │
│  build_alphas     ──▶ alpha_skill (WorldQuant-style) ──▶ same    │
│  train_model      ──▶ sklearn regression ──▶ model_output.json   │
│  run_backtest     ──▶ backtest skill ──▶ backtest_results.json   │
│                      (model_based or rule_based)                 │
│  run_debug_agent  ──▶ structured diagnosis ──▶ debug_notes.json  │
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
│    ├── debug_notes.json                                           │
│    ├── final_report.json                                          │
│    ├── equity_viz.json, equity_chart.png (optional, post-report)  │
│    └── report.md  ◀── human-readable final report                │
│  SQLite: data/agent.db  (runs + log_entries)                     │
│  Skills output: data/{analysis,feature,alpha,backtest}_runs/     │
│    (same run_id as workspace → stable paths + UI script preview) │
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
│   │   ├── App.tsx             # Tabbed shell: Activity / Workspace / Report
│   │   ├── hooks/
│   │   │   └── useAgentSocket.ts   # WebSocket + event stream
│   │   └── components/
│   │       ├── GoalInput.tsx       # Goal + run button
│   │       ├── ProgressBar.tsx     # Subtask progress + connection status
│   │       ├── LogPanel.tsx        # Live event log
│   │       ├── WorkflowGraph.tsx   # Agent pipeline / collaboration view
│   │       ├── ArtifactPanel.tsx   # Workspace browser + preview (incl. equity_viz)
│   │       ├── EquityVizPreview.tsx # Interactive equity + trade markers (SVG)
│   │       ├── ReportPanel.tsx     # LLM final report + metrics
│   │       └── PostRunChat.tsx     # Post-run Q&A (grounded on workspace)
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
│   │   ├── workspace.py        # Workspace: parquet/JSON/binary (e.g. PNG) artifacts
│   │   ├── equity_viz.py       # Post-run: equity_viz.json + equity_chart from backtest_results
│   │   ├── executor.py         # run_subtask: route → tool → log (error-aware)
│   │   ├── tool_routing.py     # LLM SubtaskToolChoice + keyword fallback
│   │   ├── subtask_heuristic.py# Keyword routing fallback
│   │   ├── clarifier.py        # Pre-execution goal clarification dialog
│   │   ├── data_loader.py      # Iterative Yahoo spec propose/load/judge loop
│   │   ├── analysis_skill.py   # LLM-generated EDA scripts + retry
│   │   ├── feature_skill.py    # LLM-generated feature/alpha scripts + retry (unified)
│   │   ├── backtest_skill.py   # LLM-generated backtest scripts + retry
│   │   ├── data_analyst.py     # Sub-agent: analyze → judge → feature plan
│   │   ├── debug_agent.py      # Failure diagnosis + structured recovery hints
│   │   ├── step_thinking.py    # Post-step reflection for next-tool guidance
│   │   ├── report_gen.py       # LLM final report → JSON + Markdown
│   │   ├── post_run_chat.py    # Build context pack + chat (max_completion_tokens)
│   │   └── plan_revision.py    # revise_plan: LLM replan after failure
│   ├── llm/
│   │   └── task_decompose.py   # NL → TaskBreakdown (4-8 tool-aligned subtasks)
│   ├── tools/
│   │   ├── __init__.py         # TOOL_REGISTRY + run_tool
│   │   ├── search.py           # web_search (Brave API)
│   │   ├── data.py             # load_data (yfinance)
│   │   ├── analysis.py         # run_data_analysis
│   │   ├── data_analyst_tool.py# run_data_analyst
│   │   ├── features.py         # build_features (+ build_alphas alias; auto-selects skill mode)
│   │   ├── regressor.py        # train_model (sklearn, workspace-aligned target)
│   │   ├── backtest.py         # run_backtest (pre-checked data/model match)
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
├── Dockerfile
├── docker-compose.yml
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

### Docker

Build the same single-port image (frontend `npm run build` + Python `uv sync`) and run with persisted `data/`:

```bash
cp .env.example .env   # at least OPENAI_API_KEY
docker compose up --build
```

Or without Compose:

```bash
docker build -t quantagent .
mkdir -p data
docker run --rm -p 8000:8000 --env-file .env -v "$(pwd)/data:/app/data" quantagent
```

Open `http://localhost:8000`. Mount `/app/data` so workspaces and `agent.db` survive restarts (Compose uses a named volume for the same path).

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
| 2 | `run_data_loader` | Iterative data-ingestion sub-agent: propose Yahoo spec, fetch, judge, retry | goal | `raw_data` |
| 2b | `load_data` | One-shot yfinance download or demo stub | explicit kwargs | `raw_data` |
| 3 | `run_data_analyst` | Iterative EDA sub-agent → feature plan | `raw_data` | `feature_plan` |
| 3b | `run_data_analysis` | Single-shot EDA alternative | `raw_data` or path | analysis summary |
| 4 | `build_features` | Feature / alpha engineering (auto-selects skill; `build_alphas` is alias) | `raw_data` + `feature_plan`/`alpha_plan` + optional `search_context` | `engineered_data` |
| 5 | `train_model` | sklearn regression / tuning | `engineered_data` (or `raw_data`) | `model_output` |
| 6 | `run_backtest` | Skill-driven backtest in `model_based` or `rule_based` mode; if `rebalance_freq` is omitted, **infers** `weekly`/`monthly` from `feature_plan` text when it matches (else `daily`) | `engineered_data`/`raw_data` + optional `model_output` | `backtest_results` |
| 7 | `evaluate_strategy` | LLM strategy verdict for ML or rule-based runs | `backtest_results` + optional `model_output` | `evaluation` |
| 8 | `run_debug_agent` | Diagnose failures and emit structured recovery hints | workspace artifacts + error context | `debug_notes` |

`run_data_loader` is the default pipeline entry for market data; `load_data` is the low-level direct fetch.  
`run_data_analysis` is a single-shot EDA alternative to `run_data_analyst`.

**Registry** — `scripts/tools/__init__.py` → `TOOL_REGISTRY` (12 entries; `build_alphas` aliases `build_features`).  
**Routing** — `tool_routing.py` reads `docs/tools.md` for LLM routing; `subtask_heuristic.py` as fallback.  
**Injection** — `workspace` and `event_callback` auto-injected when present in a tool's signature.

### Validations

- `run_data_loader` — normalizes single-ticker Yahoo downloads into panel-style OHLCV names and checks usable non-null price coverage before accepting `raw_data`
- `build_features` (incl. alpha mode) — rejects empty plans, sanitizes target column names, post-checks output contains target and planned columns, rejects non-finite values
- `train_model` — aligns with `feature_plan.target_column` from workspace; auto-derives target from price if missing; time-ordered split for datetime data
- `run_backtest` — pre-checks data/model column alignment in `model_based` mode and falls back to `rule_based` when no `model_output` exists; **backtest skill** discourages using `target_pos*` / plan `target_column` as raw weights when they act as labels (prefer signal/score columns + lag). Optional `equity_dates` / `trade_events` in JSON feed the dashboard chart
- `evaluate_strategy` — can review backtest-only rule-based runs; no longer treats missing `model_output` as automatically incomplete
- `executor` / workflow — detect tool-returned error dicts, emit debug + recovery events, **subtask retries** (`SUBTASK_FAILURE_RETRIES`), optional **replan** (`REPLAN_MAX`), and **halt** downstream on hard failure when `PIPELINE_HALT_ON_FAILURE=1`

---

## LLM model tiers

| Role | Env var | Typical model | Used by |
|------|---------|---------------|---------|
| **Code generation** | `OPENAI_TASK_MODEL` | gpt-4o-mini / gpt-5.4-mini | analysis_skill, feature_skill, alpha_skill, backtest_skill, `post_run_chat` (dashboard) |
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
  3. Long-only or long-short? Transaction costs? (Example default in clarify flow may vary; `run_backtest` defaults to `transaction_cost_bps=0` unless you ask for costs.)
  4. What metrics matter most? (Default: Sharpe, max drawdown)

Your answers: Use defaults, but make it long-only with SPY

Goal understood. Proceeding...
```

API: `POST /api/clarify { goal, conversation }` returns `{ understood, refined_goal, questions, assumptions }`.

---

## Post-run chat (dashboard)

After **`run_done`**, the **Final report** panel shows **Ask about this run**: a multi-turn chat whose system prompt includes a **context pack** built from `data/workspaces/{run_id}/` (e.g. `final_report`, `evaluation`, `feature_plan`, `backtest_results` without long equity curves, `model_output`, `search_context`, `debug_notes`, excerpt of `report.md`, and column names / shapes for `engineered_data` / `raw_data`). Full OHLCV series are not pasted into the model.

**API**

- `POST /api/run/{run_id}/chat`
- Body: `{ "messages": [ { "role": "user"|"assistant", "content": "..." }, ... ], "goal": "<optional original run goal>", "model": "<optional override>" }`
- Response: `{ "reply": "...", "run_id": "..." }`

Uses **`OPENAI_TASK_MODEL`** if set, otherwise **`OPENAI_SMALL_MODEL`**. Context is capped (roughly ~120k chars server-side).

---

## Output

Each run produces:

- **`final_report.json`** — structured report (title, sections, findings, recommendations, limitations)
- **`report.md`** — human-readable Markdown version of the same report
- **`evaluation.json`** — LLM strategy verdict (rating, strengths, weaknesses, next steps)
- **`backtest_results.json`** — Sharpe, drawdown, equity curve, turnover, etc.
- **`debug_notes.json`** — structured failure analysis and suggested recovery actions when debugging runs
- **`GET /api/workspace/{run_id}`** — manifest (artifact list, sizes, **`agent_scripts`**: id, path, kind, mtime)
- **`GET /api/workspace/{run_id}/{artifact}`** — JSON or dataframe preview, or `{ kind: "image", url }` for PNG artifacts
- **`GET /api/workspace/{run_id}/files/{artifact_name}`** — raw image (or other binary) for manifest entries with `kind: image`
- **`equity_viz.json`** — normalized dates, equity series, optional `trade_events` (Workspace tab renders an interactive chart)
- **`equity_chart.png`** — static matplotlib overview (same run)
- **`GET /api/workspace/{run_id}/agent-scripts/{script_id}`** — text preview of generated `.py` under `data/*_runs/{run_id}/`
- **Post-run chat** — same run id; see [Post-run chat (dashboard)](#post-run-chat-dashboard) (not persisted as a separate artifact by default)

---

## Events

`EventBus` backs real-time updates (thread-safe, replay-capable):

| Event | When | Notable payload |
|-------|------|-----------------|
| `run_start` | Run begins | `run_id`, `goal` |
| `decompose_done` | Plan ready | `total_subtasks`, `subtasks` |
| `workflow_topo_order` | Topological execution order resolved | `order`, optional `replan_round` |
| `subtask_start` | Subtask starts | `subtask_title`, `position`, `total` |
| `subtask_done` | Subtask ends | `status`, `summary`, `output` |
| `subtask_retry` | Same subtask retried after failure | `subtask_id`, `attempt`, `error_excerpt` |
| `workspace_update` | Artifact changed | `artifact_name` |
| `debug_agent_done` | After automatic or tool debug analysis | `summary`, `category`, `subtask_id`, `debug_error`, `debug_message` |
| `plan_replan` | `revise_plan` produced a new breakdown | `replan_round`, `subtasks` |
| `recovery_step` | Recovery tool runs after a failure | `tool_name`, `reason`, `subtask_id` |
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
OPENAI_TASK_MODEL=gpt-4o-mini      # Code generation + post-run chat (larger, more capable)
OPENAI_SMALL_MODEL=gpt-4o-nano     # Routing, judging, planning (fast, cheap); fallback for post-run chat if TASK unset

# Optional
OPENAI_BASE_URL=https://api.openai.com/v1
BRAVE_API_KEY=...                   # Web search tool
ANTHROPIC_API_KEY=...
AGENT_DB_PATH=./data/agent.db

# After each failed subtask, run the debug LLM and write debug_notes.json (optional)
# DEBUG_AGENT_ON_FAILURE=1

# After each subtask, run step reflection (which tools matter next, e.g. web_search before load_data). Default on.
# STEP_THINKING=0

# Pipeline: halt downstream after hard failure (1) or continue (0). Default 1.
# PIPELINE_HALT_ON_FAILURE=1

# Retries for the same subtask with error text appended to the description (after first failure).
# SUBTASK_FAILURE_RETRIES=2

# Max LLM replan rounds after retries / debug (full TaskBreakdown, preserve completed step ids).
# REPLAN_MAX=1
```

---

## Roadmap

| Item | Status |
|------|--------|
| Mid-run `revise_plan` | Basic LLM replan on failure (`REPLAN_MAX`) |
| Metric-driven auto-iteration (e.g. Sharpe threshold → retry) | Planned |
| Multi-asset panel support | Planned |
| Native classification training in `train_model` | Planned |
| Tests & CI | To add |

---

## Security & data

- Do **not** commit `.env`, `data/agent.db`, or `data/workspaces/`
- LLM-generated scripts run locally with a naive denylist — use in trusted environments only
- Add deps: `uv add <pkg>` (Python), `cd frontend && npm install <pkg>` (frontend)

---

_Python package name in `pyproject.toml` is `tools-research`; the public repo is **QuantAgent**._
