"""
Sub-agent: iterative data analysis → feature engineering plan.

Loop:
  1. run_data_analysis (skill-driven script)
  2. LLM judges: enough insight for feature engineering?
     - NO  → refine instruction, loop back to 1
     - YES → emit FeaturePlan (structured output)

Stops when the model says "ready" or ``max_rounds`` is hit.
"""

from __future__ import annotations

import json
import os
import uuid
from collections.abc import Callable
from pathlib import Path
from dataclasses import dataclass, field
from typing import Any, Literal, cast

from dotenv import load_dotenv
from openai import OpenAI
from pydantic import BaseModel, ConfigDict, Field

from .analysis_skill import execute_analysis_skill


class FeatureSpec(BaseModel):
    name: str = Field(description="Column name to create")
    logic: str = Field(description="Plain-English formula or pandas pseudo-code")
    rationale: str = Field(description="Why this feature helps the target")


class FeaturePlan(BaseModel):
    """Final output: what features to build and why."""

    model_config = ConfigDict(extra="forbid")

    ready: bool = Field(description="True when analysis is sufficient")
    features: list[FeatureSpec] = Field(default_factory=list)
    target_column: str = Field(default="target", description="Column to predict")
    notes: str | None = None


class JudgeDecision(BaseModel):
    """After each analysis round: continue or produce features."""

    model_config = ConfigDict(extra="forbid")

    ready: bool = Field(description="True = enough insight; False = need another round")
    next_instruction: str = Field(
        default="",
        description="If not ready: what to investigate next. If ready: leave empty.",
    )
    reasoning: str = Field(default="", description="Brief justification")


@dataclass
class AnalysisRound:
    round_num: int
    instruction: str
    result: dict[str, Any]
    judge: JudgeDecision | None = None


@dataclass
class DataAnalystResult:
    rounds: list[AnalysisRound] = field(default_factory=list)
    feature_plan: FeaturePlan | None = None
    stopped_reason: Literal["ready", "max_rounds", "error"] = "max_rounds"


def _openai_client() -> OpenAI:
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("OPENAI_API_KEY is not set.")
    base = os.environ.get("OPENAI_BASE_URL")
    kwargs: dict[str, Any] = {"api_key": key}
    if base:
        kwargs["base_url"] = base.rstrip("/")
    return OpenAI(**kwargs)


def _summarize_result(result: dict[str, Any], *, max_stdout: int = 3000) -> str:
    """Compact text version of an analysis run for the judge prompt."""
    parts: list[str] = []
    s = result.get("summary")
    if s:
        parts.append("## summary.json\n" + json.dumps(s, indent=2, ensure_ascii=False, default=str)[:4000])
    out = result.get("stdout", "")
    if out:
        parts.append("## stdout (tail)\n" + out[-max_stdout:])
    err = result.get("stderr", "")
    if err:
        parts.append("## stderr (tail)\n" + err[-1500:])
    parts.append(f"returncode={result.get('returncode')}")
    return "\n\n".join(parts)


_REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def _revision_context_from_previous(prev: AnalysisRound) -> str:
    """Prior script + errors so the next LLM call can revise instead of starting cold."""
    parts: list[str] = []
    r = prev.result
    sp = r.get("script_path")
    if isinstance(sp, str) and sp.strip():
        try:
            path = _REPO_ROOT / sp
            if path.is_file():
                text = path.read_text(encoding="utf-8")
                if len(text) > 7_000:
                    text = text[:3_500] + "\n\n...[truncated]...\n\n" + text[-3_000:]
                parts.append("### Prior script (on disk, including injected preamble)\n\n```python\n" + text + "\n```")
        except OSError:
            pass
    rc = r.get("returncode")
    parts.append(f"### Prior run\n\nreturncode={rc}")
    err = r.get("stderr") or ""
    if err:
        parts.append("### stderr (tail)\n\n```\n" + str(err)[-2_500:] + "\n```")
    if rc not in (0, None):
        out = r.get("stdout") or ""
        if out:
            parts.append("### stdout (tail)\n\n```\n" + str(out)[-1_500:] + "\n```")
    parts.append(f"### Prior instruction\n\n{prev.instruction[:2_000]}")
    return "\n\n".join(parts)


def _history_digest(rounds: list[AnalysisRound], *, max_chars: int = 6000) -> str:
    """Compressed earlier rounds so the judge has context without blowing token budget."""
    lines: list[str] = []
    for r in rounds:
        lines.append(f"### Round {r.round_num}: {r.instruction[:120]}")
        s = r.result.get("summary")
        if isinstance(s, dict):
            lines.append(json.dumps({k: v for k, v in s.items() if k in ("shape", "columns", "missing_pct", "notes", "error")}, ensure_ascii=False, default=str)[:1200])
        if r.judge:
            lines.append(f"  judge: ready={r.judge.ready}, reasoning={r.judge.reasoning[:200]}")
        lines.append("")
    text = "\n".join(lines)
    if len(text) > max_chars:
        return text[-max_chars:]
    return text


def run_data_analyst(
    goal: str,
    *,
    data_path: str | None = None,
    initial_instruction: str | None = None,
    model: str | None = None,
    client: OpenAI | None = None,
    max_rounds: int = 4,
    timeout_sec: int = 120,
    event_callback: Callable[[dict[str, Any]], None] | None = None,
    session_run_id: str | None = None,
    workspace: Any | None = None,
) -> DataAnalystResult:
    """
    Iterative sub-agent: analyze data until the model is confident enough to propose features.

    Returns ``DataAnalystResult`` with all rounds, the final ``FeaturePlan``, and stop reason.
    """
    load_dotenv()
    m = model or os.environ.get("OPENAI_SMALL_MODEL")
    if not m:
        raise RuntimeError("OPENAI_SMALL_MODEL is not set.")
    code_model = os.environ.get("OPENAI_TASK_MODEL") or m
    cli = client or _openai_client()
    result = DataAnalystResult()

    instruction = initial_instruction or (
        "First pass: report shape, dtypes, missing %, numeric describe, "
        "and correlations with likely target columns. "
        "Flag any data quality issues."
    )
    analysis_session_id = (session_run_id or "").strip()[:12] or uuid.uuid4().hex[:12]

    for round_num in range(1, max_rounds + 1):
        print(f"  [data_analyst] round {round_num}: {instruction[:80]}...")
        if event_callback is not None:
            event_callback(
                {
                    "stage": "analysis_start",
                    "round": round_num,
                    "instruction": instruction,
                }
            )

        revision_context: str | None = None
        if result.rounds:
            revision_context = _revision_context_from_previous(result.rounds[-1])

        analysis = execute_analysis_skill(
            instruction,
            data_path=data_path,
            model=code_model,
            client=cli,
            timeout_sec=timeout_sec,
            session_run_id=analysis_session_id,
            revision_context=revision_context,
            workspace=workspace,
        )
        ar = AnalysisRound(round_num=round_num, instruction=instruction, result=analysis)

        if analysis.get("returncode") != 0:
            ar.judge = JudgeDecision(
                ready=False,
                next_instruction="Previous script failed; simplify and retry.",
                reasoning=f"returncode={analysis.get('returncode')}",
            )
            result.rounds.append(ar)
            if event_callback is not None:
                event_callback(
                    {
                        "stage": "analysis_failed",
                        "round": round_num,
                        "instruction": instruction,
                        "returncode": analysis.get("returncode"),
                        "stderr": analysis.get("stderr"),
                    }
                )
            instruction = ar.judge.next_instruction
            continue

        history = _history_digest(result.rounds)
        current = _summarize_result(analysis)

        is_final_round = round_num == max_rounds
        judge_system = (
            "You are a quant research reviewer for an automated pipeline. "
            "Your job is to decide if there is ENOUGH insight to hand off to a feature-engineering step, "
            "not to demand exhaustive analysis.\n\n"
            "Set ready=true when ALL of these hold:\n"
            "- The latest analysis script succeeded (non-empty summary or stdout with shape/columns/dtypes or key stats).\n"
            "- You understand what the rows represent (e.g. time series, cross-section) and what columns exist.\n"
            "- The data schema can support the **research goal** (e.g. multi-stock sector rotation needs a panel with "
            "ticker/security id + date + sector and usually market cap; a single-name OHLCV series cannot support that).\n"
            "- There is no blocking gap: if the goal requires columns or structure that analysis proves are missing, "
            "that is NOT ready — the pipeline must reload data first.\n\n"
            "Set ready=true on early rounds if EDA is already adequate for the goal and schema.\n\n"
            "Set ready=false when the output is empty, failed, or a specific data/schema gap must be fixed "
            "(give ONE focused next_instruction: what to load or which columns are required).\n\n"
        )
        if is_final_round:
            judge_system += (
                f"**This is round {round_num} of {max_rounds} (FINAL).** There is no next analysis round. "
                "If the goal requires data you do not have (e.g. GICS sector, multi-ticker panel, market cap) "
                "and the current output confirms they are missing, you MUST set ready=false and set next_instruction "
                "to a concrete reload recipe (e.g. pass many tickers to load_data, or use an external fundamentals source). "
                "Only set ready=true if feature engineering can realistically run on this dataframe as-is.\n\n"
                "Do not set ready=true just because the script succeeded."
            )
        else:
            judge_system += (
                f"You are on analysis round {round_num} of {max_rounds}. "
                "If the next round is the last, still be strict about schema fit to the goal."
            )
        judge_user = (
            f"## Research goal\n\n{goal}\n\n"
            + (f"## Earlier rounds\n\n{history}\n\n" if history.strip() else "")
            + f"## Current round {round_num} / {max_rounds}\n\n{current}\n"
        )
        judge_resp = cli.chat.completions.parse(
            model=m,
            messages=[
                {"role": "system", "content": judge_system},
                {"role": "user", "content": judge_user},
            ],
            response_format=JudgeDecision,
        )
        decision = cast(JudgeDecision, judge_resp.choices[0].message.parsed)
        ar.judge = decision
        result.rounds.append(ar)
        print(f"  [data_analyst] judge: ready={decision.ready}, reasoning={decision.reasoning[:100]}")
        if event_callback is not None:
            event_callback(
                {
                    "stage": "judge_done",
                    "round": round_num,
                    "instruction": instruction,
                    "ready": decision.ready,
                    "reasoning": decision.reasoning,
                    "next_instruction": decision.next_instruction,
                }
            )

        if decision.ready:
            plan = _generate_feature_plan(goal, result.rounds, data_path=data_path, model=m, client=cli)
            result.feature_plan = plan
            result.stopped_reason = "ready"
            return result

        if is_final_round:
            plan = _generate_feature_plan(goal, result.rounds, data_path=data_path, model=m, client=cli)
            result.feature_plan = plan
            result.stopped_reason = "max_rounds"
            return result

        instruction = decision.next_instruction or "Dig deeper into the data."

    if result.feature_plan is None:
        plan = _generate_feature_plan(goal, result.rounds, data_path=data_path, model=m, client=cli)
        result.feature_plan = plan
    result.stopped_reason = "max_rounds"
    return result


def _generate_feature_plan(
    goal: str,
    rounds: list[AnalysisRound],
    *,
    data_path: str | None,
    model: str,
    client: OpenAI,
) -> FeaturePlan:
    history = _history_digest(rounds, max_chars=8000)
    system = (
        "Based on the data analysis rounds, propose concrete features for modeling. "
        "Each feature needs a name, logic (pandas pseudo-code), and rationale. "
        "Also specify which column is the target (short ASCII identifier).\n\n"
        "If the history shows the data **cannot** support the goal (wrong granularity, single ticker when a panel is "
        "needed, missing sector/ticker/date identifiers, etc.), set ready=false, leave features empty, "
        "and put actionable reload instructions in notes (what to fetch, which columns must exist)."
    )
    user = (
        f"## Goal\n\n{goal}\n\n"
        f"## Data path\n\n{data_path or 'synthetic'}\n\n"
        f"## Analysis history\n\n{history}\n"
    )
    resp = client.chat.completions.parse(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        response_format=FeaturePlan,
    )
    parsed = resp.choices[0].message.parsed
    if parsed is None:
        return FeaturePlan(ready=False, features=[], notes="Model returned no plan.")
    return cast(FeaturePlan, parsed)
