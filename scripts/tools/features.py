"""Feature engineering: read FeaturePlan from workspace, generate & run a script via skill."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from agent.workspace import Workspace

_VALID_COL_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_ ]*$")
_DEFAULT_TARGET = "target"


def _sanitize_target_column(raw: Any) -> str:
    """
    Return a usable target column name from the feature plan.

    Rejects obviously invalid values (long sentences, empty, non-ASCII names
    that the data analyst sometimes produces when it cannot decide).
    """
    s = str(raw).strip() if raw else ""
    if not s or len(s) > 60 or not _VALID_COL_RE.match(s):
        return _DEFAULT_TARGET
    return s


def build_features(
    workspace: Workspace | None = None,
    timeout_sec: int = 120,
) -> dict[str, Any]:
    """
    Build feature columns by executing the ``feature_engineering`` skill.

    Reads ``feature_plan`` and ``raw_data`` from workspace, generates a Python
    script that implements the plan, runs it, and saves the enriched DataFrame
    back as ``engineered_data`` in the workspace.

    Validates that:
    - The feature plan has a sane ``target_column`` name.
    - The output parquet actually contains that target.
    """
    if workspace is None:
        return {"error": "no_workspace", "message": "build_features requires a workspace with raw_data and feature_plan."}

    if not workspace.has("raw_data"):
        return {"error": "no_raw_data", "message": "Workspace has no raw_data artifact. Run load_data first."}

    if not workspace.has("feature_plan"):
        return {"error": "no_feature_plan", "message": "Workspace has no feature_plan. Run run_data_analyst first."}

    from agent.feature_skill import execute_feature_skill

    plan = workspace.load_json("feature_plan")
    raw_df = workspace.load_df("raw_data")
    data_columns = list(raw_df.columns)

    target_column = _sanitize_target_column(plan.get("target_column"))
    plan["target_column"] = target_column

    features = plan.get("features") or []
    if not features:
        return {
            "error": "empty_feature_plan",
            "message": (
                "feature_plan.features is empty — the data analyst did not propose any features. "
                "Re-run run_data_analyst with a clearer goal or richer data."
            ),
            "target_column": target_column,
        }

    data_path = str(workspace.df_path("raw_data"))

    result = execute_feature_skill(
        plan,
        data_path=data_path,
        data_columns=data_columns,
        timeout_sec=timeout_sec,
        session_run_id=workspace.run_id,
    )

    if result.get("returncode") == 0 and result.get("output_path"):
        import pandas as pd
        import numpy as np

        enriched = pd.read_parquet(result["output_path"])

        if target_column not in enriched.columns:
            result["error"] = "missing_target_column"
            result["message"] = (
                f"Feature script ran but output does not contain required target column "
                f"'{target_column}'. Columns produced: {list(enriched.columns)[:20]}"
            )
            result["returncode"] = 1
            result["target_column"] = target_column
            return result

        # Hard training-usability validation: fail fast if non-finite values leak into engineered_data.
        # This prevents downstream model training / backtests from either crashing or silently producing nonsense.
        planned_feature_names = [f["name"] for f in features if f.get("name")]
        missing_features = [c for c in planned_feature_names if c not in enriched.columns]
        if missing_features:
            result["error"] = "missing_planned_feature_columns"
            result["message"] = f"Engineered output is missing planned feature columns: {missing_features[:10]}"
            result["returncode"] = 1
            return result

        target_ser = pd.to_numeric(enriched[target_column], errors="coerce")
        target_non_finite = int((~np.isfinite(target_ser.to_numpy(dtype=np.float64, copy=False))).sum())

        feature_non_finite = 0
        for c in planned_feature_names:
            s = pd.to_numeric(enriched[c], errors="coerce")
            feature_non_finite += int((~np.isfinite(s.to_numpy(dtype=np.float64, copy=False))).sum())

        if target_non_finite > 0 or feature_non_finite > 0:
            result["error"] = "non_finite_values_in_engineered_data"
            result["message"] = (
                "Feature-engineered output contains non-finite values after the cleanup step. "
                f"target_non_finite={target_non_finite}, feature_non_finite_total={feature_non_finite}"
            )
            result["returncode"] = 1
            result["target_non_finite"] = target_non_finite
            result["feature_non_finite_total"] = feature_non_finite
            return result

        workspace.save_df("engineered_data", enriched, description="Feature-engineered dataset")
        result["workspace_artifact"] = "engineered_data"
        result["engineered_shape"] = [enriched.shape[0], enriched.shape[1]]
        result["engineered_columns"] = list(enriched.columns)[:30]

    planned_feature_names = [f["name"] for f in features]
    result["planned_features"] = planned_feature_names
    result["target_column"] = target_column
    return result
