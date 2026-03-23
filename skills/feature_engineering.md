# Skill: feature_engineering

Use when the agent has finished data analysis and needs to **produce concrete feature columns** for modeling.

## Context you receive

- `FeaturePlan` from the data analyst sub-agent: list of `FeatureSpec(name, logic, rationale)` + `target_column`.
- The original data (via `DATA_PATH`).

## What you produce

A **single Python script** that:

1. Loads the dataset from `DATA_PATH` (pandas).
2. For each feature in the plan, computes the column using the `logic` field (pandas / numpy operations).
3. Handles edge cases: NaN from rolling windows, division by zero, look-ahead bias (only use past data for each row).
4. Saves the enriched DataFrame (original columns + new features) to `OUTPUT_PATH` (`.parquet`).
5. Writes a JSON summary to `OUTPUT_JSON`: `{ "features_created": [...], "rows", "columns", "nulls_introduced", "notes" }`.
6. Prints a short recap to stdout (≤ 30 lines).

## Rules

- **No look-ahead:** rolling / lag features must only use data available at the current timestamp.
- **No network, no subprocess.** Only `DATA_PATH`, `OUTPUT_PATH`, `OUTPUT_JSON`.
- Allowed imports: `pandas`, `numpy`, `json`, `pathlib`, `sys`, `warnings`.

## Injected variables (do not redefine)

- `DATA_PATH: str`
- `OUTPUT_PATH: str` (where to write the enriched `.parquet`)
- `OUTPUT_JSON: pathlib.Path`
- `RUN_DIR: pathlib.Path`
- `FEATURE_PLAN_JSON: str` (serialized list of `{"name", "logic", "rationale"}`)
