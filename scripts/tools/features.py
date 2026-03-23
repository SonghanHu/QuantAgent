"""Feature engineering: read FeaturePlan from workspace, generate & run a script via skill."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from agent.workspace import Workspace


def build_features(
    workspace: Workspace | None = None,
    timeout_sec: int = 120,
) -> dict[str, Any]:
    """
    Build feature columns by executing the ``feature_engineering`` skill.

    Reads ``feature_plan`` and ``raw_data`` from workspace, generates a Python
    script that implements the plan, runs it, and saves the enriched DataFrame
    back as ``engineered_data`` in the workspace.

    Falls back to the FeaturePlan's feature names if the script fails.
    """
    if workspace is None:
        return {"error": "no_workspace", "message": "build_features requires a workspace with raw_data and feature_plan."}

    if not workspace.has("raw_data"):
        return {"error": "no_raw_data", "message": "Workspace has no raw_data artifact. Run load_data first."}

    if not workspace.has("feature_plan"):
        return {"error": "no_feature_plan", "message": "Workspace has no feature_plan. Run run_data_analyst first."}

    from agent.feature_skill import execute_feature_skill

    plan = workspace.load_json("feature_plan")
    data_path = str(workspace.df_path("raw_data"))

    result = execute_feature_skill(
        plan,
        data_path=data_path,
        timeout_sec=timeout_sec,
    )

    if result.get("returncode") == 0 and result.get("output_path"):
        import pandas as pd

        enriched = pd.read_parquet(result["output_path"])
        workspace.save_df("engineered_data", enriched, description="Feature-engineered dataset")
        result["workspace_artifact"] = "engineered_data"
        result["engineered_shape"] = [enriched.shape[0], enriched.shape[1]]
        result["engineered_columns"] = list(enriched.columns)[:30]

    features = [f["name"] for f in plan.get("features", [])]
    result["planned_features"] = features
    result["target_column"] = plan.get("target_column", "target")
    return result
