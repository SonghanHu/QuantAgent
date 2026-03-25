"""
Sub-agent: propose yfinance params → load → judge until data fits the goal or max rounds.

Prompts stay short; the model decides tickers, horizon, and when the panel is good enough.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, cast

from dotenv import load_dotenv
from openai import OpenAI
from pydantic import BaseModel, ConfigDict, Field

from tools.data_spec import YFinanceFetchSpec


class DataLoaderJudgeDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ready: bool = Field(description="True when this dataset supports the stated research goal")
    next_focus: str = Field(
        default="",
        description="If not ready: what to change next (symbols, range, interval). Empty if ready.",
    )
    reasoning: str = Field(default="", description="Brief justification")


@dataclass
class LoaderRound:
    round_num: int
    spec: dict[str, Any]
    load_meta: dict[str, Any]
    judge: DataLoaderJudgeDecision | None = None


@dataclass
class DataLoaderResult:
    rounds: list[LoaderRound] = field(default_factory=list)
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


def _search_context_snippet(load_json: Callable[[str], Any], max_chars: int = 3500) -> str:
    try:
        data = load_json("search_context")
        s = json.dumps(data, ensure_ascii=False, default=str)
        return s[:max_chars] + ("\n\n[truncated]" if len(s) > max_chars else "")
    except Exception:  # noqa: BLE001
        return ""


def _compact_load_meta(meta: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "source",
        "rows",
        "columns",
        "error",
        "tickers",
        "yahoo_download_tickers",
        "yahoo_ticker_aliases_applied",
        "start_ts",
        "end_ts",
        "interval",
        "period",
        "start",
        "end",
        "workspace_artifact",
        "workspace_path",
        "kwargs_used",
    )
    return {k: meta[k] for k in keys if k in meta}


def _workspace_save_summary(meta: dict[str, Any]) -> dict[str, Any]:
    path_raw = meta.get("workspace_path")
    if not path_raw:
        return {}
    path = Path(str(path_raw))
    return {
        "workspace_artifact": meta.get("workspace_artifact"),
        "workspace_path": str(path),
        "workspace_filename": path.name,
        "workspace_file_exists": path.exists(),
    }


def _history_digest(rounds: list[LoaderRound], *, max_chars: int = 5000) -> str:
    lines: list[str] = []
    for r in rounds:
        lines.append(f"### Round {r.round_num}")
        lines.append(json.dumps({"spec": r.spec, "load": _compact_load_meta(r.load_meta)}, default=str)[:2000])
        if r.judge:
            lines.append(
                f"judge: ready={r.judge.ready}, next_focus={r.judge.next_focus[:200]!r}, "
                f"reasoning={r.judge.reasoning[:300]!r}"
            )
        lines.append("")
    text = "\n".join(lines)
    return text[-max_chars:] if len(text) > max_chars else text


def _ohlcv_column_stats(df: Any) -> dict[str, Any]:
    """Non-null stats for OHLCV + adj close (bare names or ``Open_TICKER`` panel style)."""
    import pandas as pd

    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return {}
    n = len(df)
    cols: list[Any] = []
    for c in df.columns:
        cs = str(c)
        if cs in ("Open", "High", "Low", "Close", "Adj Close", "Volume"):
            cols.append(c)
        elif cs.startswith(
            ("Open_", "High_", "Low_", "Close_", "Adj Close_", "Volume_")
        ):
            cols.append(c)
    out: dict[str, Any] = {}
    for c in cols[:80]:
        s = df[c]
        nn = int(s.notna().sum()) if hasattr(s, "notna") else 0
        out[str(c)] = {"non_null": nn, "non_null_pct": round(100.0 * nn / max(n, 1), 2)}
    return {
        "shape": [n, len(df.columns)],
        # Full OHLCV (+ volume) so judges can confirm MACD / indicator readiness, not only Close.
        "column_coverage": out,
        # Backward-compatible alias (older prompts refer to "price_columns")
        "price_columns": {k: v for k, v in out.items() if "Close" in k or k in ("Close", "Adj Close")},
    }


def run_data_loader(
    goal: str,
    *,
    workspace: Any,
    model: str | None = None,
    client: OpenAI | None = None,
    max_rounds: int = 4,
    event_callback: Callable[[dict[str, Any]], None] | None = None,
) -> DataLoaderResult:
    """
    Loop: LLM proposes ``YFinanceFetchSpec`` → ``load_data`` → LLM judges coverage vs goal.
    """
    load_dotenv()
    m = model or os.environ.get("OPENAI_SMALL_MODEL")
    if not m:
        raise RuntimeError("OPENAI_SMALL_MODEL is not set.")
    cli = client or _openai_client()
    result = DataLoaderResult()

    from tools.data import load_data as _load_data

    search_extra = ""
    if workspace is not None and workspace.has("search_context"):
        search_extra = _search_context_snippet(workspace.load_json)

    hint = ""

    for round_num in range(1, max_rounds + 1):
        is_final = round_num == max_rounds
        history = _history_digest(result.rounds)

        propose_system = (
            "You output a YFinanceFetchSpec: Yahoo symbols, period or start/end, interval, rationale. "
            "Align the download with the research goal. No prose outside the structured object."
        )
        propose_user_parts = [f"## Goal\n\n{goal.strip()}"]
        if search_extra.strip():
            propose_user_parts.append(f"## Prior web search (optional)\n\n{search_extra}")
        if history.strip():
            propose_user_parts.append(f"## Previous attempts\n\n{history}")
        if hint.strip():
            propose_user_parts.append(f"## Judge hint for this round\n\n{hint.strip()}")
        propose_user = "\n\n".join(propose_user_parts)

        if event_callback is not None:
            event_callback(
                {
                    "type": "data_loader_round",
                    "stage": "spec_propose",
                    "round": round_num,
                }
            )

        spec_resp = cli.chat.completions.parse(
            model=m,
            messages=[
                {"role": "system", "content": propose_system},
                {"role": "user", "content": propose_user},
            ],
            response_format=YFinanceFetchSpec,
        )
        spec_parsed = spec_resp.choices[0].message.parsed
        if spec_parsed is None:
            result.stopped_reason = "error"
            return result
        spec = cast(YFinanceFetchSpec, spec_parsed)
        spec_dict = json.loads(spec.model_dump_json())

        if workspace is not None:
            workspace.discard("raw_data")

        load_meta = _load_data(
            **spec.model_dump(mode="python", exclude_none=True),
            workspace=workspace,
        )
        lr = LoaderRound(round_num=round_num, spec=spec_dict, load_meta=dict(load_meta))

        if event_callback is not None:
            event_callback(
                {
                    "type": "data_loader_round",
                    "stage": "load_done",
                    "round": round_num,
                    "rows": load_meta.get("rows"),
                    "tickers": load_meta.get("tickers"),
                    "error": load_meta.get("error"),
                }
            )

        dq: dict[str, Any] = {}
        if workspace is not None and workspace.has("raw_data"):
            try:
                dq = _ohlcv_column_stats(workspace.load_df("raw_data"))
            except Exception:  # noqa: BLE001
                dq = {}

        judge_system = (
            "You review whether the latest Yahoo Finance download is adequate for the research goal. "
            "Output a structured decision only.\n"
            "- ready=true: required assets and history exist with usable OHLCV (and Adj Close / Volume when needed) "
            "— use the JSON field `column_coverage` for per-column non-null counts (not only `price_columns`).\n"
            "- ready=false: say what is wrong and set next_focus so the next download can fix it.\n"
        )
        if is_final:
            judge_system += (
                f"\nFinal round ({round_num}/{max_rounds}). If the data still cannot support the goal, "
                "set ready=false; there is no further download round after this."
            )

        judge_user = (
            f"## Goal\n\n{goal.strip()}\n\n"
            f"## Round {round_num} / {max_rounds}\n\n"
            f"### Spec used\n\n{json.dumps(spec_dict, indent=2, ensure_ascii=False)}\n\n"
            f"### Load result (summary)\n\n{json.dumps(_compact_load_meta(load_meta), indent=2, ensure_ascii=False)}\n\n"
        )
        save_summary = _workspace_save_summary(load_meta)
        if save_summary:
            judge_user += f"### Workspace save confirmation\n\n{json.dumps(save_summary, indent=2, ensure_ascii=False)}\n\n"
        if dq:
            judge_user += f"### OHLCV / volume / close column coverage\n\n{json.dumps(dq, indent=2, ensure_ascii=False)[:6000]}\n"

        judge_resp = cli.chat.completions.parse(
            model=m,
            messages=[
                {"role": "system", "content": judge_system},
                {"role": "user", "content": judge_user},
            ],
            response_format=DataLoaderJudgeDecision,
        )
        decision = cast(DataLoaderJudgeDecision, judge_resp.choices[0].message.parsed)
        lr.judge = decision
        result.rounds.append(lr)

        if event_callback is not None:
            event_callback(
                {
                    "type": "data_loader_round",
                    "stage": "judge_done",
                    "round": round_num,
                    "ready": decision.ready,
                    "reasoning": decision.reasoning,
                    "next_focus": decision.next_focus,
                }
            )

        if decision.ready:
            result.stopped_reason = "ready"
            return result

        hint = decision.next_focus or "Adjust tickers or date range; ensure every asset in the goal has non-null prices."

    result.stopped_reason = "max_rounds"
    if workspace is not None and result.rounds:
        lj = result.rounds[-1].judge
        if lj is not None and not lj.ready:
            workspace.discard("raw_data")
    return result
