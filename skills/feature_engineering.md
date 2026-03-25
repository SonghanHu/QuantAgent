# Skill: feature_engineering

Use when the agent has finished data analysis and needs to **produce concrete feature columns + a target column** for modeling.

## Context you receive

- `FeaturePlan` from the data analyst sub-agent: list of `FeatureSpec(name, logic, rationale)` + `target_column`.
- The original data (via `DATA_PATH`).

## What you produce

A **single Python script** that:

1. Loads the dataset from `DATA_PATH` (pandas).
2. For each feature in the plan, computes the column using the `logic` field (pandas / numpy operations).
3. **Creates the target column** (critical for downstream training and pipeline compatibility):
   - The required column name is given by the injected variable `TARGET_COLUMN`.
   - If `TARGET_COLUMN` already exists in the data, keep it as-is.
   - Otherwise derive it from the **best available price columns**:
     - First prefer bare single-asset columns: `Adj Close`, then `Close`.
     - If the frame is a multi-asset wide panel, also support suffixed columns such as `Adj Close_GLD`, `Adj Close_USO`, `Close_SPY`, etc.
   - Infer the forward-return horizon from `TARGET_COLUMN` when obvious:
     - contains `next_week`, `week`, or `5d` → use about 5 trading days
     - otherwise default to next-bar / 1-day
   - For a multi-asset panel with several price columns and no pre-existing `TARGET_COLUMN`, it is acceptable to create a **pipeline-compatibility target** as the equal-weight forward return across the detected assets, and explain that choice in the summary `notes`.
   - If no trustworthy price columns exist at all, write an error summary to `OUTPUT_JSON` and `sys.exit(1)`.
   - The final parquet **must** contain a column named exactly `TARGET_COLUMN`.
4. Handles edge cases: NaN from rolling windows, division by zero, look-ahead bias (only use past data for each row).
5. Drops rows where `TARGET_COLUMN` is NaN (tail row from shift, warm-up NaN rows).
6. Saves the enriched DataFrame (original columns + new features + target) to `OUTPUT_PATH` (`.parquet`).
7. Writes a JSON summary to `OUTPUT_JSON`:
   ```json
   {
     "features_created": ["feat1", "feat2", ...],
     "target_column": "<TARGET_COLUMN value>",
     "target_source": "existing | derived from <price_col>",
     "rows": <int>,
     "columns": <int>,
     "nulls_introduced": <int>,
     "notes": "..."
   }
   ```
8. Prints a short recap to stdout (<= 30 lines).

## Rules

- **Index alignment (avoids `reindex` / `_reindex_for_setitem` crashes):** Any time you assign a
  `Series` into `df[new_col] = s`, pandas aligns `s.index` to `df.index`. If they differ (e.g. you
  took `s` from another frame, a subset, or after `reset_index` on only one side), assignment can
  raise or silently misalign. **Safe patterns:**
  - Prefer computing on the same object: `df["x"] = df.groupby(...).transform(...)` or vectorized ops on `df` columns.
  - If you must use a separate `Series` `s`, ensure alignment: `df["x"] = s.reindex(df.index)` or,
    when row counts are guaranteed identical and order matches, `df["x"] = s.to_numpy()` / `s.values`.
  - Never do `df["x"] = other_df["y"]` unless `other_df.index.equals(df.index)`.
- **No look-ahead:** rolling / lag features must only use data available at the current timestamp.
  The only allowed forward operation is `shift(-1)` for the target (label).
- **Panel price data:** many runs use wide multi-asset OHLCV frames with columns like `Adj Close_GLD`,
  `Close_USO`, `Volume_UUP`. Treat these as valid price inputs. Do **not** fail just because bare
  `Adj Close` / `Close` columns are absent.
- **pandas frequency aliases:** if you need monthly resampling or month-end grouping, use `ME` rather than `M` (pandas 3+ no longer supports `M`).
- **NumPy `np.select` / mixed dtypes:** `np.select(conditions, choices, default=...)` requires every
  array in `choices` and the `default` value to share a **common dtype**. Do **not** mix **strings**
  (e.g. ticker names like `"GLD"`) with `default=np.nan` (float): NumPy raises `TypeError`. Fix by:
  using **numeric codes only** in `choices` (e.g. `0.0`, `1.0`, `2.0` for which asset is top), or
  `default=np.nan` with **all** choices as `float`/`np.float64`, or build the column with
  `pd.Series`/`map` without mixing str and float in one `np.select` call.
- **Emit a single executable script:** no markdown fences, no placeholders, no pseudo-code, no duplicated partial blocks.
- **Keep top-level structure simple:** imports → data load → feature creation → target creation → cleanup → save summary/output.
- **Indentation must be valid Python:** use consistent 4-space indentation; never leave a stray indented statement at top level.
- **No network, no subprocess.** Only `DATA_PATH`, `OUTPUT_PATH`, `OUTPUT_JSON`.
- Allowed imports: `pandas`, `numpy`, `json`, `pathlib`, `sys`, `warnings`.
- Do **not** rename or drop `TARGET_COLUMN` once created/present.
- `TARGET_COLUMN` must be a short, valid Python-identifier-like name (e.g. `target`, `fwd_ret_1d`).
  If the injected value looks invalid (long sentence, non-ASCII), default to `"target"`.

## Injected variables (do not redefine)

- `DATA_PATH: str`
- `OUTPUT_PATH: str` (where to write the enriched `.parquet`)
- `OUTPUT_JSON: pathlib.Path`
- `RUN_DIR: pathlib.Path`
- `FEATURE_PLAN_JSON: str` (serialized list of `{"name", "logic", "rationale"}`)
- `TARGET_COLUMN: str` (the label column that training and backtesting expect)
