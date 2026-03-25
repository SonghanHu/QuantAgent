"""
Post-run Q&A: chat with an LLM grounded in workspace artifacts (report, evaluation, etc.).
"""

from __future__ import annotations

import json
import os
from typing import Any

from dotenv import load_dotenv
from openai import OpenAI

_CHAT_SYSTEM = """You are a senior quant research assistant. The user completed an automated research pipeline run. \
Below is CONTEXT extracted from that run's workspace (reports, JSON artifacts, and excerpts). \
Answer follow-up questions using only this context when possible. If something is not in the context, say so clearly \
and suggest what artifact to inspect or what to re-run. Be concise; use short bullets when helpful. \
Do not invent specific numbers, dates, or metrics that are not present in the context."""


def _openai_client() -> OpenAI:
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("OPENAI_API_KEY is not set.")
    base = os.environ.get("OPENAI_BASE_URL")
    kwargs: dict[str, Any] = {"api_key": key}
    if base:
        kwargs["base_url"] = base.rstrip("/")
    return OpenAI(**kwargs)


def _truncate(text: str, max_len: int) -> str:
    if len(text) <= max_len:
        return text
    return text[: max_len - 24] + "\n\n...[truncated]..."


def build_run_context_pack(ws: Any, *, goal: str | None = None) -> str:
    """Serialize key workspace artifacts into a single markdown-ish string for the system prompt."""
    parts: list[str] = []
    if goal and goal.strip():
        parts.append("## Original user goal\n\n" + goal.strip())

    parts.append("## Workspace\n\n" + ws.summary())
    arts = ws.list_artifacts()
    parts.append("## Artifact names\n\n" + json.dumps(sorted(arts.keys()), ensure_ascii=False, indent=2))

    json_specs: list[tuple[str, int, bool]] = [
        ("final_report", 14_000, False),
        ("evaluation", 8_000, False),
        ("feature_plan", 10_000, False),
        ("backtest_results", 10_000, True),
        ("model_output", 8_000, False),
        ("search_context", 5_000, False),
        ("debug_notes", 6_000, False),
    ]

    for name, max_chars, strip_equity in json_specs:
        if not ws.has(name):
            continue
        try:
            data = ws.load_json(name)
            if strip_equity and isinstance(data, dict) and "equity_curve" in data:
                data = {k: v for k, v in data.items() if k != "equity_curve"}
            blob = json.dumps(data, ensure_ascii=False, indent=2, default=str)
            parts.append(f"## {name} (JSON)\n\n{_truncate(blob, max_chars)}")
        except Exception:  # noqa: BLE001
            continue

    report_path = ws.root / "report.md"
    if report_path.is_file():
        try:
            md = report_path.read_text(encoding="utf-8")
            parts.append("## report.md (excerpt)\n\n" + _truncate(md, 10_000))
        except OSError:
            pass

    # Light tabular hints without dumping full OHLCV
    for df_name in ("engineered_data", "raw_data"):
        if not ws.has(df_name):
            continue
        try:
            df = ws.load_df(df_name)
            cols = [str(c) for c in df.columns[:120]]
            parts.append(
                f"## {df_name} (schema only)\n\n"
                f"shape: {df.shape[0]} × {df.shape[1]}\n\ncolumns (first 120): {cols!r}"
            )
        except Exception:  # noqa: BLE001
            continue

    return "\n\n---\n\n".join(parts)


def chat_with_run_context(
    *,
    context_pack: str,
    messages: list[dict[str, str]],
    model: str | None = None,
    client: OpenAI | None = None,
) -> str:
    """
    Stateless chat: ``messages`` should be the full user/assistant history (no system messages).
    """
    load_dotenv()
    m = model or os.environ.get("OPENAI_TASK_MODEL") or os.environ.get("OPENAI_SMALL_MODEL")
    if not m:
        raise RuntimeError("Set OPENAI_TASK_MODEL or OPENAI_SMALL_MODEL for post-run chat.")

    cli = client or _openai_client()
    api_messages: list[dict[str, str]] = [
        {"role": "system", "content": _CHAT_SYSTEM + "\n\n---\n\n# CONTEXT\n\n" + context_pack},
    ]
    for msg in messages:
        role = msg.get("role", "")
        content = (msg.get("content") or "").strip()
        if role not in ("user", "assistant") or not content:
            continue
        api_messages.append({"role": role, "content": content})

    if len(api_messages) < 2:
        raise ValueError("Need at least one user message with non-empty content.")

    completion = cli.chat.completions.create(
        model=m,
        messages=api_messages,
        temperature=0.35,
        max_tokens=2_048,
    )
    choice = completion.choices[0].message.content
    return (choice or "").strip()
