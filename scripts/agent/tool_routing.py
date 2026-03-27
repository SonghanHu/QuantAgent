"""
Route a subtask to a registry tool using OPENAI_SMALL_MODEL (structured output).

Falls back to keyword heuristics when LLM is disabled, misconfigured, or invalid after retries.
"""

from __future__ import annotations

import inspect
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, cast

from dotenv import load_dotenv
from openai import OpenAI
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from tools import TOOL_REGISTRY

from .models import Subtask
from .subtask_heuristic import subtask_to_tool_name


class SubtaskToolChoice(BaseModel):
    """Model output: exactly one tool + optional arguments (object, not a string of JSON)."""

    model_config = ConfigDict(extra="forbid")

    tool_name: str = Field(description="Must be one of the allowed registry names.")
    kwargs: dict[str, Any] = Field(
        default_factory=dict,
        description="Arguments for that tool as a JSON object. Use {} if none. "
        "Keep string values short or escape quotes; invalid JSON breaks routing.",
    )


@dataclass(frozen=True)
class ResolvedTool:
    tool_name: str
    kwargs: dict[str, Any]
    source: Literal["explicit", "llm", "heuristic"]


def _explicit_tool_name_from_title(title: str) -> str | None:
    """Honor an exact registry tool name when the planner already wrote it into the title."""
    text = (title or "").strip()
    if not text:
        return None
    for name in sorted(TOOL_REGISTRY, key=len, reverse=True):
        if re.search(rf"(?<![A-Za-z0-9_]){re.escape(name)}(?![A-Za-z0-9_])", text):
            return name
    return None


def _scripts_root() -> Path:
    """Directory ``scripts/`` (parent of ``agent/``)."""
    return Path(__file__).resolve().parent.parent


def read_tools_catalog(*, max_chars: int = 6000) -> str:
    """Load ``docs/tools.md`` (truncated) for the router prompt."""
    path = _scripts_root() / "docs" / "tools.md"
    text = path.read_text(encoding="utf-8") if path.is_file() else ""
    if max_chars > 0 and len(text) > max_chars:
        return text[:max_chars] + "\n\n[... catalog truncated ...]\n"
    return text


def _openai_client() -> OpenAI:
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("OPENAI_API_KEY is not set.")
    base = os.environ.get("OPENAI_BASE_URL")
    kwargs: dict[str, Any] = {"api_key": key}
    if base:
        kwargs["base_url"] = base.rstrip("/")
    return OpenAI(**kwargs)


def filter_kwargs_for_tool(tool_name: str, kwargs: dict[str, Any]) -> dict[str, Any]:
    """Drop keys the target callable does not accept (prevents TypeError)."""
    fn = TOOL_REGISTRY[tool_name]
    sig = inspect.signature(fn)
    allowed = set(sig.parameters)
    runtime_injected = {"workspace", "event_callback"}
    return {k: v for k, v in kwargs.items() if k in allowed and k not in runtime_injected}


def resolve_subtask_tool(
    subtask: Subtask,
    *,
    use_llm: bool = True,
    client: OpenAI | None = None,
    model: str | None = None,
    max_catalog_chars: int = 6000,
    max_retries: int = 2,
) -> ResolvedTool:
    """
    Pick ``tool_name`` and ``kwargs`` via small model + catalog, else keyword fallback.

    ``max_retries`` counts LLM calls (each call gets a fresh parse); on repeated invalid
    ``tool_name``, the prompt is nudged with the allowed list before falling back.
    """
    valid = sorted(TOOL_REGISTRY)
    explicit_name = _explicit_tool_name_from_title(subtask.title)
    if explicit_name is not None:
        return ResolvedTool(explicit_name, {}, "explicit")

    if not use_llm:
        name = subtask_to_tool_name(subtask)
        return ResolvedTool(name, {}, "heuristic")

    load_dotenv()
    m = model or os.environ.get("OPENAI_SMALL_MODEL")
    if not m:
        name = subtask_to_tool_name(subtask)
        return ResolvedTool(name, {}, "heuristic")

    try:
        cli = client or _openai_client()
    except RuntimeError:
        name = subtask_to_tool_name(subtask)
        return ResolvedTool(name, {}, "heuristic")

    catalog = read_tools_catalog(max_chars=max_catalog_chars)
    allowed_line = ", ".join(valid)
    system = (
        "You route a single research subtask to exactly one tool from the allowed list. "
        "Return tool_name and a kwargs object (not a stringified JSON blob). "
        "kwargs must match that tool's parameters; use {} if no arguments. "
        f"Allowed tool_name values: {allowed_line}. "
        "Special rule: if subtask text contains `Requested model: <...>`, and the chosen tool is `train_model`, "
        "set `requested_model_name` to the same <...> text."
    )
    user = (
        "## Tool catalog (reference)\n\n"
        f"{catalog}\n\n"
        "## Subtask\n\n"
        f"title: {subtask.title}\n"
        f"description: {subtask.description}\n"
    )
    messages: list[dict[str, str]] = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]

    for _ in range(max_retries):
        try:
            completion = cli.chat.completions.parse(
                model=m,
                messages=cast(Any, messages),
                response_format=SubtaskToolChoice,
            )
            parsed = completion.choices[0].message.parsed
        except ValidationError as exc:
            messages.append(
                {
                    "role": "user",
                    "content": (
                        "Structured output failed validation. Respond again with valid JSON matching the schema: "
                        "tool_name from the allowed list, kwargs as a JSON object (use {} if none). "
                        f"Error (truncated): {str(exc)[:600]}"
                    ),
                }
            )
            continue
        except Exception as exc:  # noqa: BLE001 — SDK may wrap parse/HTTP errors
            messages.append(
                {
                    "role": "user",
                    "content": (
                        "Could not parse structured tool choice. Retry: tool_name from the allowed list, "
                        "kwargs as a plain object only. "
                        f"Error (truncated): {str(exc)[:600]}"
                    ),
                }
            )
            continue

        if parsed is None:
            messages.append(
                {
                    "role": "user",
                    "content": "You returned no structured output. Respond again with a valid tool_name.",
                }
            )
            continue

        if parsed.tool_name in TOOL_REGISTRY:
            raw_kw = dict(parsed.kwargs) if isinstance(parsed.kwargs, dict) else {}
            clean = filter_kwargs_for_tool(parsed.tool_name, cast(dict[str, Any], raw_kw))
            return ResolvedTool(parsed.tool_name, clean, "llm")

        messages.append(
            {
                "role": "user",
                "content": (
                    f"tool_name {parsed.tool_name!r} is not allowed. "
                    f"Pick exactly one of: {allowed_line}. "
                    "Return the same JSON schema again."
                ),
            }
        )

    name = subtask_to_tool_name(subtask)
    return ResolvedTool(name, {}, "heuristic")
