"""
Decompose a natural-language task into structured subtasks via OpenAI.

Requires in `.env`:
  OPENAI_API_KEY
  OPENAI_SMALL_MODEL   (e.g. gpt-5.4-nano or gpt-4o-mini)

Optional:
  OPENAI_BASE_URL
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any

# Running as ``python scripts/llm/task_decompose.py`` puts ``llm/`` on sys.path; ensure ``scripts/`` is too.
_SCRIPTS_ROOT = Path(__file__).resolve().parent.parent
if str(_SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_ROOT))

from dotenv import load_dotenv
from openai import OpenAI

from agent.models import TaskBreakdown


def _client() -> OpenAI:
    load_dotenv()
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        print("Missing OPENAI_API_KEY in environment or `.env`.", file=sys.stderr)
        sys.exit(1)
    base = os.environ.get("OPENAI_BASE_URL")
    kwargs: dict[str, Any] = {"api_key": key}
    if base:
        kwargs["base_url"] = base.rstrip("/")
    return OpenAI(**kwargs)


def decompose_task(task_text: str, *, model: str) -> TaskBreakdown:
    client = _client()
    system = (
        "You decompose a user's research goal into **4–8 subtasks** that map to the "
        "available tool pipeline. Each subtask executes exactly one tool.\n\n"
        "## Available tools (in typical pipeline order)\n\n"
        "1. `web_search` — search the web for research context (alpha ideas, market regime, factor definitions)\n"
        "2. `run_data_loader` — iterative download sub-agent (propose yfinance params → load → judge) → saves raw_data\n"
        "3. `run_data_analyst` — iterative EDA sub-agent → produces a feature plan\n"
        "4. `build_features` — execute the feature plan to create engineered columns + target\n"
        "5. `build_alphas` — WorldQuant-style alpha factor construction (alternative to build_features for quant alpha research)\n"
        "6. `train_model` — fit a regression model (ridge, lasso, RF, GBM, etc.)\n"
        "7. `run_backtest` — skill-driven backtest with configurable hyperparameters\n"
        "8. `evaluate_strategy` — LLM-driven evaluation of backtest + model results\n"
        "9. `run_debug_agent` — diagnose tool/traceback failures from workspace + error context (optional; use when debugging or recovery)\n\n"
        "`run_data_analysis` (single-shot EDA) can replace `run_data_analyst` for simpler goals.\n"
        "Use `build_alphas` instead of `build_features` when the goal involves alpha research, "
        "formulaic alphas, or WorldQuant-style factor construction.\n"
        "Use `web_search` early in the pipeline when the goal involves novel research, "
        "unfamiliar alpha ideas, or market context.\n"
        "When tickers, index membership, sector lists, or data vendors are unspecified, add **`web_search`** "
        "before `run_data_loader` to pin down symbols and realistic data assumptions.\n"
        "`load_data` exists for direct one-shot downloads only; prefer `run_data_loader` in the main pipeline.\n\n"
        "## Rules\n\n"
        "- Output **4 to 8** subtasks. Never exceed 8.\n"
        "- Each subtask title should clearly indicate which tool it uses.\n"
        "- Dependencies form a DAG: search → load → analyst → features/alphas → train → backtest → evaluate.\n"
        "- Do NOT create separate subtasks for things the tool handles internally "
        "(e.g. `run_data_analyst` already does cleaning, EDA, and feature planning).\n"
        "- If the user's goal only covers part of the pipeline (e.g. just analysis), "
        "only include the relevant steps.\n"
        "- Do not add `run_debug_agent` unless the user asks for debugging/diagnosis or recovery from errors.\n"
    )
    user = f"Task to decompose:\n\n{task_text.strip()}"

    completion = client.chat.completions.parse(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        response_format=TaskBreakdown,
    )
    parsed = completion.choices[0].message.parsed
    if parsed is None:
        raise RuntimeError("Model returned no structured output.")
    return parsed


def main() -> int:
    load_dotenv()
    model = os.environ.get("OPENAI_SMALL_MODEL")
    if not model:
        print("Missing OPENAI_SMALL_MODEL in environment or `.env`.", file=sys.stderr)
        sys.exit(1)

    p = argparse.ArgumentParser(description="Decompose a task using OPENAI_SMALL_MODEL.")
    p.add_argument(
        "task",
        nargs="*",
        help="Task in natural language (pass as one quoted string or multiple words)",
    )
    args = p.parse_args()
    text = " ".join(args.task).strip()
    if not text and not sys.stdin.isatty():
        text = sys.stdin.read().strip()
    if not text:
        p.print_help()
        print("\nError: provide a task as arguments or pipe text on stdin.", file=sys.stderr)
        return 1

    breakdown = decompose_task(text, model=model)
    print(breakdown.model_dump_json(indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
