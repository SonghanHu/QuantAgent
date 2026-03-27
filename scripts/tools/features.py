"""
Feature / alpha engineering: read plan from workspace, generate & run a script via skill.

Unified tool that auto-selects between ``feature_engineering`` and ``alpha_engineering``
skill modes based on workspace contents (presence of ``alpha_plan`` or ``search_context``).
The ``mode`` parameter can override auto-detection.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from agent.workspace import Workspace

_VALID_COL_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_ ]*$")
_DEFAULT_TARGET = "target"


def _sanitize_target_column(raw: Any) -> str:
    s = str(raw).strip() if raw else ""
    if not s or len(s) > 60 or not _VALID_COL_RE.match(s):
        return _DEFAULT_TARGET
    return s


def build_features(
    workspace: Workspace | None = None,
    timeout_sec: int = 150,
    mode: Literal["auto", "features", "alphas"] = "auto",
) -> dict[str, Any]:
    """
    Build feature / alpha columns by executing a skill-driven LLM code-gen pipeline.

    ``mode`` controls which skill markdown and preamble are used:

    - ``"features"`` — ``skills/feature_engineering.md``
    - ``"alphas"``   — ``skills/alpha_engineering.md`` (WorldQuant-style; injects ``search_context``)
    - ``"auto"`` (default) — picks ``"alphas"`` when workspace has ``alpha_plan`` or ``search_context``,
      otherwise ``"features"``

    Reads ``feature_plan`` (or ``alpha_plan``) and ``raw_data`` from workspace,
    generates a Python script, runs it, validates the output, and saves the enriched
    DataFrame as ``engineered_data``.
    """
    if workspace is None:
        return {"error": "no_workspace", "message": "build_features requires a workspace."}

    if not workspace.has("raw_data"):
        return {"error": "no_raw_data", "message": "Workspace has no raw_data. Run load_data first."}

    plan_key = "alpha_plan" if workspace.has("alpha_plan") else "feature_plan"
    if not workspace.has(plan_key):
        return {"error": "no_plan", "message": "No feature_plan or alpha_plan in workspace. Run run_data_analyst first."}

    if mode == "auto":
        use_alpha = workspace.has("alpha_plan") or workspace.has("search_context")
        skill_name = "alpha_engineering" if use_alpha else "feature_engineering"
    elif mode == "alphas":
        skill_name = "alpha_engineering"
    else:
        skill_name = "feature_engineering"

    from agent.feature_skill import execute_feature_skill

    plan = workspace.load_json(plan_key)
    target_column = _sanitize_target_column(plan.get("target_column"))
    plan["target_column"] = target_column

    items = plan.get("alphas") or plan.get("features") or []
    if not items:
        return {
            "error": "empty_plan",
            "message": f"{plan_key} has no entries. Re-run run_data_analyst with a clearer goal.",
            "target_column": target_column,
        }

    search_context = ""
    if skill_name == "alpha_engineering" and workspace.has("search_context"):
        try:
            sc = workspace.load_json("search_context")
            search_context = sc.get("summary", "") if isinstance(sc, dict) else str(sc)
        except Exception:  # noqa: BLE001
            pass

    raw_df = workspace.load_df("raw_data")
    data_columns = list(raw_df.columns)
    data_path = str(workspace.df_path("raw_data"))

    result = execute_feature_skill(
        plan,
        data_path=data_path,
        skill_name=skill_name,
        data_columns=data_columns,
        search_context=search_context,
        timeout_sec=timeout_sec,
        session_run_id=workspace.run_id,
    )

    if result.get("returncode") == 0 and result.get("output_path"):
        import numpy as np
        import pandas as pd

        enriched = pd.read_parquet(result["output_path"])

        if target_column not in enriched.columns:
            result["error"] = "missing_target_column"
            result["message"] = (
                f"Script ran but output lacks target column '{target_column}'. "
                f"Columns: {list(enriched.columns)[:20]}"
            )
            result["returncode"] = 1
            result["target_column"] = target_column
            return result

        planned_names = [f.get("name", "") for f in items if f.get("name")]
        missing = [c for c in planned_names if c not in enriched.columns]
        if missing:
            result["error"] = "missing_planned_columns"
            result["message"] = f"Engineered output is missing planned columns: {missing[:10]}"
            result["returncode"] = 1
            return result

        check_cols = [target_column, *[c for c in planned_names if c in enriched.columns]]
        for c in check_cols:
            enriched[c] = pd.to_numeric(enriched[c], errors="coerce")
        enriched.replace([np.inf, -np.inf], np.nan, inplace=True)

        pre_clean_rows = len(enriched)
        enriched.dropna(subset=check_cols, inplace=True)
        dropped = pre_clean_rows - len(enriched)

        min_rows = max(50, int(pre_clean_rows * 0.10))
        if len(enriched) < min_rows:
            result["error"] = "too_few_rows_after_cleanup"
            result["message"] = (
                f"Only {len(enriched)} rows remain after dropping {dropped} non-finite warmup rows "
                f"(minimum {min_rows}). The generated script likely has a bug beyond normal lookback NaNs."
            )
            result["returncode"] = 1
            return result

        remaining_nf = 0
        for c in check_cols:
            remaining_nf += int((~np.isfinite(enriched[c].to_numpy(dtype=np.float64, copy=False))).sum())
        if remaining_nf > 0:
            result["error"] = "non_finite_values_in_engineered_data"
            result["message"] = (
                f"Engineered output still has {remaining_nf} non-finite values after dropping "
                f"{dropped} warmup rows. This indicates a script bug."
            )
            result["returncode"] = 1
            return result

        if dropped > 0:
            result["warmup_rows_dropped"] = dropped

        desc = "Alpha-engineered dataset" if skill_name == "alpha_engineering" else "Feature-engineered dataset"
        workspace.save_df("engineered_data", enriched, description=desc)
        result["workspace_artifact"] = "engineered_data"
        result["engineered_shape"] = [enriched.shape[0], enriched.shape[1]]
        result["engineered_columns"] = list(enriched.columns)[:40]

    result["planned_features"] = [f.get("name", "") for f in items]
    result["target_column"] = target_column
    result["skill_mode"] = skill_name
    return result
