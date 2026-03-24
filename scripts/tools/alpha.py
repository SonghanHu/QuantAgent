"""Alpha engineering: WorldQuant-style alpha factor construction via skill."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from agent.workspace import Workspace

_VALID_COL_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_ ]*$")


def _sanitize_target(raw: Any) -> str:
    s = str(raw).strip() if raw else ""
    if not s or len(s) > 60 or not _VALID_COL_RE.match(s):
        return "target"
    return s


def build_alphas(
    workspace: Workspace | None = None,
    timeout_sec: int = 150,
) -> dict[str, Any]:
    """
    Construct WorldQuant-style alpha factors using the ``alpha_engineering`` skill.

    Reads ``feature_plan`` (or ``alpha_plan``) and ``raw_data`` from workspace,
    generates a Python script that implements alpha expressions, and saves the
    enriched DataFrame as ``engineered_data`` in the workspace.

    Also picks up ``search_context`` from workspace if available (from web_search tool).
    """
    if workspace is None:
        return {"error": "no_workspace", "message": "build_alphas requires a workspace."}

    if not workspace.has("raw_data"):
        return {"error": "no_raw_data", "message": "Workspace has no raw_data. Run load_data first."}

    plan_key = "alpha_plan" if workspace.has("alpha_plan") else "feature_plan"
    if not workspace.has(plan_key):
        return {"error": "no_plan", "message": "No feature_plan or alpha_plan in workspace. Run run_data_analyst first."}

    from agent.alpha_skill import execute_alpha_skill

    plan = workspace.load_json(plan_key)
    target_column = _sanitize_target(plan.get("target_column"))
    plan["target_column"] = target_column

    alphas = plan.get("alphas") or plan.get("features") or []
    if not alphas:
        return {
            "error": "empty_alpha_plan",
            "message": "Alpha/feature plan has no entries. Re-run data analyst with a clearer goal.",
            "target_column": target_column,
        }

    search_context = ""
    if workspace.has("search_context"):
        try:
            sc = workspace.load_json("search_context")
            search_context = sc.get("summary", "") if isinstance(sc, dict) else str(sc)
        except Exception:  # noqa: BLE001
            pass

    data_path = str(workspace.df_path("raw_data"))

    result = execute_alpha_skill(
        plan,
        data_path=data_path,
        search_context=search_context,
        timeout_sec=timeout_sec,
    )

    if result.get("returncode") == 0 and result.get("output_path"):
        import pandas as pd

        enriched = pd.read_parquet(result["output_path"])

        if target_column not in enriched.columns:
            result["error"] = "missing_target_column"
            result["message"] = (
                f"Alpha script ran but output lacks target column '{target_column}'. "
                f"Columns: {list(enriched.columns)[:20]}"
            )
            result["returncode"] = 1
            result["target_column"] = target_column
            return result

        workspace.save_df("engineered_data", enriched, description="Alpha-engineered dataset")
        result["workspace_artifact"] = "engineered_data"
        result["engineered_shape"] = [enriched.shape[0], enriched.shape[1]]
        result["engineered_columns"] = list(enriched.columns)[:40]

    alpha_names = [a.get("name", "") for a in alphas]
    result["planned_alphas"] = alpha_names
    result["target_column"] = target_column
    return result
