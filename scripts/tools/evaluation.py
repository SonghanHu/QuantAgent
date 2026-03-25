"""Strategy evaluation: LLM reads backtest + model output and produces a structured verdict."""

from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING, Any, Literal, cast

from dotenv import load_dotenv
from openai import OpenAI
from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from agent.workspace import Workspace


class StrategyVerdict(BaseModel):
    """Structured evaluation output from the LLM."""

    model_config = ConfigDict(extra="forbid")

    overall_rating: Literal["strong", "promising", "weak", "failed"] = Field(
        description="High-level quality rating"
    )
    summary: str = Field(description="2-3 sentence executive summary")
    strengths: list[str] = Field(default_factory=list, description="What works well")
    weaknesses: list[str] = Field(default_factory=list, description="Concerns or risks")
    risk_assessment: str = Field(default="", description="Comment on drawdown, tail risk, regime sensitivity")
    next_steps: list[str] = Field(
        default_factory=list,
        description="Concrete suggestions: alternative models, features, data, or parameters to try",
    )
    deploy_ready: bool = Field(
        default=False,
        description="True only if metrics are strong AND risks are acceptable",
    )


def _openai_client() -> OpenAI:
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("OPENAI_API_KEY is not set.")
    base = os.environ.get("OPENAI_BASE_URL")
    kwargs: dict[str, Any] = {"api_key": key}
    if base:
        kwargs["base_url"] = base.rstrip("/")
    return OpenAI(**kwargs)


def evaluate_strategy(
    workspace: Workspace | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    """
    Evaluate strategy quality by having an LLM review backtest and model outputs.

    Reads ``backtest_results`` and ``model_output`` from workspace, produces a
    structured ``StrategyVerdict`` with rating, strengths/weaknesses, and next steps.
    Falls back to a minimal verdict if workspace artifacts are missing.
    """
    load_dotenv()
    m = model or os.environ.get("OPENAI_SMALL_MODEL")
    if not m:
        raise RuntimeError("OPENAI_SMALL_MODEL is not set.")

    backtest_results: dict[str, Any] | None = None
    model_output: dict[str, Any] | None = None
    feature_plan: dict[str, Any] | None = None

    if workspace is not None:
        if workspace.has("backtest_results"):
            backtest_results = workspace.load_json("backtest_results")
        if workspace.has("model_output"):
            model_output = workspace.load_json("model_output")
        if workspace.has("feature_plan"):
            feature_plan = workspace.load_json("feature_plan")

    if backtest_results is None and model_output is None:
        return {
            "verdict": "incomplete",
            "summary": "No backtest or model output available for evaluation.",
            "next_steps": ["Run run_backtest first, and add train_model only if the strategy is predictive/ML-based."],
        }

    context_parts: list[str] = []
    if model_output:
        trimmed = {k: v for k, v in model_output.items() if k != "equity_curve"}
        context_parts.append(
            "## Model training output\n\n"
            + json.dumps(trimmed, indent=2, ensure_ascii=False, default=str)[:4000]
        )
    if backtest_results:
        bt = {k: v for k, v in backtest_results.items() if k != "equity_curve"}
        context_parts.append(
            "## Backtest results\n\n"
            + json.dumps(bt, indent=2, ensure_ascii=False, default=str)[:4000]
        )
    if feature_plan:
        context_parts.append(
            "## Feature plan\n\n"
            + json.dumps(feature_plan, indent=2, ensure_ascii=False, default=str)[:2000]
        )

    workspace_summary = ""
    if workspace is not None:
        workspace_summary = f"\n\n## Workspace\n\n{workspace.summary()}"

    system = (
        "You are a senior quant researcher evaluating a trading strategy. "
        "Given backtest results and optional model training metrics, produce a structured verdict. "
        "Be specific and actionable. Reference actual numbers from the results. "
        "Consider: Sharpe ratio quality (>1 good, >2 excellent), drawdown severity, "
        "turnover/cost impact, and regime robustness. "
        "If model training metrics are present, also consider overfitting risk (train vs test R²). "
        "If no model output is present, treat this as a rule-based strategy review rather than an incomplete run."
    )
    user = "\n\n".join(context_parts) + workspace_summary

    cli = _openai_client()
    completion = cli.chat.completions.parse(
        model=m,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        response_format=StrategyVerdict,
    )
    parsed = completion.choices[0].message.parsed
    if parsed is None:
        return {"verdict": "error", "summary": "LLM returned no structured response."}
    verdict = cast(StrategyVerdict, parsed)

    result = json.loads(verdict.model_dump_json())

    if workspace is not None:
        workspace.save_json(
            "evaluation",
            result,
            description="Strategy evaluation verdict from LLM reviewer",
        )
        result["workspace_artifact"] = "evaluation"

    result["verdict"] = verdict.overall_rating
    return result
