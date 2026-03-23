# Skill: backtest

Use when the agent must **simulate a trading strategy** on historical data and produce risk/return metrics.

## Context you receive

- Engineered (or raw) data with features and a target column.
- Model training output: which model was used, feature columns, target column, train/test metrics.
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
| `train_ratio` | float (0–1) | Fraction of data used for in-sample training; remainder is out-of-sample |

## What you produce

A **single Python script** that:

1. Loads the dataset from `DATA_PATH` (pandas — `.parquet` or `.csv`).
2. Splits data into **train** and **test** by time order (using `train_ratio`), ensuring **no look-ahead**.
3. Trains the model specified in `MODEL_OUTPUT_JSON` (model type + feature columns + target) on the train set using scikit-learn.
4. Generates **predictions** on the test set.
5. Converts predictions into **signals**:
   - `long_only`: signal = clipped prediction (≥ 0)
   - `long_short`: signal = raw prediction (positive = long, negative = short)
6. Applies **position sizing** per `position_sizing`:
   - `equal_weight`: sign of signal only (fixed size)
   - `signal_proportional`: normalize signals so abs sum = 1, clip by `max_position_pct`
   - `volatility_scaled`: scale by inverse rolling volatility of returns
7. Computes **daily strategy returns** = position(t-1) × actual_return(t) − transaction_costs.
8. Computes metrics and writes them to `OUTPUT_JSON`:

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
  "config": { ... },
  "notes": "..."
}
```

9. Optionally saves an equity curve plot to `RUN_DIR / "equity.png"` (matplotlib, `savefig` only, never `show()`).
10. Prints a short human-readable recap to stdout (≤ 40 lines).

## Rules

- **No look-ahead:** train only on data before test period; rolling features must use only past data.
- **Annualize:** Sharpe = mean(daily_returns) / std(daily_returns) × sqrt(252). Adjust if `rebalance_freq` != daily.
- **Transaction costs:** compute turnover as sum of abs position changes; cost = turnover × `transaction_cost_bps` / 10000.
- **No network, no subprocess.** Only `DATA_PATH`, `OUTPUT_JSON`, `RUN_DIR`.
- Be defensive: if the model fails to train or data is insufficient, write an error entry to `OUTPUT_JSON`.

## Allowed imports

`pandas`, `numpy`, `json`, `pathlib`, `sys`, `warnings`, `sklearn` (for model re-fitting), `matplotlib` (for saving charts only).

## Injected variables (do not redefine)

- `DATA_PATH: str` — path to the engineered (or raw) data
- `OUTPUT_JSON: pathlib.Path` — where to write results
- `RUN_DIR: pathlib.Path` — directory for charts and artifacts
- `BACKTEST_CONFIG_JSON: str` — serialized backtest hyperparameters
- `MODEL_OUTPUT_JSON: str` — serialized model training output (model name, features, target, metrics)
