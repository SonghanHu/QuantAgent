"""Run skill-guided data analysis: LLM writes a script, we execute it under ``data/analysis_runs/``."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from agent.workspace import Workspace


def run_data_analysis(
    instruction: str,
    data_path: str | None = None,
    skill_name: str = "data_analysis",
    timeout_sec: int = 120,
    workspace: Workspace | None = None,
) -> dict[str, Any]:
    """
    Use ``skills/<skill_name>.md`` + ``instruction`` so the model emits Python, then run it.

    When *workspace* has a ``raw_data`` artifact and no explicit ``data_path`` is given,
    the parquet path is resolved automatically.
    """
    if data_path is None and workspace is not None and workspace.has("raw_data"):
        data_path = str(workspace.df_path("raw_data"))

    from agent.analysis_skill import execute_analysis_skill

    return execute_analysis_skill(
        instruction,
        data_path=data_path,
        skill_name=skill_name,
        timeout_sec=timeout_sec,
    )
