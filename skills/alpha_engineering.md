# Skill: alpha_engineering

Use when the agent needs to **construct quantitative alpha factors** inspired by WorldQuant-style alpha expressions, formulaic alphas, and systematic factor research.

## Context you receive

- `AlphaPlan` from the data analyst or user: list of `AlphaSpec(name, expression, category, rationale)` + `target_column`.
- The original OHLCV data (via `DATA_PATH`).
- Optional `SEARCH_CONTEXT` with recent research findings or alpha ideas from web search.

## Alpha categories

Generate features across these factor families:

| Category | Examples |
|----------|---------|
| **Momentum** | cross-sectional momentum, time-series momentum, 52-week high ratio, acceleration |
| **Mean-reversion** | RSI, Bollinger %B, distance to MA, Ornstein–Uhlenbeck half-life |
| **Volume** | VWAP deviation, volume surprise, Amihud illiquidity, Kyle lambda proxy |
| **Volatility** | realized vol, Garman-Klass vol, vol-of-vol, ATR ratio, skew of returns |
| **Price patterns** | gap ratio, intraday range, candle body ratio, open-close asymmetry |
| **Technical** | MACD signal, Stochastic %K/%D, Williams %R, CCI, ADX proxy |
| **Composite / interaction** | momentum × volume surprise, vol-adjusted momentum, mean-reversion conditioned on regime |

## WorldQuant-style expression syntax (reference)

The script should implement alphas using pandas/numpy, but conceptually these map to:

```
rank(ts_delta(close, 5))                     # 5-day momentum ranked
-1 * ts_corr(close, volume, 10)              # price-volume divergence
ts_rank(ts_stddev(returns, 20), 60)           # vol regime rank
(close - ts_mean(close, 20)) / ts_stddev(close, 20)  # z-score
ts_decay_linear(returns, 10)                  # weighted momentum
rank(volume / ts_mean(volume, 20)) * sign(returns)    # volume-confirmed direction
```

## What you produce

A **single Python script** that:

1. Loads the dataset from `DATA_PATH` (pandas).
2. Implements each alpha from `ALPHA_PLAN_JSON` using pandas/numpy operations.
3. Adds **helper functions** at the top for common operations:
   - `ts_rank(series, window)` — rolling percentile rank
   - `ts_decay_linear(series, window)` — linearly-weighted rolling sum
   - `ts_corr(x, y, window)` — rolling correlation
   - `rank(series)` — cross-sectional percentile rank (for panel data) or simple rank
   - `scale(series)` — normalize to sum of abs = 1
4. **Creates the target column**:
   - Use `TARGET_COLUMN` as the required label name.
   - If missing, derive as next-bar simple return from `Adj Close` or `Close`.
   - If no price column exists, write error summary and `sys.exit(1)`.
5. Handles NaN: drops rows where `TARGET_COLUMN` is NaN, forward-fills or drops warm-up NaN rows.
6. **Winsorizes** extreme alpha values at 1st/99th percentile to reduce outlier impact.
7. Saves the enriched DataFrame to `OUTPUT_PATH` (`.parquet`).
8. Writes a JSON summary to `OUTPUT_JSON`:
   ```json
   {
     "alphas_created": ["alpha_mom_5d", "alpha_vol_surprise", ...],
     "alpha_categories": {"momentum": 3, "volume": 2, ...},
     "target_column": "<TARGET_COLUMN>",
     "target_source": "existing | derived from <price_col>",
     "rows": <int>,
     "columns": <int>,
     "ic_preview": {"alpha_name": <rank_ic_with_target>, ...},
     "notes": "..."
   }
   ```
9. Computes a quick **information coefficient** (Spearman correlation of each alpha with target) and includes in summary.
10. Prints a short recap to stdout (<= 40 lines).

## Rules

- **No look-ahead:** all alphas use only data available at time t. Only `shift(-1)` for target.
- **No network, no subprocess.** Only `DATA_PATH`, `OUTPUT_PATH`, `OUTPUT_JSON`.
- Allowed imports: `pandas`, `numpy`, `json`, `pathlib`, `sys`, `warnings`, `scipy.stats` (for rank correlation).
- Do **not** rename or drop `TARGET_COLUMN`.
- Winsorize alphas but not the target or original price columns.
- If panel data (multiple assets): rank and scale within each cross-section (date).

## Injected variables (do not redefine)

- `DATA_PATH: str`
- `OUTPUT_PATH: str` (enriched `.parquet`)
- `OUTPUT_JSON: pathlib.Path`
- `RUN_DIR: pathlib.Path`
- `ALPHA_PLAN_JSON: str` (serialized list of `{"name", "expression", "category", "rationale"}`)
- `TARGET_COLUMN: str`
- `SEARCH_CONTEXT: str` (optional research context from web search, may be empty)
