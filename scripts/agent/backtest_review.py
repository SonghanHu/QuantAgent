"""
Backtest code review agent: static check of generated script against skill rules before execution.
"""

from __future__ import annotations

import os
from typing import Any, Literal, cast

from dotenv import load_dotenv
from openai import OpenAI
from pydantic import BaseModel, ConfigDict, Field


def _json_dumps(obj: Any) -> str:
    import json

    return json.dumps(obj, ensure_ascii=False, indent=2, default=str)


class BacktestCodeReview(BaseModel):
    """Structured verdict from the review model."""

    model_config = ConfigDict(extra="forbid")

    approved: bool = Field(
        description="True only if the script is safe to run: respects skill rules, likely no look-ahead, NA-safe."
    )
    severity: Literal["pass", "minor", "major"] = Field(
        default="major",
        description="pass if approved; major if blocking issues.",
    )
    issues: list[str] = Field(
        default_factory=list,
        description="Concrete problems (max ~8 short bullets). Empty if approved.",
    )
    revision_instructions: str = Field(
        default="",
        description="What the generator must change next turn; imperative, concise.",
    )


_REVIEWER_SYSTEM = """You are a senior quant engineering reviewer. You ONLY review Python backtest code \
(the body that will be appended after a fixed injected preamble defining DATA_PATH, OUTPUT_JSON, config, get_rebalance_freq).

Your job: reject unsafe or spec-violating code before it runs.

Checklist (must enforce):
1. **Imports:** only pandas, numpy, json, pathlib, sys, warnings, sklearn (if model_based), matplotlib — no subprocess, socket, requests, urllib, os.system, pickle.loads.
2. **No look-ahead:** positions for bar t must come from information at t-1 or last rebalance; strategy returns use lagged weights × returns.
3. **Config:** must use injected `_CFG` / `config` for strategy_type, rebalance_freq, transaction_cost_bps, train_ratio, etc. Rebalance cadence in code must match config.
4. **pandas NA:** boolean masks must be NA-safe (.fillna(False), no `if series:` on possibly-NA Series); no ambiguous boolean NA in filters.
5. **Output:** must write valid JSON to OUTPUT_JSON with metrics fields per skill (sharpe, equity_curve, etc.); on failure write {"error": "..."}.
6. **Nested functions:** must not rely on bare `effective_rebalance` inside nested defs without global — prefer get_rebalance_freq().
7. **Rule_based:** do not use target column as raw tradable weights if it is a label; prefer rebuilding positions from signals with shift(1) where appropriate.
8. **Strategy fidelity:** `position_sizing` in code must match BACKTEST_CONFIG (e.g. no replacing equal_weight with signal_proportional). No extra ranking/filter layers unless clearly required by context.
9. **Transaction costs:** if `transaction_cost_bps` is 0, code must not charge costs; if > 0, must apply that value only — no hidden extra bps.
10. **Execution timing:** close-based signal on day t → portfolio return on t+1 (one explicit lag); flag double-lag on weights and returns.
11. **Rebalance:** weekly/monthly must ffill weights between rebalances; daily updates targets for next bar. Reject tautological rebalance masks (e.g. always-True OR of a mask with its negation).
12. **Self-check:** before approve, confirm (a) strategy matches config/user intent, (b) costs match config, (c) lag OK, (d) turnover from held weights, (e) survivorship/universe limitations mentioned in notes if relevant.
13. **Signal mapping explicit (model_based long/flat):** OUTPUT_JSON must include `signal_mapping` with at least `prediction_target_horizon`, `signal_rule`, `execution`, exposure stats (`avg_gross_exposure`, `percent_days_invested`), and `win_rate_definition` so long/flat conversion and win-rate denominator are auditable.

If you are unsure but see no clear violation, set approved=true and mention minor risks in issues (severity minor).
If there is any likely look-ahead, wrong import, or missing OUTPUT_JSON handling, approved=false (severity major).
"""


def _openai_client() -> OpenAI:
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("OPENAI_API_KEY is not set.")
    base = os.environ.get("OPENAI_BASE_URL")
    kwargs: dict[str, Any] = {"api_key": key}
    if base:
        kwargs["base_url"] = base.rstrip("/")
    return OpenAI(**kwargs)


def _truncate(s: str, max_len: int) -> str:
    s = s.strip()
    if len(s) <= max_len:
        return s
    return s[: max_len - 24] + "\n\n...[truncated]...\n\n" + s[-8_000:]


def review_backtest_script(
    *,
    script_body: str,
    backtest_config: dict[str, Any],
    backtest_mode: str,
    skill_markdown: str,
    model: str | None = None,
    client: OpenAI | None = None,
) -> BacktestCodeReview:
    """
    Call a small LLM to review the generated script body (without injected preamble).

    ``skill_markdown`` should be the backtest skill text (can be truncated by caller).
    """
    load_dotenv()
    m = (
        model
        or os.environ.get("OPENAI_REVIEW_MODEL")
        or os.environ.get("OPENAI_SMALL_MODEL")
    )
    if not m:
        raise RuntimeError("Set OPENAI_SMALL_MODEL or OPENAI_REVIEW_MODEL for backtest code review.")

    cli = client or _openai_client()
    cfg = _truncate(_json_dumps(backtest_config), 4_000)
    skill = _truncate(skill_markdown, 10_000)
    code = _truncate(script_body, 28_000)

    user = (
        f"## BACKTEST_MODE\n\n{backtest_mode}\n\n"
        f"## BACKTEST_CONFIG_JSON (excerpt)\n\n```json\n{cfg}\n```\n\n"
        f"## Skill (excerpt)\n\n{skill}\n\n"
        f"## Script body to review (no preamble)\n\n```python\n{code}\n```\n\n"
        "Respond with structured fields only. If not approved, revision_instructions must tell the coder exactly what to change."
    )

    completion = cli.chat.completions.parse(
        model=m,
        messages=[
            {"role": "system", "content": _REVIEWER_SYSTEM},
            {"role": "user", "content": user},
        ],
        response_format=BacktestCodeReview,
    )
    parsed = completion.choices[0].message.parsed
    if parsed is None:
        return BacktestCodeReview(
            approved=True,
            severity="minor",
            issues=["Reviewer returned no structured output; proceeding without block."],
            revision_instructions="",
        )
    return cast(BacktestCodeReview, parsed)


def format_review_feedback(review: BacktestCodeReview) -> str:
    """User-message block appended for regeneration."""
    lines = [
        "### Backtest code review — revision required",
        "",
        f"- **approved:** {review.approved}",
        f"- **severity:** {review.severity}",
        "",
    ]
    if review.issues:
        lines.append("**Issues:**")
        for i, x in enumerate(review.issues, 1):
            lines.append(f"{i}. {x}")
        lines.append("")
    if review.revision_instructions.strip():
        lines.append("**Instructions for the next script:**")
        lines.append(review.revision_instructions.strip())
        lines.append("")
    lines.append("Regenerate the full script body only; keep allowed imports and respect the injected preamble variables.")
    return "\n".join(lines)
