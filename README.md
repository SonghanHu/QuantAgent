# tools-research

自然语言驱动的**研究型 Agent**——输入一句话目标，自动拆解子任务、路由工具、拉取数据、特征工程、建模回测，全程通过 **Real-time Dashboard** 实时可视化。

---

## 架构总览

```
┌───────────────────────────────────────────────────────────────────┐
│  Browser  (React 19 + Tailwind v4 + Vite 8)                      │
│                                                                   │
│  GoalInput ──▶ POST /api/run ──▶ run_id                          │
│  useAgentSocket ◀── WebSocket /ws/{run_id} ◀── EventBus          │
│  ArtifactPanel ──▶ GET /api/workspace/{run_id}/{artifact}        │
│  ProgressBar · LogPanel · ReportPanel                            │
└──────────────────────────┬────────────────────────────────────────┘
                           │  Vite proxy (dev) / 同端口 (prod)
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
│  save final state ──▶ SQLite + Workspace                         │
└──────────────────────────┬────────────────────────────────────────┐
                           │
┌──────────────────────────▼────────────────────────────────────────┐
│  Tool Layer  (scripts/tools/)                                     │
│                                                                   │
│  load_data ──▶ yfinance download ──▶ raw_data.parquet            │
│  run_data_analyst ──▶ sub-agent loop (skill → judge → plan)      │
│  build_features ──▶ feature_skill code-gen ──▶ engineered.parquet│
│  train_model ──▶ sklearn pipeline ──▶ model metrics              │
│  run_backtest / evaluate_strategy ──▶ (stub)                     │
└──────────────────────────┬────────────────────────────────────────┘
                           │
┌──────────────────────────▼────────────────────────────────────────┐
│  Persistence                                                      │
│                                                                   │
│  Workspace: data/workspaces/{run_id}/                            │
│    ├── manifest.json                                              │
│    ├── raw_data.parquet                                           │
│    ├── feature_plan.json                                          │
│    └── engineered_data.parquet                                    │
│  SQLite: data/agent.db  (runs + log_entries)                     │
│  Skills output: data/analysis_runs/ · data/feature_runs/         │
└───────────────────────────────────────────────────────────────────┘
```

---

## 技术栈

| 层       | 技术                          | 版本       |
|----------|-------------------------------|------------|
| Frontend | React, TypeScript, Tailwind   | 19 / 5.9 / 4.2 |
| Build    | Vite                          | 8.0        |
| Backend  | FastAPI, Uvicorn              | 0.135+ / 0.42+ |
| LLM      | OpenAI (structured output)    | SDK 2.29+  |
| Data     | pandas, numpy, pyarrow, yfinance | 3.0 / 2.4 / 23 / 1.2 |
| ML       | scikit-learn                  | 1.8+       |
| Storage  | SQLite, Parquet, JSON         | —          |
| 包管理    | uv (Python), npm (Frontend)   | —          |

---

## 目录结构

```
.
├── frontend/                   # React SPA
│   ├── src/
│   │   ├── App.tsx             # 主页面：提交目标、显示进度/日志/产物/报告
│   │   ├── hooks/
│   │   │   └── useAgentSocket.ts   # WebSocket 连接 + 事件流
│   │   ├── components/
│   │   │   ├── GoalInput.tsx       # 目标输入 + 启动按钮
│   │   │   ├── ProgressBar.tsx     # 子任务进度条 + 连接状态
│   │   │   ├── LogPanel.tsx        # 实时事件日志
│   │   │   ├── ArtifactPanel.tsx   # Workspace 产物浏览 + 预览
│   │   │   └── ReportPanel.tsx     # 最终报告
│   │   └── types.ts            # AgentEvent, WorkspaceManifest, ArtifactPreview
│   ├── vite.config.ts          # 开发代理：/api → :8000, /ws → ws://:8000
│   └── dist/                   # 生产构建（FastAPI 直接 serve）
│
├── server/                     # FastAPI 后端
│   ├── app.py                  # HTTP API + WebSocket + 静态文件
│   └── agent_runner.py         # RunManager：线程池运行 agent
│
├── scripts/                    # Agent 核心逻辑
│   ├── workflow_demo.py        # 端到端编排：拆解 → 拓扑序执行 → 落库
│   ├── dashboard_dev.py        # 一键启动前后端 dev server
│   ├── agent/
│   │   ├── models.py           # Subtask, TaskBreakdown (Pydantic)
│   │   ├── state.py            # AgentState, ExecutionRecord
│   │   ├── events.py           # EventBus：线程安全的 pub/sub + replay
│   │   ├── workspace.py        # Workspace：parquet/JSON 产物管理
│   │   ├── executor.py         # run_subtask：路由 → 调工具 → 记录
│   │   ├── tool_routing.py     # LLM 路由 SubtaskToolChoice + 关键词回退
│   │   ├── subtask_heuristic.py# 关键词匹配兜底
│   │   ├── analysis_skill.py   # LLM 生成 EDA 脚本 + subprocess 执行
│   │   ├── feature_skill.py    # LLM 生成特征工程脚本 + subprocess 执行
│   │   ├── data_analyst.py     # 子 agent 循环：分析 → 裁判 → 特征计划
│   │   └── plan_revision.py    # revise_plan (预留 NotImplementedError)
│   ├── llm/
│   │   ├── task_decompose.py   # NL → TaskBreakdown (OpenAI structured output)
│   │   └── yfinance_spec.py    # NL → YFinanceFetchSpec
│   ├── tools/
│   │   ├── __init__.py         # TOOL_REGISTRY + run_tool + list_tools
│   │   ├── data.py             # load_data (yfinance)
│   │   ├── data_spec.py        # YFinanceFetchSpec
│   │   ├── analysis.py         # run_data_analysis
│   │   ├── data_analyst_tool.py# run_data_analyst
│   │   ├── features.py         # build_features
│   │   ├── regressor.py        # train_model (sklearn)
│   │   ├── backtest.py         # run_backtest (stub)
│   │   └── evaluation.py       # evaluate_strategy (stub)
│   ├── storage/
│   │   └── agent_log_db.py     # SQLite: runs + log_entries
│   └── docs/
│       ├── tools.md            # 工具目录（LLM 路由用）
│       └── yfinance_guide.md   # yfinance 说明书
│
├── skills/                     # Markdown 技能描述（喂给 LLM 生成脚本）
│   ├── data_analysis.md
│   └── feature_engineering.md
│
├── data/                       # 运行时数据（不进版本库）
│   ├── agent.db                # SQLite 日志
│   ├── workspaces/{run_id}/    # 每次运行的产物
│   ├── analysis_runs/{id}/     # EDA 脚本 + 结果
│   └── feature_runs/{id}/      # 特征工程脚本 + 结果
│
├── pyproject.toml              # Python 依赖 (uv)
└── .env.example                # 环境变量模板
```

---

## 快速开始

### 1. 环境准备

```bash
# Python 依赖
uv sync

# 前端依赖
cd frontend && npm install && cd ..

# 环境变量
cp .env.example .env
# 编辑 .env，填入 OPENAI_API_KEY 等
```

### 2. 启动 Dashboard（开发模式）

**方式一：一键启动**

```bash
uv run python scripts/dashboard_dev.py
```

同时启动：
- 后端 `http://127.0.0.1:8000`（FastAPI + Uvicorn）
- 前端 `http://127.0.0.1:5173`（Vite dev server，自动代理 `/api` 和 `/ws` 到后端）

打开浏览器访问 `http://127.0.0.1:5173`。

**方式二：分别启动**

```bash
# 终端 1：后端
uv run uvicorn server.app:app --host 127.0.0.1 --port 8000 --reload

# 终端 2：前端
cd frontend && npm run dev -- --host 127.0.0.1 --port 5173
```

### 3. 生产模式（单端口）

```bash
# 构建前端
cd frontend && npm run build && cd ..

# 启动后端（自动 serve frontend/dist）
uv run uvicorn server.app:app --host 0.0.0.0 --port 8000
```

访问 `http://localhost:8000`，前后端同端口，无需代理。

### 4. 仅 CLI（无 UI）

```bash
# 端到端执行（调用 LLM、拉数据、训练等）
uv run python scripts/workflow_demo.py "下载 SPY 近一年日线，分析、特征工程、训练 Ridge 回归、回测评估"

# 只拆解任务
uv run python scripts/llm/task_decompose.py "你的研究目标"

# 生成 yfinance 参数
uv run python scripts/llm/yfinance_spec.py "拉标普500 ETF 近两年日线"
```

---

## 数据流

```
用户输入目标
    │
    ▼
POST /api/run { goal }
    │
    ▼
RunManager.start_run ──▶ 开启 daemon thread
    │
    ▼
workflow_demo.run_workflow
    ├── 创建 Workspace (data/workspaces/{run_id}/)
    ├── 可选创建 SQLite run 记录
    ├── emit("run_start")
    │
    ├── decompose_task (OpenAI structured output)
    │   └── TaskBreakdown { subtasks[], dependencies }
    │   └── emit("decompose_done")
    │
    ├── 拓扑排序 subtasks
    │   └── emit("workflow_topo_order")
    │
    ├── for each subtask:
    │   ├── emit("subtask_start")
    │   ├── resolve_subtask_tool (LLM / 关键词回退)
    │   │   └── emit("subtask_tool_resolved")
    │   ├── run_tool(tool_name, **kwargs)
    │   │   └── 工具可读写 Workspace (parquet/JSON)
    │   ├── emit("subtask_done")
    │   └── emit("workspace_update") if artifacts changed
    │
    └── emit("run_done") ──▶ WebSocket 关闭
                               │
                               ▼
                    前端刷新 workspace manifest
                    显示最终报告
```

---

## 事件系统

`EventBus`（`scripts/agent/events.py`）是前后端实时通信的核心：

- **线程安全**：`Lock` 保护 history 和 subscriber 列表
- **发布**：`emit(event_type, **payload)` → 追加 history + 推入所有 subscriber queue
- **订阅**：`subscribe(replay=True)` → 返回 `(id, queue, history)`，新连接可回放已有事件
- **WebSocket 桥接**：`server/app.py` 中 `asyncio.to_thread(queue.get)` 将阻塞队列转为异步推送

**事件类型**：

| 事件 | 触发时机 | 关键字段 |
|------|----------|----------|
| `run_start` | 运行开始 | `run_id`, `goal` |
| `decompose_done` | 任务拆解完成 | `total_subtasks`, `subtasks` |
| `workflow_topo_order` | 拓扑排序完成 | `order` |
| `subtask_start` | 子任务开始 | `subtask_title` |
| `subtask_tool_resolved` | 工具路由完成 | `tool_name`, `kwargs` |
| `subtask_done` | 子任务完成 | `status`, `summary` |
| `workspace_update` | 产物变化 | `artifact_name` |
| `run_done` | 运行结束 | `status`, `workspace_summary` |

---

## Workspace 产物系统

每次运行在 `data/workspaces/{run_id}/` 下创建独立目录：

- **`manifest.json`**：记录所有产物的元信息（名称、类型、描述、shape、时间戳）
- **产物类型**：`dataframe`（`.parquet`）、`json`（`.json`）、`file`（其他）
- **API 访问**：
  - `GET /api/workspace/{run_id}` → manifest + 产物列表
  - `GET /api/workspace/{run_id}/{name}` → JSON 内容或 DataFrame 前 20 行预览
- **工具集成**：`executor.py` 自动将 `Workspace` 注入工具函数签名中含 `workspace` 参数的工具

---

## 工具系统

| 工具名 | 功能 | 读写 Workspace |
|--------|------|----------------|
| `load_data` | yfinance 下载行情数据 | 写 `raw_data` |
| `run_data_analysis` | EDA 技能（LLM 生成脚本 + subprocess） | 读 `raw_data` |
| `run_data_analyst` | 子 agent 循环：分析 → 裁判 → 生成特征计划 | 写 `feature_plan` |
| `build_features` | 特征工程（LLM 生成脚本 + subprocess） | 读 `raw_data` + `feature_plan`，写 `engineered_data` |
| `train_model` | sklearn 训练（Ridge / RF / 可选 RandomizedSearchCV） | 读 workspace 数据 |
| `run_backtest` | 回测（stub） | — |
| `evaluate_strategy` | 策略评估（stub） | — |

**注册**：`scripts/tools/__init__.py` 的 `TOOL_REGISTRY` 字典。

**路由**：`tool_routing.py` 用 LLM 读 `docs/tools.md` 选择工具 + 参数，校验失败时回退到 `subtask_heuristic.py` 的关键词匹配。

**注入**：`executor.py` 通过 `inspect.signature` 自动注入 `workspace` 和 `event_callback` 参数。

---

## LLM 集成

- **客户端**：OpenAI Python SDK，支持自定义 `OPENAI_BASE_URL`
- **模型**：通过 `OPENAI_SMALL_MODEL` 配置（默认 `gpt-5.4-nano`）
- **模式**：全部使用 `chat.completions.parse` + Pydantic `response_format`（结构化输出）
- **用途**：
  - `decompose_task` → `TaskBreakdown`
  - `resolve_subtask_tool` → `SubtaskToolChoice`
  - `infer_yfinance_spec` → `YFinanceFetchSpec`
  - `analysis_skill` / `feature_skill` → 生成 Python 脚本（denylist 安全校验 + subprocess 执行）
  - `data_analyst` 子 agent → `JudgeDecision` + `FeaturePlan`

---

## 环境变量

```bash
# 必填
OPENAI_API_KEY=sk-...

# 可选
OPENAI_BASE_URL=https://api.openai.com/v1   # 自定义端点
OPENAI_SMALL_MODEL=gpt-5.4-nano             # 路由/拆解用的小模型
ANTHROPIC_API_KEY=...                        # Anthropic 备用
AGENT_DB_PATH=./data/agent.db                # SQLite 路径
```

---

## 还在做 / 下一步

| 方向 | 状态 |
|------|------|
| 中途改计划 `revise_plan` | 预留接口，尚未实现 |
| 回测 / 评估工具 | stub，需接入真实逻辑 |
| 完整 ReAct 循环 | 当前为计划式执行，多轮推理待扩展 |
| 指标驱动迭代 | Sharpe < 阈值自动换特征 / 重跑 |
| 报告生成 | 从 execution_log 生成研究报告 |
| 测试与 CI | 待补充 |

---

## 数据与密钥

- **不要**把 `.env`、`data/agent.db`、`data/workspaces/` 提交进版本库
- SQLite 表：`runs`（目标、计划、最终状态）、`log_entries`（分类型事件 + JSON payload）
- 加包：`uv add <package>`（Python）、`cd frontend && npm install <package>`（前端）
