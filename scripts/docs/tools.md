# Tools catalog (ReAct)

Use this file as **context for the LLM**: after *Thought*, choose an *Action* that names exactly one tool from the registry. Arguments are passed as JSON-like kwargs to `run_tool(name, **kwargs)`.

The small-model router (`agent.tool_routing.resolve_subtask_tool`) reads this catalog (truncated), returns structured `tool_name` plus a **JSON string** of kwargs (OpenAI schema-safe); invalid names are retried, then keyword fallback.

**Workspace:** Every run has a shared `Workspace` directory (`data/workspaces/<run_id>/`). Tools that accept a `workspace` parameter automatically receive it. Data flows between tools through workspace artifacts:

- `web_search` → saves `search_context.json`
- `load_data` → saves `raw_data.parquet`
- `run_data_analysis` / `run_data_analyst` / `train_model` → auto-resolve `data_path` from `raw_data` when not explicitly set
- `run_data_analyst` → saves `feature_plan.json`
- `build_features` → reads `raw_data` + `feature_plan`, saves `engineered_data.parquet`
- `build_alphas` → reads `raw_data` + `feature_plan`/`alpha_plan` + `search_context`, saves `engineered_data.parquet`
- `train_model` → reads from `engineered_data` (or `raw_data`), saves `model_output.json`
- `run_backtest` → reads `engineered_data` (or `raw_data`) + `model_output`, saves `backtest_results.json`
- `evaluate_strategy` → reads `backtest_results` + `model_output` + `feature_plan`, saves `evaluation.json`

You do **not** need to pass `data_path` explicitly when the upstream `load_data` has already run — the workspace handles artifact flow.

**Typical pipelines:**

1. `web_search` (optional) → `load_data` → `run_data_analyst` → `build_features` → `train_model` → `run_backtest` → `evaluate_strategy`
2. For alpha research: `web_search` → `load_data` → `run_data_analyst` → **`build_alphas`** → `train_model` → `run_backtest` → `evaluate_strategy`
3. For single-shot analysis: `load_data` → `run_data_analysis` → …

Skip steps only if the subtask clearly does not need them. Use `build_alphas` instead of `build_features` when the goal involves alpha research, formulaic alphas, or WorldQuant-style factors.

---

## `web_search`

- **What it does:** Searches the web using **Brave Search API** and returns structured results. Saves results as `search_context` in workspace for downstream tools (e.g. `build_alphas` injects research context into the alpha script prompt).
- **When to use:** When the subtask involves researching alpha ideas, factor definitions, market regime context, recent academic papers, or any external information. Use early in the pipeline.
- **Arguments:**
  - `query` (required): search query string (e.g. "WorldQuant 101 formulaic alphas momentum factors")
  - `num_results`: number of results to return (default `5`, max `20`)
  - `workspace`: auto-injected
- **Returns:** `query`, `num_results`, `results` (list of {title, url, description}), `summary` (formatted text). Saves `search_context` to workspace.
- **ReAct example:** *Thought: Need alpha factor ideas.* → *Action: web_search* with `{ "query": "WorldQuant formulaic alpha momentum volume factors" }`.

---

## `load_data`

- **What it does:** If **`tickers`** is set → downloads OHLCV via **yfinance** (one fixed code path). If omitted → small **demo stub** for pipeline tests.
- **When to use:** Subtask mentions data ingestion, symbols, Yahoo, prices, returns, universe, fetching data, etc.
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
- **Validations (fail-fast):**
  - Rejects empty feature plans (`features: []`).
  - Sanitizes `target_column`: must be a short ASCII identifier (e.g. `target`, `fwd_ret_1d`); long sentences / non-ASCII are replaced with `"target"`.
  - After script execution, verifies that the output parquet actually contains the target column; refuses to save `engineered_data` otherwise.
- **When to use:** After `run_data_analyst` has produced a feature plan. Subtask mentions features, factors, signals, feature engineering.
- **Arguments:**
  - `workspace`: auto-injected. Must contain `raw_data` and `feature_plan` artifacts.
  - `timeout_sec`: per-script subprocess timeout (default `120`).
- **Returns:** `planned_features`, `target_column`, `engineered_shape`, `engineered_columns`, script execution details. Also saves `engineered_data` to workspace.
- **ReAct example:** *Thought: Feature plan is ready, now build features.* → *Action: build_features* with `{}`.

---

## `build_alphas`

- **What it does:** **WorldQuant-style alpha factor construction.** Reads `feature_plan` (or `alpha_plan`) and `raw_data` from workspace, generates a Python script via `skills/alpha_engineering.md` that implements quantitative alpha expressions (momentum, mean-reversion, volume, volatility, technical, composite). Computes information coefficient (IC) for each alpha. Also injects `search_context` from web search if available. Saves enriched DataFrame as `engineered_data`.
- **When to use:** Instead of `build_features` when the goal involves alpha research, factor investing, formulaic alphas, or WorldQuant-style quant research. Subtask mentions alpha, factors, signals, IC, cross-sectional.
- **Arguments:**
  - `workspace`: auto-injected. Must contain `raw_data` and `feature_plan`/`alpha_plan`.
  - `timeout_sec`: per-script subprocess timeout (default `150`).
- **Returns:** `planned_alphas`, `target_column`, `engineered_shape`, `engineered_columns`, IC preview, script execution details. Saves `engineered_data` to workspace.
- **ReAct example:** *Thought: Build WorldQuant-style alphas from the plan.* → *Action: build_alphas* with `{}`.

---

## `train_model`

- **What it does:** **scikit-learn** regression: Pipeline(imputer → scaler → estimator). You choose model, feature columns, and optional tuning.
- **When to use:** Training / fitting / regression / hyperparameter tuning / cross-validation.
- **Arguments:**
  - `model_name`: `linear_regression`, `ridge`, `lasso`, `elasticnet`, `random_forest`, `gradient_boosting`, `svr` (aliases `lr`, `rf`, `gbm`, `gbr`, `enet`, …)
  - `feature_columns`: list or comma-separated string; **omit** to use all numeric columns except `target_column`
  - `target_column`: default `"target"`. When loading `engineered_data` from workspace, the tool reads `feature_plan.target_column` and uses it (if it is a valid identifier); this ensures training uses the same target that feature engineering produced. If the column is missing but the frame has **Adj Close** / **Close** (typical yfinance OHLCV), the tool adds `target` = **next-bar simple return** of that price series.
  - `tune_hyperparameters`: `true` / `false` — runs `RandomizedSearchCV` when a search space exists (`linear_regression` / OLS has none → `tune_ignored`)
  - `data_path`: optional path to `.csv` or `.parquet`; omit for **synthetic** data (`f0..f{n-1}` + target)
  - `n_samples`, `n_features`: synthetic data shape when no `data_path`
  - `test_size`, `random_state`, `cv_folds`, `tuning_iter`
- **Split:** For data with a **monotonic datetime index**, train/test split is **time-ordered** (last `test_size` fraction held out); otherwise sklearn `train_test_split` (shuffled).
- **Returns:** `train_r2`, `test_r2`, `test_rmse`, `best_params`, `best_cv_r2`, `feature_columns`, `target_derived_from_price` (if auto-target was used), `time_ordered_split`, etc.
- **ReAct example:** *Thought: Tune a ridge on f0,f1,f2.* → `{ "model_name": "ridge", "feature_columns": "f0,f1,f2", "tune_hyperparameters": true }`.

---

## `run_backtest`

- **What it does:** **Skill-driven backtest sub-agent.** Reads `engineered_data` (or `raw_data`) and `model_output` from workspace. **Pre-checks** that the data contains the target column and feature columns listed in `model_output`; returns `data_model_mismatch` error immediately if not (avoids waiting for a long script execution to fail). An LLM generates a complete backtest script from `skills/backtest.md`, respecting structured **hyperparameters** (strategy type, rebalance frequency, position sizing, transaction costs, etc.). The script re-trains the model on an in-sample window, generates out-of-sample predictions, converts to signals, and computes PnL / risk metrics. Saves `backtest_results` to workspace.
- **When to use:** After `train_model`. Subtask mentions backtest, Sharpe, drawdown, turnover, PnL, equity curve, risk metrics.
- **Arguments (hyperparameters):**
  - `strategy_type`: `"long_only"` (default) | `"long_short"` — whether the strategy can short
  - `rebalance_freq`: `"daily"` (default) | `"weekly"` | `"monthly"` — rebalance cadence
  - `position_sizing`: `"equal_weight"` | `"signal_proportional"` (default) | `"volatility_scaled"`
  - `transaction_cost_bps`: float, default `5.0` — round-trip cost in basis points
  - `max_position_pct`: float 0–1, default `1.0` — max portfolio fraction per position
  - `initial_capital`: float, default `1000000`
  - `train_ratio`: float 0.1–1.0, default `0.7` — in-sample fraction
  - `timeout_sec`: script execution timeout (default `180`)
  - `workspace`: auto-injected; must contain `model_output` and data
- **Returns:** `sharpe`, `max_drawdown`, `total_return`, `annual_return`, `win_rate`, `n_test_days`, plus script execution details. Saves `backtest_results` JSON to workspace.
- **ReAct example:** *Thought: Need long-short daily backtest with 10bps costs.* → *Action: run_backtest* with `{ "strategy_type": "long_short", "transaction_cost_bps": 10, "train_ratio": 0.7 }`.

---

## `evaluate_strategy`

- **What it does:** **LLM-driven evaluation.** Reads `backtest_results`, `model_output`, and optionally `feature_plan` from workspace. A senior quant reviewer LLM produces a structured `StrategyVerdict` with overall rating, strengths, weaknesses, risk assessment, and concrete next steps. Saves `evaluation` to workspace.
- **When to use:** After `run_backtest`. Subtask mentions evaluation, summary, conclusion, verdict, next steps, robustness.
- **Arguments:**
  - `workspace`: auto-injected; should contain `backtest_results` and/or `model_output`
  - `model`: optional LLM model override
- **Returns:** `verdict` (`strong` | `promising` | `weak` | `failed`), `summary`, `strengths`, `weaknesses`, `risk_assessment`, `next_steps`, `deploy_ready`. Saves `evaluation` JSON to workspace.
- **ReAct example:** *Thought: Backtest done, need to interpret results.* → *Action: evaluate_strategy* with `{}`.

---

## Python entrypoint

With `scripts/` on `sys.path`:

```python
from tools import run_tool, list_tools, TOOL_REGISTRY

run_tool("load_data", dataset="demo")
```

Implementations live under `scripts/tools/*.py`; each function has a docstring describing usage.
