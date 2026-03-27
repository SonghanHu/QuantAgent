# Tools catalog (ReAct)

Use this file as **context for the LLM**: after *Thought*, choose an *Action* that names exactly one tool from the registry. Arguments are passed as JSON-like kwargs to `run_tool(name, **kwargs)`.

The small-model router (`agent.tool_routing.resolve_subtask_tool`) reads this catalog (truncated), returns structured `tool_name` plus a **JSON string** of kwargs (OpenAI schema-safe); invalid names are retried, then keyword fallback.

**Registry:** `scripts/tools/__init__.py` defines `TOOL_REGISTRY` with **12** tools. Some tools also accept an optional `event_callback` (for streaming `data_loader_round` / `data_analyst_round` events to the dashboard).

**Workspace:** Every run has a shared `Workspace` directory (`data/workspaces/<run_id>/`). Tools that accept a `workspace` parameter automatically receive it. Data flows between tools through workspace artifacts:

- `web_search` → saves `search_context.json`
- `fetch_sp500_tickers` → optional save `sp500_tickers.json` (current constituents list)
- `run_data_loader` → iterative judge loop → saves `raw_data.parquet` when the judge accepts the panel (normalizes single-ticker Yahoo frames to panel-style `Close_<SYM>` / `Adj Close_<SYM>` before the judge runs)
- `load_data` → one-shot download → saves `raw_data.parquet` (low-level; pipeline prefers `run_data_loader`)
- `run_data_analysis` / `run_data_analyst` / `train_model` → auto-resolve `data_path` from `raw_data` when not explicitly set
- `run_data_analyst` → saves `feature_plan.json`
- `build_features` → reads `raw_data` + `feature_plan`, saves `engineered_data.parquet`
- `build_alphas` → reads `raw_data` + `feature_plan`/`alpha_plan` + `search_context`, saves `engineered_data.parquet`
- `train_model` → reads from `engineered_data` (or `raw_data`), saves `model_output.json`
- `run_backtest` → reads `engineered_data` (or `raw_data`); if `model_output` exists → **`model_based`** backtest, else → **`rule_based`** (signals/features only). Saves `backtest_results.json`
- `evaluate_strategy` → reads `backtest_results` and optionally `model_output` + `feature_plan`; saves `evaluation.json` (works for ML or rule-only runs)
- `run_debug_agent` → reads workspace + error context, saves `debug_notes.json`

You do **not** need to pass `data_path` explicitly when the upstream `run_data_loader` / `load_data` has already run — the workspace handles artifact flow.

**Typical pipelines:**

1. ML / predictive workflow: `web_search` (optional) → `run_data_loader` → `run_data_analyst` → `build_features` → `train_model` → `run_backtest` → `evaluate_strategy`
2. Rule-based workflow: `web_search` (optional) → `run_data_loader` → `run_data_analyst` → `build_features` → `run_backtest` → `evaluate_strategy`
3. For alpha research: `web_search` → `run_data_loader` → `run_data_analyst` → **`build_alphas`** → `train_model` or direct `run_backtest` → `evaluate_strategy`
4. For single-shot analysis: `run_data_loader` or `load_data` → `run_data_analysis` → …

Skip steps only if the subtask clearly does not need them. Use `build_alphas` instead of `build_features` when the goal involves alpha research, formulaic alphas, or WorldQuant-style factors.

**Tool names (registry):** `build_alphas`, `build_features`, `evaluate_strategy`, `fetch_sp500_tickers`, `load_data`, `run_backtest`, `run_data_analysis`, `run_data_analyst`, `run_data_loader`, `run_debug_agent`, `train_model`, `web_search`.

---

## `fetch_sp500_tickers`

- **What it does:** Downloads the public [S&P 500 constituents CSV](https://raw.githubusercontent.com/datasets/s-and-p-500-companies/main/data/constituents.csv), parses the `Symbol` column, normalizes dots to hyphens for Yahoo-style tickers (e.g. `BRK.B` → `BRK-B`), and returns a sorted deduplicated list.
- **When to use:** When a subtask needs the **current** S&P 500 universe for screening, batch downloads, or universe definition — not for point-in-accurate historical index membership (see notes).
- **Arguments:** `timeout` (seconds, default `60`), `workspace` (auto-injected).
- **Returns:** `tickers`, `n`, `source_url`, `notes` (survivorship / current-membership caveat). With workspace: saves `sp500_tickers` artifact.
- **ReAct example:** *Thought: Need the latest S&P 500 symbol list before batch price load.* → *Action: fetch_sp500_tickers* with `{}`.

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

## `run_data_loader`

- **What it does:** Sub-agent: each round the model emits a **`YFinanceFetchSpec`**, the tool runs **`load_data`** (fixed path), then a **judge** decides if `raw_data` fits the **research goal** (coverage, missing prices, horizon). Repeats until accepted or max rounds. Stale `raw_data` is dropped if the judge rejects the final attempt.
- **Implementation note:** `load_data` flattens Yahoo multi-index columns and, for single-ticker downloads, suffixes bare OHLCV names (`Close` → `Close_<TICKER>`) so downstream judges and features see stable price column names.
- **When to use:** Default for any subtask whose job is to **obtain** market/OHLCV data for the run. Prefer over bare `load_data` in the main pipeline.
- **Arguments:** `goal` (required; overall objective), `max_rounds` (default `4`), `workspace` (auto-injected), optional `event_callback` for streaming.
- **Returns:** `stopped_reason`, `round_summaries`, `returncode` (`0` when judge accepted and `raw_data` exists), `raw_data_path`, `raw_data_exists`, `last_spec`, `judge_reasoning` on failure. Each round summary also includes workspace save confirmation when available.
- **ReAct example:** *Thought: Need a multi-asset panel for the user’s strategy.* → *Action: run_data_loader* with `{ "goal": "<subtask + parent goal>" }`.

---

## `load_data`

- **What it does:** If **`tickers`** is set → downloads OHLCV via **yfinance** (one fixed code path). If omitted → small **demo stub** for pipeline tests.
- **When to use:** One-shot fetch when kwargs are already known, tests, or internal use by `run_data_loader`. Not the default pipeline entry for “download data” subtasks.
- **Arguments (yfinance path):**
  - `tickers`: string (comma-separated) or list, e.g. `"SPY"` or `"SPY,TLT"` or `GC=F`
  - `period`: e.g. `1y`, `2y`, `max` (used when `start`/`end` not set)
  - `start` / `end`: optional `YYYY-MM-DD`
  - `interval`: default `1d` (`1wk`, `1h`, … per Yahoo limits)
  - `auto_adjust`, `prepost`, `actions`: booleans
  - `rationale`: optional string for logs
- **Arguments (stub path):** omit `tickers` or use `dataset: "demo"`.
- **Design note:** Let a **planner LLM** read `docs/yfinance_guide.md` and emit these kwargs. In the main pipeline, `run_data_loader` handles this automatically via its iterative judge loop. The model should **not** write arbitrary code—only fill parameters.
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
- **When to use:** Training / fitting / regression / hyperparameter tuning / cross-validation. Usually **skip** this for rule-based strategies such as MACD, momentum ranking, fixed long-short rotations, or formulaic signals that already define positions directly.
- **Arguments:**
  - `model_name`: `linear_regression`, `ridge`, `lasso`, `elasticnet`, `random_forest`, `gradient_boosting`, `svr` (aliases `lr`, `rf`, `gbm`, `gbr`, `enet`, …)
  - `requested_model_name` (optional): if the user explicitly requested a model family in natural language, pass that request verbatim here (e.g. `RandomForestRegressor`, `Random Forest`). The tool will record whether the executed model matches and emit `spec_deviated` / `spec_deviation_reason`.
  - `feature_columns`: list or comma-separated string; **omit** to use all numeric columns except `target_column`
  - `target_column`: default `"target"`. When loading `engineered_data` from workspace, the tool reads `feature_plan.target_column` and uses it (if it is a valid identifier); this ensures training uses the same target that feature engineering produced. If the column is missing but the frame has **Adj Close** / **Close** (typical yfinance OHLCV), the tool adds `target` = **next-bar simple return** of that price series.
  - `tune_hyperparameters`: `true` / `false` — runs `RandomizedSearchCV` when a search space exists (`linear_regression` / OLS has none → `tune_ignored`)
  - `data_path`: optional path to `.csv` or `.parquet`; omit for **synthetic** data (`f0..f{n-1}` + target)
  - `n_samples`, `n_features`: synthetic data shape when no `data_path`
  - `test_size`, `random_state`, `cv_folds`, `tuning_iter`
- **Split:** For data with a **monotonic datetime index**, train/test split is **time-ordered** (last `test_size` fraction held out); otherwise sklearn `train_test_split` (shuffled).
- **Returns:** `train_r2`, `test_r2`, `test_rmse`, `best_params`, `best_cv_r2`, `feature_columns`, `target_derived_from_price` (if auto-target was used), `time_ordered_split`, plus spec-tracking fields:
  - `executed_model_key`, `executed_model_display`
  - `requested_model_key` (if provided)
  - `spec_deviated`, `spec_deviation_reason`
  - `target_prediction_horizon` (best-effort inference)
- **ReAct example:** *Thought: Tune a ridge on f0,f1,f2.* → `{ "model_name": "ridge", "feature_columns": "f0,f1,f2", "tune_hyperparameters": true }`.

---

## `run_backtest`

- **What it does:** **Skill-driven backtest sub-agent.** Reads `engineered_data` (or `raw_data`) and runs in one of two modes:
  - **`model_based`**: uses `model_output`, validates target/features, re-trains/predicts, then converts predictions to positions.
  - **`rule_based`**: uses prebuilt signal/weight/return columns and optional `feature_plan` context directly, without requiring `model_output`.
  Saves `backtest_results` to workspace.
- **When to use:** After `build_features` for rule-based strategies, or after `train_model` for predictive/ML strategies. Subtask mentions backtest, Sharpe, drawdown, turnover, PnL, equity curve, risk metrics.
- **Arguments (hyperparameters):**
  - `strategy_type`: `"long_only"` (default) | `"long_short"` — whether the strategy can short
  - `rebalance_freq`: `"daily"` | `"weekly"` | `"monthly"` — rebalance cadence. **Omit** to let the tool infer `weekly` / `monthly` from `feature_plan` text (e.g. W-FRI, 周频); if nothing matches, defaults to `"daily"`. When the user’s goal states a cadence, **pass it explicitly** here (do not rely on inference alone).
  - `position_sizing`: `"equal_weight"` | `"signal_proportional"` (default) | `"volatility_scaled"`
  - `transaction_cost_bps`: float, default `0.0` — round-trip cost in basis points (use `> 0` only when the user explicitly asked for transaction costs)
  - `max_position_pct`: float 0–1, default `1.0` — max portfolio fraction per position
  - `initial_capital`: float, default `1000000`
  - `train_ratio`: optional float 0.1–1.0 — time-ordered train fraction; default **`1.0` for `rule_based`** (full-sample metrics) and **`0.7` for `model_based`** unless you pass an explicit value
  - `timeout_sec`: script execution timeout (default `180`)
  - `workspace`: auto-injected; must contain `engineered_data` or `raw_data`; `model_output` optional (selects mode)
- **Returns:** `sharpe`, `max_drawdown`, `total_return`, `annual_return`, `win_rate`, `n_test_days`, `backtest_mode`, plus script execution details. Saves `backtest_results` JSON to workspace.
- **ReAct example:** *Thought: Need long-short daily backtest with 10bps costs.* → *Action: run_backtest* with `{ "strategy_type": "long_short", "rebalance_freq": "daily", "transaction_cost_bps": 10, "train_ratio": 0.7 }`.
- **ReAct example (rotation):** *Thought: User asked for weekly rebalance.* → *Action: run_backtest* with `{ "rebalance_freq": "weekly", "strategy_type": "long_only" }`.

---

## `evaluate_strategy`

- **What it does:** **LLM-driven evaluation.** Reads `backtest_results`, optional `model_output`, and optionally `feature_plan` from workspace. A senior quant reviewer LLM produces a structured `StrategyVerdict` with overall rating, strengths, weaknesses, risk assessment, and concrete next steps. If no `model_output` is present, the reviewer treats the run as a **rule-based** strategy review (not incomplete). Saves `evaluation` to workspace.
- **When to use:** After `run_backtest`. Subtask mentions evaluation, summary, conclusion, verdict, next steps, robustness.
- **Arguments:**
  - `workspace`: auto-injected; should contain `backtest_results` and/or `model_output`
  - `model`: optional LLM model override
- **Returns:** `verdict` (`strong` | `promising` | `weak` | `failed`), `summary`, `strengths`, `weaknesses`, `risk_assessment`, `next_steps`, `deploy_ready`. Saves `evaluation` JSON to workspace.
- **ReAct example:** *Thought: Backtest done, need to interpret results.* → *Action: evaluate_strategy* with `{}`.

---

## `run_debug_agent`

- **What it does:** Invokes the debug LLM on the current workspace plus optional goal/query text. Produces structured diagnosis and suggested recovery steps; saves **`debug_notes`** to workspace.
- **When to use:** When a subtask explicitly asks for debugging, or when the orchestrator needs a post-failure diagnosis (optional; controlled by env / workflow).
- **Arguments:**
  - `workspace`: auto-injected
  - `goal`, `query`: natural-language context (executor may fill from the subtask)
  - `model`: optional override (defaults to `OPENAI_TASK_MODEL` or `OPENAI_SMALL_MODEL`)
- **Returns:** Diagnosis dict plus `workspace_artifact: debug_notes` when successful.
- **ReAct example:** *Thought: Need to understand why build_features failed.* → *Action: run_debug_agent* with `{ "goal": "…", "query": "traceback from feature_eng" }`.

---

## Python entrypoint

With `scripts/` on `sys.path`:

```python
from tools import run_tool, list_tools, TOOL_REGISTRY

run_tool("load_data", dataset="demo")
```

Implementations live under `scripts/tools/*.py`; each function has a docstring describing usage.
