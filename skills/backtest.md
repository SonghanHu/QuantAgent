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
| `position_sizing` | `"equal_weight"` \| `"signal_proportional"` \| `"volatility_scaled"` | How to size positions from signals |
| `transaction_cost_bps` | float | Round-trip cost in basis points |
| `max_position_pct` | float (0–1) | Max fraction of portfolio in one position |
| `initial_capital` | float | Starting portfolio value |
| `train_ratio` | float (0.1–1.0) | Time-ordered split: first fraction **train**, remainder **test** for metrics. **`1.0` = evaluate on the full aligned history (no hold-out)** — **default for `rule_based`** when the tool does not override. For `model_based`, values `< 1` reserve an out-of-sample test tail for predictions. |

## What you produce

A **single Python script** that:

1. Loads the dataset from `DATA_PATH` (pandas — `.parquet` or `.csv`).
2. Branches on `BACKTEST_MODE`:
   - **`model_based`**:
     - Split data into **train** and **test** by time order (using `train_ratio`), ensuring **no look-ahead**.
     - Train the model specified in `MODEL_OUTPUT_JSON` (model type + feature columns + target) on the train set using scikit-learn.
     - Generate **predictions** on the test set.
     - Convert predictions into signals.
   - **`rule_based`**:
     - Do **not** train a model.
     - When `train_ratio == 1.0` (typical): compute strategy returns and **all** summary metrics on the **entire** usable date range (after any warm-up / NaN drop). Do **not** report metrics only on a short “test tail” unless `train_ratio < 1`.
     - Use prebuilt rule columns from the data directly. Prefer, in order:
       1. Precomputed **strategy return** columns (`strategy_ret`, `strategy_ret_net`, …) if they are clearly portfolio returns.
       2. **Signal / score** columns (`composite_score_*`, `signal*`, `score*`, `alpha*`, `mom*`, `rank_*`, `rel_str_*`, …) — normalize to weights, apply **`rebalance_freq`** (daily / weekly / monthly), then **`shift(1)`** so positions are known **before** each bar’s return (no look-ahead).
       3. Generic weight columns (`w_*`, `weight*`, `position*`) **only if** they are execution-ready (already lagged). **Do not** treat `target_pos*`, `target_*`, or the feature plan’s `target_column` as raw tradable weights when those columns encode **labels**, hypothetical “next period winners”, or unshifted targets — that causes leakage and absurd equity curves. If unsure, rebuild positions from scores in step 2 instead.
     - If explicit weights are missing but signals exist, convert them into positions using `strategy_type` and `position_sizing`.
     - If the data already contains strategy return columns (e.g. `strategy_ret`, `strategy_ret_net`), you may use them directly and still compute metrics/turnover defensively.
3. Applies **position sizing** per `position_sizing` when positions must be derived:
   - `equal_weight`: sign of signal only (fixed size)
   - `signal_proportional`: normalize signals so abs sum = 1, clip by `max_position_pct`
   - `volatility_scaled`: scale by inverse rolling volatility of returns
4. Computes **daily strategy returns** = position(t-1) × actual_return(t) − transaction_costs.
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
  "test_start": "YYYY-MM-DD",
  "test_end": "YYYY-MM-DD",
  "n_test_days": int,
  "equity_curve": [float, ...],
  "equity_dates": ["YYYY-MM-DD", ...],
  "trade_events": [
    { "date": "YYYY-MM-DD", "side": "buy" | "sell", "label": "optional reason" },
    { "index": 42, "side": "sell", "label": "optional" }
  ],
  "config": { ... },
  "notes": "..."
}
```

`equity_dates` (same length as `equity_curve`) and `trade_events` are **optional** but recommended: the run pipeline builds an interactive equity chart from them. Use either ISO `date` or integer `index` into the evaluated return series. Omit `trade_events` if there are no discrete trades to mark.

6. Optionally saves an equity curve plot to `RUN_DIR / "equity.png"` (matplotlib, `savefig` only, never `show()`).
7. Prints a short human-readable recap to stdout (≤ 40 lines).

For `test_start` / `test_end` / `n_test_days`: use the **actual** first/last **dates** of the return series you evaluated (prefer the DataFrame’s **DatetimeIndex**). If the index is not datetimes, convert or derive dates from a date column — **never** emit placeholder epochs like `1970-01-01` unless that date truly appears in the data.

## Rules

- **No look-ahead:** train only on data before test period; rolling features must use only past data. Positions for bar *t* must be fixed from information available at *t−1* (or last rebalance), then multiplied by returns at *t*.
- **Match cadence:** `rebalance_freq` in `BACKTEST_CONFIG_JSON` must match how you form holdings (e.g. weekly plan → weekly rebalance mask, not daily unless the user asked for daily).
- **Annualize:** Sharpe = mean(daily_returns) / std(daily_returns) × sqrt(252). Adjust if `rebalance_freq` != daily.
- **Transaction costs:** compute turnover as sum of abs position changes; cost = turnover × `transaction_cost_bps` / 10000.
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
