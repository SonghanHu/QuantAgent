# Skill: feature_engineering

Use when the agent has finished data analysis and needs to **produce concrete feature columns + a target column** for modeling.

## Context you receive

- `FeaturePlan` from the data analyst sub-agent: list of `FeatureSpec(name, logic, rationale)` + `target_column`.
- The original data (via `DATA_PATH`).

## What you produce

A **single Python script** that:

1. Loads the dataset from `DATA_PATH` (pandas).
2. For each feature in the plan, computes the column using the `logic` field (pandas / numpy operations).
3. **Creates the target column** (critical for downstream training and backtesting):
   - The required column name is given by the injected variable `TARGET_COLUMN`.
   - If `TARGET_COLUMN` already exists in the data, keep it as-is.
   - Otherwise derive it: **next-bar simple return** from `Adj Close` (preferred) or `Close`:
     `df[TARGET_COLUMN] = df[price_col].pct_change().shift(-1)`
   - If neither price column exists, write an error summary to `OUTPUT_JSON` and `sys.exit(1)`.
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
