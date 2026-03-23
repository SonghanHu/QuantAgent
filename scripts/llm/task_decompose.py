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
        "You break down user tasks into clear, ordered subtasks for execution. "
        "Each subtask has a numeric id (1-based), title, short description, "
        "and optional dependency ids (other subtasks that must finish first). "
        "Keep subtasks concrete and verifiable."
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
