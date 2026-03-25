# Skill: data_analysis

Use when the agent must **understand a dataset before modeling** (EDA / profiling / quality checks).

## What you produce

You write a **single runnable Python script** (the runtime will prepend a small injected block). The script must:

1. If `DATA_PATH` is a non-empty string: load it with **pandas** (`read_csv` or `read_parquet` by suffix). If `DATA_PATH` is `None`: build a small **synthetic** `DataFrame` so the script still runs (e.g. `np.random.default_rng` + `pd.DataFrame`), and state that in the summary.
2. Compute **descriptive** stats: `dtypes`, `shape`, missing counts / share, numeric `describe()`, optional correlation matrix for numeric columns (no huge prints — cap width).
3. Write a **JSON summary** to `OUTPUT_JSON` (path injected): keys at least `shape`, `columns`, `dtypes` (as str list or dict), `missing_pct` (per column or top 20), `notes` (short strings about issues). Optional: `numeric_describe` as nested dict with stringified floats.
4. **Print** a short human-readable recap to stdout (≤ ~40 lines).
5. **No network**, no subprocess, no shelling out, no `eval`/`exec` on untrusted strings, no reading arbitrary paths — only `DATA_PATH` and `OUTPUT_JSON`.

## Allowed imports

`pandas`, `numpy`, `json`, `pathlib`, `sys`, `warnings`.  
Optional: `matplotlib` only if you **save** a figure under the same run directory using `OUTPUT_JSON.parent` (never `plt.show()` in batch).

## Style

- Be defensive: catch load errors and write them into `OUTPUT_JSON["error"]`.
- Keep runtime modest (avoid O(n²) on huge tables unless sampled).
- **pandas frequency aliases:** for month-end logic use `ME`, not `M` (pandas 3+ rejects `M`). If you resample monthly, prefer `resample("ME")`; for explicit month-end offsets use the modern alias / API rather than deprecated `M`.

## Inputs you can assume (injected)

- `DATA_PATH: str | None`
- `OUTPUT_JSON: pathlib.Path`

Do **not** redefine those names.
