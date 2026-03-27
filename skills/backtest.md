# Skill: backtest

Use when the agent must **simulate a trading strategy** on historical data and produce risk/return metrics.

## Context you receive

- Engineered (or raw) data with features and a target column.
- Strategy context:
  - `BACKTEST_MODE`: `"model_based"` or `"rule_based"`
  - `MODEL_OUTPUT_JSON`: training output when in model-based mode
  - `STRATEGY_CONTEXT_JSON`: feature plan, data columns, and other hints
- **Backtest configuration** (structured hyperparameters — see below).

## Backtest configuration (injected as `BACKTEST_CONFIG_JSON`)

The planner decides these; you **must respect them exactly**:

| Parameter | Type | Meaning |
|-----------|------|---------|
| `strategy_type` | `"long_only"` \| `"long_short"` | Whether the strategy can short |
| `rebalance_freq` | `"daily"` \| `"weekly"` \| `"monthly"` | How often positions are rebalanced |
| `position_sizing` | `"equal_weight"` \| `"signal_proportional"` \| `"volatility_scaled"` | How to size positions from signals — **must match the user’s stated rule** (e.g. never replace explicit equal-weight with signal-proportional or vol-scaled unless the user asked for that). |
| `transaction_cost_bps` | float | Round-trip cost in basis points — use **`0` unless the user explicitly requested costs**; apply the injected value exactly (no implicit extra bps). |
| `max_position_pct` | float (0–1) | Max fraction of portfolio in one position |
| `initial_capital` | float | Starting portfolio value |
| `train_ratio` | float (0.1–1.0) | Time-ordered split: first fraction **train**, remainder **test** for metrics. **`1.0` = evaluate on the full aligned history (no hold-out)** — **default for `rule_based`** when the tool does not override. For `model_based`, values `< 1` reserve an out-of-sample test tail for predictions. |

## Strategy fidelity (mandatory)

When `STRATEGY_CONTEXT_JSON` / feature plan / user goal states an explicit portfolio rule, **preserve it exactly**.

- Do **not** change **equal-weight** into `signal_proportional`, `volatility_scaled`, or any other sizing rule unless the user asked for that change.
- Do **not** add transaction costs unless `transaction_cost_bps` in config is **> 0** (reflecting an explicit user request). When it is `0`, charge **no** cost.
- Do **not** introduce extra ranking, filtering, or feature-based weighting layers unless the user requested them.
- If the strategy is **rule-based** and fully specified in context, implement the **simplest faithful** version — no “improvements” that alter economics.

## Execution timing (mandatory)

State the timing convention in code comments and honor it consistently.

- If the signal uses **close-based** information on day **t**, the **earliest** portfolio return that can be attributed to that decision is on day **t+1** (one bar lag unless the user specifies another convention).
- Apply **exactly one** lag between **target weight generation** (from information known at signal time) and **realized** portfolio return for that bar — do not **double-lag** by shifting both weights and returns in a way that stacks two unintended delays.
- Align with `rebalance_freq`: weights used for return on date *d* must be those in force at the **open** of *d* (or your stated convention), derived from information available **before** *d*’s return is realized.

## Rebalance rules (mandatory)

- **Daily rebalance:** compute target weights each signal day and hold them for the **next** bar’s return (after the one-lag rule above).
- **Weekly / monthly:** update target weights **only** on rebalance dates; **forward-fill** held weights between rebalance dates (constant holdings until the next rebalance).
- Never write **tautological** rebalance masks (e.g. `reb_mask | ~reb_mask` = always true) — each mask must be a meaningful calendar or rule-based selector.

## Required validation (before finalizing the script)

Before writing `OUTPUT_JSON`, verify:

1. **Strategy rule** matches the user / feature-plan request (sizing, long-only, assets, signals) — no silent substitutions.
2. **Transaction costs** match config: `transaction_cost_bps == 0` ⇒ **zero** cost in the return math; positive ⇒ apply exactly that rate to turnover (or as specified in your cost model, stated in `notes`).
3. **Lag structure** is correct: one intentional lag from signal to return; no double lag.
4. **Turnover** is computed from **actual held** weights (post-ffill for weekly/monthly), not from pre-ffill targets alone if that misstates trading.
5. **Survivorship / universe bias:** if data or tools imply current constituents only (e.g. S&P 500 list without history), say so briefly in `notes`.
6. **Signal mapping must be explicit (especially for model_based long/flat):**
   - State the prediction target horizon (e.g. `next-day return`) in `signal_mapping.prediction_target_horizon`.
   - State the signal rule / threshold used to decide **invested vs flat** in `signal_mapping.signal_rule`.
   - State the execution / holding rule (e.g. hold from next bar close) in `signal_mapping.execution`.
   - Compute and report exposure stats:
     - `signal_mapping.avg_gross_exposure` (average of sum(abs(weights)) over evaluated days)
     - `signal_mapping.percent_days_invested` (percentage of evaluated days where gross exposure > 0)
   - Define `win_rate` denominator precisely:
     - If your strategy can be flat, `win_rate` must be computed on **invested days only** by default (exclude flat days from denominator), unless the user explicitly asked otherwise.
     - Record this definition in `signal_mapping.win_rate_definition`.

## What you produce

A **single Python script** that:

1. Loads the dataset from `DATA_PATH` (pandas — `.parquet` or `.csv`).
2. Branches on `BACKTEST_MODE`:
   - **`model_based`**:
     - Split data into **train** and **test** by time order (using `train_ratio`), ensuring **no look-ahead**.
     - Train the model specified in `MODEL_OUTPUT_JSON` (model type + feature columns + target) on the train set using scikit-learn.
     - Generate **predictions** on the test set.
     - Convert predictions into signals using an **explicit, auditable mapping**:
       - Define `signal_threshold` (default `0.0` unless the user explicitly requested another threshold or the strategy context provides one).
       - For `long_only` strategies:
         - **Invested vs flat:** invest when `y_pred > signal_threshold`, otherwise hold flat (no exposure).
       - For `long_short` strategies:
         - Use the same threshold explicitly to decide long vs short (e.g. `y_pred > threshold` => long, `y_pred < -threshold` => short, otherwise flat) unless strategy context specifies a different rule.
       - Store the mapping in `signal_mapping` (threshold, long/flat conditions, execution/holding rule) and ensure win-rate is computed using the same invested-vs-flat definition.
   - **`rule_based`**:
     - Do **not** train a model.
     - When `train_ratio == 1.0` (typical): compute strategy returns and **all** summary metrics on the **entire** usable date range (after any warm-up / NaN drop). Do **not** report metrics only on a short “test tail” unless `train_ratio < 1`.
     - Use prebuilt rule columns from the data directly. Prefer, in order:
       1. Precomputed **strategy return** columns (`strategy_ret`, `strategy_ret_net`, …) if they are clearly portfolio returns.
       2. **Signal / score** columns (`composite_score_*`, `signal*`, `score*`, `alpha*`, `mom*`, `rank_*`, `rel_str_*`, …) — normalize to weights, apply **`rebalance_freq`** (daily / weekly / monthly), then **`shift(1)`** so positions are known **before** each bar’s return (no look-ahead).
       3. Generic weight columns (`w_*`, `weight*`, `position*`) **only if** they are execution-ready (already lagged). **Do not** treat `target_pos*`, `target_*`, or the feature plan’s `target_column` as raw tradable weights when those columns encode **labels**, hypothetical “next period winners”, or unshifted targets — that causes leakage and absurd equity curves. If unsure, rebuild positions from scores in step 2 instead.
     - If explicit weights are missing but signals exist, convert them into positions using `strategy_type` and **`position_sizing` from config exactly** — do not override equal-weight with proportional sizing (or vice versa) unless the user asked for it.
     - If the data already contains strategy return columns (e.g. `strategy_ret`, `strategy_ret_net`), you may use them directly and still compute metrics/turnover defensively.
3. Applies **position sizing** per `position_sizing` when positions must be derived:
   - `equal_weight`: sign of signal only (fixed size)
   - `signal_proportional`: normalize signals so abs sum = 1, clip by `max_position_pct`
   - `volatility_scaled`: scale by inverse rolling volatility of returns
4. Computes **daily strategy returns** = position(t-1) × actual_return(t) **minus transaction costs only if** `config['transaction_cost_bps'] > 0`, using that value exactly (turnover × bps / 10000 or equivalent documented in `notes`). If bps is `0`, **omit** cost or add zero — do not invent costs.
5. Computes metrics and writes them to `OUTPUT_JSON`:

```json
{
  "sharpe": float,
  "annual_return": float,
  "max_drawdown": float,
  "calmar_ratio": float,
  "total_return": float,
  "win_rate": float,
  "avg_turnover": float,
  "n_trades": int,
  "signal_mapping": {
    "prediction_target_horizon": "next-day return",
    "signal_rule": string,
    "execution": string,
    "signal_threshold": null,
    "avg_gross_exposure": float,
    "percent_days_invested": float,
    "win_rate_definition": string
  },
  "test_start": "YYYY-MM-DD",
  "test_end": "YYYY-MM-DD",
  "n_test_days": int,
  "equity_curve": [float, ...],
  "equity_dates": ["YYYY-MM-DD", ...],
  "trade_events": [
    { "date": "YYYY-MM-DD", "side": "buy" | "sell", "label": "optional reason" },
    { "index": 42, "side": "sell", "label": "optional" }
  ],
  "benchmark_curves": [
    { "label": "SPY buy & hold", "equity": [float, ...] },
    { "label": "Equal weight", "equity": [float, ...] }
  ],
  "config": { ... },
  "notes": "..."
}
```

`equity_dates` (same length as `equity_curve`) and `trade_events` are **optional** but recommended: the run pipeline builds an interactive equity chart from them. Use either ISO `date` or integer `index` into the evaluated return series. Omit `trade_events` if there are no discrete trades to mark.

**Benchmark curves (recommended for comparison charts):** When you also compute buy-and-hold, equal-weight, or index benchmarks on the **same evaluation dates** as `equity_curve`, include them as `benchmark_curves`: a list of `{ "label": str, "equity": [float, ...] }` where each `equity` array has the **same length** as `equity_curve` (same bar index, same `initial_capital` scaling). The dashboard and static PNG overlay these lines for visual comparison. Omit if not computed.

6. Optionally saves an equity curve plot to `RUN_DIR / "equity.png"` (matplotlib, `savefig` only, never `show()`).
7. Prints a short human-readable recap to stdout (≤ 40 lines).

For `test_start` / `test_end` / `n_test_days`: use the **actual** first/last **dates** of the return series you evaluated (prefer the DataFrame’s **DatetimeIndex**). If the index is not datetimes, convert or derive dates from a date column. **Never** derive dates by coercing arbitrary numeric columns into timestamps, and **never** emit placeholder epochs like `1970-01-01` unless that date truly appears in the data. If no trustworthy dates exist, omit `equity_dates` and explain the limitation in `notes` rather than fabricating dates.

## Rules

- **Automated code review (runner):** Before your script is executed, a separate review model may reject it for look-ahead risk, forbidden imports, NA-unsafe pandas, or OUTPUT_JSON contract gaps. If rejected, the same skill prompt is called again with **revision instructions** — incorporate fixes without arguing; keep the script minimal and compliant.
- **pandas NA / boolean ambiguity (mandatory):** A failed run often raises `ValueError: boolean value of NA is ambiguous`. You **must** avoid it:
  - Never use `if series:` or `bool(series)` on a pandas `Series` that may contain `NA`/`NaN`.
  - For compound masks, make every piece NA-safe: e.g. `(a > 0) & b` → `(a.notna() & (a > 0)) & b.fillna(False)` or `(a.fillna(-np.inf) > 0) & ...` as appropriate.
  - Before boolean indexing (`df.loc[mask]`), use `mask = mask.fillna(False)` (or `mask & df.index.notna()` if the mask is aligned).
  - After `rank`, `idxmax`, `argsort`, or cross-sectional `max` across columns, replace missing ranks/scores before comparisons; do not feed `NA` into `>`, `==`, or `np.where` without `fillna` / `where(..., other)`.
  - When building weekly hold positions from signals, explicitly `dropna`/`ffill` only where theory allows, or skip rebalance rows with incomplete scores — never leave `NA` in a column that later drives a boolean filter.
- **No look-ahead:** train only on data before test period; rolling features must use only past data. Positions for bar *t* must be fixed from information available at *t−1* (or last rebalance), then multiplied by returns at *t*.
- **Match cadence:** `rebalance_freq` in `BACKTEST_CONFIG_JSON` must match how you form holdings (e.g. weekly plan → weekly rebalance mask, not daily unless the user asked for daily).
- **Annualize:** Sharpe = mean(daily_returns) / std(daily_returns) × sqrt(252). Adjust if `rebalance_freq` != daily.
- **Transaction costs:** only when `transaction_cost_bps` > 0; turnover from **actual held** weights; cost = turnover × `transaction_cost_bps` / 10000 (or document alternative in `notes` if the user specified one). When bps is 0, do not apply costs.
- In `rule_based` mode, prefer using columns already produced by feature engineering rather than recreating the strategy from scratch.
- **pandas frequency aliases:** if implementing monthly rebalancing or month-end resampling, use `ME` rather than `M` (pandas 3+ no longer supports `M`).
- **No network, no subprocess.** Only `DATA_PATH`, `OUTPUT_JSON`, `RUN_DIR`.
- Be defensive: if the model fails to train or data is insufficient, write an error entry to `OUTPUT_JSON`.

## Allowed imports

`pandas`, `numpy`, `json`, `pathlib`, `sys`, `warnings`, `sklearn` (only for `model_based` re-fitting), `matplotlib` (for saving charts only).

## Injected variables (do not redefine)

- `DATA_PATH: str` — path to the engineered (or raw) data
- `OUTPUT_JSON: pathlib.Path` — where to write results
- `RUN_DIR: pathlib.Path` — directory for charts and artifacts
- `BACKTEST_CONFIG_JSON: str` — serialized backtest hyperparameters
- `BACKTEST_MODE: str` — `"model_based"` or `"rule_based"`
- `STRATEGY_CONTEXT_JSON: str` — serialized strategy context (feature plan, data columns, hints)
- `MODEL_OUTPUT_JSON: str` — serialized model training output (present mainly for `model_based`)
- `_CFG` / `config` — `dict` from `json.loads(BACKTEST_CONFIG_JSON)` (use for all hyperparameters)
- `get_rebalance_freq()` — **preferred inside nested functions** (returns rebalance cadence string)
- `effective_rebalance` — module-level `str` alias; **do not read this name inside `def`/`lambda` bodies** unless you `global effective_rebalance` — use `get_rebalance_freq()` there to avoid `UnboundLocalError`

The full runnable file is written to `RUN_DIR / "backtest.py"` and mirrored into the workspace as `backtest_generated.py` for the dashboard.
