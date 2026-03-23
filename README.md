# tools-research

用 **uv** 管理的 Python 工作区：在搭一个「自然语言任务 → 拆解 → 选工具执行 → 落库」的 **研究型 agent 原型**。**数据**：`load_data` 可在提供 `tickers` 时用 **yfinance** 真拉行情。**训练**：`train_model` 使用 **scikit-learn**（可选模型、自选特征列、可选 `RandomizedSearchCV` 调参）；未提供 `data_path` 时用合成数据跑通管线。

---

## 环境

- Python **3.12+**
- [uv](https://docs.astral.sh/uv/)

```bash
uv sync
cp .env.example .env   # 填入 OPENAI_API_KEY、OPENAI_SMALL_MODEL 等
```

主要依赖：`openai`、`pydantic`、`python-dotenv`、`yfinance`、`numpy` / `pandas` / `matplotlib`（数值与画图预留）。

---

## 当前做到哪一步

| 能力 | 状态 |
|------|------|
| **任务拆解** | NL → `TaskBreakdown`（子任务 + 依赖），`scripts/llm/task_decompose.py`，small model + 结构化输出 |
| **运行时状态** | `AgentState` / `ExecutionRecord`，含 `plan_version`、`replan_triggers` 占位 |
| **工具注册** | `scripts/tools/` 下分文件实现，`run_tool` + `scripts/docs/tools.md`（给路由 / ReAct 用） |
| **数据（yfinance）** | `docs/yfinance_guide.md` 给 LLM 作说明书；模型只填结构化 `YFinanceFetchSpec`，由固定代码 `yf.download` 执行（避免每次手写不同脚本）。辅助：`llm/yfinance_spec.py` 的 `infer_yfinance_spec` |
| **数据分析（skill + 代码）** | `skills/data_analysis.md` + `run_data_analysis`：small model **生成可执行脚本**，写入 `data/analysis_runs/<id>/` 并 **subprocess 运行**，产出 `summary.json`（建模前 EDA） |
| **子任务 → 工具** | small model 读截断版 `tools.md`，输出 `tool_name` + `kwargs_json`，校验失败重试后 **关键词回退**（`agent/tool_routing.py`） |
| **执行** | `agent/executor.py`：`run_subtask` 写执行日志 |
| **端到端 demo** | `scripts/workflow_demo.py`：拆解 → 拓扑序执行子任务 → 可选写 SQLite |
| **日志库** | SQLite：`storage/agent_log_db.py`，默认 `data/agent.db`（`AGENT_DB_PATH` 可改） |
| **中途改计划** | **仅预留**：`agent/plan_revision.py` 里 `revise_plan(...)` 仍为 `NotImplementedError` |

---

## `scripts/` 目录（简要）

```
skills/                 # Agent skills（如 data_analysis.md → LLM 写脚本 + 执行）
scripts/
  workflow_demo.py      # 一键跑通流水线
  agent/                # 模型、状态、执行、路由、analysis_skill、replan 占位
  llm/                  # task_decompose, yfinance_spec（说明书 → 结构化参数）
  storage/              # SQLite
  tools/                # 工具实现 + 注册表（含 run_data_analysis）
  docs/tools.md         # 工具说明（路由 prompt 用）
  docs/yfinance_guide.md
```

运行示例：

```bash
# 端到端（会调多次 API；默认写库，加 --no-db 可关）
uv run python scripts/workflow_demo.py "你的研究目标描述"

# 只拆解任务
uv run python scripts/llm/task_decompose.py "你的研究目标描述"

# 根据自然语言 + yfinance 说明书，生成拉数参数（JSON）
uv run python scripts/llm/yfinance_spec.py "拉标普500 ETF 近两年日线"
```

**注意：** 执行 `scripts/` 下入口时，需保证 **`scripts` 在 `sys.path` 里**。从仓库根用上面命令时，Python 会把 `scripts/` 设为脚本所在目录的父级相关路径；`llm/task_decompose.py` 内对子目录直接运行做了 `sys.path` 修补。

---

## 还缺什么 / 建议下一步

1. **真实量化工具**：把 `tools/*.py` 换成真实数据加载、特征、训练、回测；接口尽量保持 `TOOL_REGISTRY` 名字稳定。
2. **`revise_plan` 实现**：子任务失败、Sharpe/回撤不达标、数据缺失、要加 robustness 时，用 LLM 生成新 `TaskBreakdown`，并在 `workflow_demo`（或未来主循环）里接上分支 + `plan_version` 递增。
3. **完整 ReAct 循环**：现在是「按计划拓扑执行 + 每步路由」；若要做 Thought → Action → Observation 多轮，可把 LLM 步与 `AgentState` 更新再包一层。
4. **指标驱动的迭代**：例如 Sharpe &lt; 阈值自动换特征族 / 重跑——需在 `artifacts` 或工具输出里约定指标结构，再写决策逻辑（或第二个 small model）。
5. **报告生成**：从 `AgentState` + `execution_log` 生成最终研究结论（模板 / LLM 摘要）。
6. **工程化**：`pyproject` 里把 `scripts` 收成可安装包或统一 `python -m` 入口、单测、CI；`.env` 格式问题若出现需自行检查（dotenv 对非法行会告警）。

---

## 依赖与加包

```bash
uv add <package>
```

---

## 数据与密钥

- 不要把 `.env` 或 `data/*.db` 提交进版本库（已在 `.gitignore` 中忽略常见项）。
- 数据库表：`runs`（用户输入、计划、最终状态）、`log_entries`（分类型事件与 JSON payload）。
