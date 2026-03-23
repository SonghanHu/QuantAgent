# Tools catalog (ReAct)

Use this file as **context for the LLM**: after *Thought*, choose an *Action* that names exactly one tool from the registry. Arguments are passed as JSON-like kwargs to `run_tool(name, **kwargs)`.

The small-model router (`agent.tool_routing.resolve_subtask_tool`) reads this catalog (truncated), returns structured `tool_name` plus a **JSON string** of kwargs (OpenAI schema-safe); invalid names are retried, then keyword fallback.

**Workspace:** Every run has a shared `Workspace` directory (`data/workspaces/<run_id>/`). Tools that accept a `workspace` parameter automatically receive it. Data flows between tools through workspace artifacts:

- `load_data` → saves `raw_data.parquet`
- `run_data_analysis` / `run_data_analyst` / `train_model` → auto-resolve `data_path` from `raw_data` when not explicitly set
- `run_data_analyst` → saves `feature_plan.json`
- `build_features` → reads `raw_data` + `feature_plan`, saves `engineered_data.parquet`
- `train_model` → can also read from `engineered_data` (when `data_path` not set)

You do **not** need to pass `data_path` explicitly when the upstream `load_data` has already run — the workspace handles artifact flow.

**Typical pipeline:**

1. `load_data` → 2. **`run_data_analyst`** (iterative EDA sub-agent → feature plan) → 3. `build_features` → 4. `train_model` → 5. `run_backtest` → 6. `evaluate_strategy`

Or for single-shot analysis only: `load_data` → `run_data_analysis` → …

Skip steps only if the subtask clearly does not need them (e.g. pure reporting may jump to `evaluate_strategy` in stub mode).

---

## `load_data`

- **What it does:** If **`tickers`** is set → downloads OHLCV via **yfinance** (one fixed code path). If omitted → small **demo stub** for pipeline tests.
- **When to use:** Subtask mentions data ingestion, symbols, Yahoo, prices, returns, universe, “拉数据”, etc.
- **Arguments (yfinance path):**
  - `tickers`: string (comma-separated) or list, e.g. `"SPY"` or `"SPY,TLT"` or `GC=F`
  - `period`: e.g. `1y`, `2y`, `max` (used when `start`/`end` not set)
  - `start` / `end`: optional `YYYY-MM-DD`
  - `interval`: default `1d` (`1wk`, `1h`, … per Yahoo limits)
  - `auto_adjust`, `prepost`, `actions`: booleans
  - `rationale`: optional string for logs
- **Arguments (stub path):** omit `tickers` or use `dataset: "demo"`.
- **Design note:** Let a **planner LLM** read `docs/yfinance_guide.md` and emit these kwargs (or use `llm.yfinance_spec.infer_yfinance_spec` → `load_data(**spec.model_dump(exclude_none=True))`). The model should **not** write arbitrary code—only fill parameters.
- **Returns:** `source`, `rows`, `columns`, `start_ts`, `end_ts`, `preview_rows`, etc.; or stub fields. When workspace is present, also `workspace_artifact` and `workspace_path`.
- **ReAct example:** *Thought: Need 2y daily SPY for momentum.* → *Action: load_data* with `{ "tickers": "SPY", "period": "2y", "interval": "1d" }`.

---

## `run_data_analysis`

- **What it does:** Reads a **Skill** markdown from repo `skills/<skill_name>.md` (default `data_analysis`). A **small model** writes a **Python script**; the tool injects `DATA_PATH` / `OUTPUT_JSON` / `RUN_DIR`, saves under `data/analysis_runs/<id>/analysis.py`, and **runs** it with the current interpreter. Captures stdout/stderr and parses `summary.json` if produced.
- **When to use:** Before serious modeling — EDA, data quality, missingness, distributions, correlations, profiling.
- **Arguments:**
  - `instruction` (required): what to analyze / hypotheses / columns of interest.
  - `data_path`: optional `.csv` / `.parquet` path; omit for synthetic-only script per skill.
  - `skill_name`: default `"data_analysis"` → `skills/data_analysis.md`.
  - `timeout_sec`: default `120`.
- **Safety:** Trusted environment only; naive denylist blocks `subprocess`, `requests`, etc. Not a full sandbox.
- **Returns:** `returncode`, `stdout`, `stderr`, `summary`, `script_path`, `run_id`, `skill`.
- **ReAct example:** *Thought: Profile the panel before training.* → `{ "instruction": "Summarize missingness and numeric describe; flag outliers in volume.", "data_path": "data/my_panel.parquet" }`.

---

## `run_data_analyst`

- **What it does:** **Iterative sub-agent.** Loops: (a) run a skill-driven analysis script, (b) LLM judge reviews and decides "enough?" — if not, sends a refined instruction for the next round. When done, emits a **`FeaturePlan`** (concrete feature specs: name, pandas logic, rationale, target column).
- **When to use:** After loading data and before training, when you need the AI to **explore, understand, and propose features autonomously** — replaces manual EDA + feature brainstorming.
- **Arguments:**
  - `goal` (required): overall research objective (guides the judge and feature planner).
  - `data_path`: optional `.csv` / `.parquet`.
  - `initial_instruction`: first-round analysis focus; sensible default if omitted.
  - `max_rounds`: default `4` — cap on analyze → judge cycles.
  - `timeout_sec`: per-script subprocess timeout (default `120`).
- **Returns:** `stopped_reason` (`ready` | `max_rounds`), `num_rounds`, `round_summaries`, `feature_plan` (list of features + target).
- **ReAct example:** *Thought: Need to understand data and propose features.* → `{ "goal": "Predict weekly return on SPY", "data_path": "data/spy.parquet", "max_rounds": 3 }`.

---

## `build_features`

- **What it does:** Reads `feature_plan` and `raw_data` from workspace, uses `skills/feature_engineering.md` to generate and execute a Python script that computes the planned features. Saves the enriched DataFrame as `engineered_data` in workspace.
- **When to use:** After `run_data_analyst` has produced a feature plan. Subtask mentions features, factors, signals, engineering, 特征工程.
- **Arguments:**
  - `workspace`: auto-injected. Must contain `raw_data` and `feature_plan` artifacts.
  - `timeout_sec`: per-script subprocess timeout (default `120`).
- **Returns:** `planned_features`, `target_column`, `engineered_shape`, `engineered_columns`, script execution details. Also saves `engineered_data` to workspace.
- **ReAct example:** *Thought: Feature plan is ready, now build features.* → *Action: build_features* with `{}`.

---

## `train_model`

- **What it does:** **scikit-learn** regression: Pipeline(imputer → scaler → estimator). You choose model, feature columns, and optional tuning.
- **When to use:** Training / fitting / 回归 / 调参 / cross-validation.
- **Arguments:**
  - `model_name`: `linear_regression`, `ridge`, `lasso`, `elasticnet`, `random_forest`, `gradient_boosting`, `svr` (aliases `lr`, `rf`, `gbm`, `gbr`, `enet`, …)
  - `feature_columns`: list or comma-separated string; **omit** to use all numeric columns except `target_column`
  - `target_column`: default `"target"`
  - `tune_hyperparameters`: `true` / `false` — runs `RandomizedSearchCV` when a search space exists (`linear_regression` / OLS has none → `tune_ignored`)
  - `data_path`: optional path to `.csv` or `.parquet`; omit for **synthetic** data (`f0..f{n-1}` + target)
  - `n_samples`, `n_features`: synthetic data shape when no `data_path`
  - `test_size`, `random_state`, `cv_folds`, `tuning_iter`
- **Returns:** `train_r2`, `test_r2`, `test_rmse`, `best_params`, `best_cv_r2`, `feature_columns`, etc.
- **ReAct example:** *Thought: Tune a ridge on f0,f1,f2.* → `{ "model_name": "ridge", "feature_columns": "f0,f1,f2", "tune_hyperparameters": true }`.

---

## `run_backtest`

- **What it does:** Simulates PnL and risk stats (**stub** — will become a sub-agent that generates a backtest script from workspace artifacts).
- **When to use:** Subtask mentions backtest, Sharpe, drawdown, turnover, 回测, 净值.
- **Arguments:** `workspace`: auto-injected (not yet used by stub).
- **Returns:** `{ "sharpe", "max_drawdown", "turnover", "stub": true }`.
- **ReAct example:** *Thought: Need performance metrics.* → *Action: run_backtest* with `{}`.

---

## `evaluate_strategy`

- **What it does:** High-level verdict and suggested next step (stub).
- **When to use:** Subtask mentions summary, conclusion, next steps, robustness, 结论, 总结.
- **Arguments:** none (stub).
- **Returns:** `{ "verdict", "next_step" }`.
- **ReAct example:** *Thought: Enough numbers; interpret.* → *Action: evaluate_strategy* with `{}`.

---

## Python entrypoint

With `scripts/` on `sys.path`:

```python
from tools import run_tool, list_tools, TOOL_REGISTRY

run_tool("load_data", dataset="demo")
```

Implementations live under `scripts/tools/*.py`; each function has a docstring describing usage.
