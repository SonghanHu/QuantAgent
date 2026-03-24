"""
Pre-execution clarification dialog: LLM asks the user clarifying questions
to ensure it fully understands the research goal before decomposing tasks.

Used by both CLI (``workflow_demo.py``) and the API server.
"""

from __future__ import annotations

import os
from typing import Any, cast

from dotenv import load_dotenv
from openai import OpenAI
from pydantic import BaseModel, ConfigDict, Field


class ClarificationResult(BaseModel):
    """Structured output from the clarification LLM."""

    model_config = ConfigDict(extra="forbid")

    understood: bool = Field(
        description="True if the goal is clear enough to proceed without questions"
    )
    refined_goal: str = Field(
        description="The original goal rewritten with all clarified details incorporated"
    )
    questions: list[str] = Field(
        default_factory=list,
        description="1-4 clarifying questions if understood=False; empty if understood=True",
    )
    assumptions: list[str] = Field(
        default_factory=list,
        description="Key assumptions the system is making about the user's intent",
    )
    summary: str = Field(
        default="",
        description="Brief summary of what the system plans to do",
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


_SYSTEM = """\
You are a senior quant research assistant. The user is about to launch an automated pipeline that can:
1. Download market data (stocks, ETFs, futures via yfinance)
2. Run exploratory data analysis
3. Engineer features or WorldQuant-style alpha factors
4. Train regression models (ridge, lasso, RF, GBM, etc.)
5. Backtest trading strategies
6. Evaluate performance
7. Search the web for research context

Your job is to **understand the user's goal completely** before execution starts.

If the goal is clear and specific enough, set understood=True, write a refined_goal that fills in reasonable defaults, and list your assumptions.

If the goal is ambiguous or missing critical details, set understood=False and ask 1-4 targeted questions about:
- **Data**: Which tickers/assets? What time period? What frequency?
- **Target**: What are we predicting? (next-day return, weekly return, classification?)
- **Strategy**: Long-only vs long-short? Rebalance frequency? Transaction cost assumptions?
- **Model**: Any model preferences? Hyperparameter tuning?
- **Evaluation**: What metrics matter most? (Sharpe, drawdown, hit rate?)

Keep questions concise and offer sensible defaults in parentheses so the user can just confirm.\
"""


def clarify_goal(
    goal: str,
    conversation: list[dict[str, str]] | None = None,
    *,
    model: str | None = None,
    client: OpenAI | None = None,
) -> ClarificationResult:
    """
    Analyze the user's goal and either confirm understanding or ask questions.

    ``conversation`` is the ongoing dialog history (list of {role, content} dicts).
    On first call, pass None or empty; on follow-ups, include prior exchanges.
    """
    load_dotenv()
    m = model or os.environ.get("OPENAI_SMALL_MODEL")
    if not m:
        raise RuntimeError("OPENAI_SMALL_MODEL is not set.")

    cli = client or _openai_client()

    messages: list[dict[str, str]] = [{"role": "system", "content": _SYSTEM}]

    if conversation:
        messages.extend(conversation)
    else:
        messages.append({"role": "user", "content": goal})

    resp = cli.chat.completions.parse(
        model=m,
        messages=messages,
        response_format=ClarificationResult,
    )
    parsed = resp.choices[0].message.parsed
    if parsed is None:
        return ClarificationResult(
            understood=True,
            refined_goal=goal,
            assumptions=["Could not parse clarification response; proceeding with original goal."],
            summary=goal,
        )
    return cast(ClarificationResult, parsed)


def run_interactive_clarification(
    goal: str,
    *,
    model: str | None = None,
    max_rounds: int = 3,
) -> str:
    """
    CLI-mode interactive clarification loop.

    Returns the refined goal string ready for decomposition.
    """
    conversation: list[dict[str, str]] = [{"role": "user", "content": goal}]

    for _round in range(max_rounds):
        result = clarify_goal(goal, conversation, model=model)

        if result.understood:
            print(f"\n{'='*60}")
            print("Goal understood. Here's the plan:")
            print(f"  {result.summary}")
            if result.assumptions:
                print("\nAssumptions:")
                for a in result.assumptions:
                    print(f"  • {a}")
            print(f"\nRefined goal:\n  {result.refined_goal}")
            print(f"{'='*60}\n")

            confirm = input("Proceed? [Y/n/edit] ").strip().lower()
            if confirm in ("", "y", "yes"):
                return result.refined_goal
            if confirm in ("n", "no"):
                edit = input("What would you like to change? ").strip()
                conversation.append({"role": "assistant", "content": result.summary})
                conversation.append({"role": "user", "content": edit})
                continue
            conversation.append({"role": "assistant", "content": result.summary})
            conversation.append({"role": "user", "content": confirm})
            continue

        print(f"\nI have a few questions before starting:\n")
        for i, q in enumerate(result.questions, 1):
            print(f"  {i}. {q}")
        print()

        answers = input("Your answers (or 'skip' to use defaults): ").strip()
        if answers.lower() in ("skip", ""):
            conversation.append({
                "role": "assistant",
                "content": "Questions: " + " | ".join(result.questions),
            })
            conversation.append({
                "role": "user",
                "content": "Use reasonable defaults for all questions.",
            })
        else:
            conversation.append({
                "role": "assistant",
                "content": "Questions: " + " | ".join(result.questions),
            })
            conversation.append({"role": "user", "content": answers})

    final = clarify_goal(goal, conversation, model=model)
    return final.refined_goal
