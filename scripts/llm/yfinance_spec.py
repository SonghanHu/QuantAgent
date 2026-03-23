"""
Use OPENAI_SMALL_MODEL + ``docs/yfinance_guide.md`` to emit a structured yfinance spec.

The model does **not** write executable code; it fills ``YFinanceFetchSpec`` fields only.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, cast

from dotenv import load_dotenv
from openai import OpenAI

# ``python scripts/llm/yfinance_spec.py`` → ensure ``scripts/`` on path
_SCRIPTS_ROOT = Path(__file__).resolve().parent.parent
if str(_SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_ROOT))

from tools.data_spec import YFinanceFetchSpec


def _guide_text(*, max_chars: int = 14_000) -> str:
    path = _SCRIPTS_ROOT / "docs" / "yfinance_guide.md"
    text = path.read_text(encoding="utf-8") if path.is_file() else ""
    if max_chars > 0 and len(text) > max_chars:
        return text[:max_chars] + "\n\n[... truncated ...]\n"
    return text


def _client() -> OpenAI:
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("OPENAI_API_KEY is not set.")
    base = os.environ.get("OPENAI_BASE_URL")
    kwargs: dict[str, Any] = {"api_key": key}
    if base:
        kwargs["base_url"] = base.rstrip("/")
    return OpenAI(**kwargs)


def infer_yfinance_spec(
    user_instruction: str,
    *,
    model: str | None = None,
    client: OpenAI | None = None,
    max_guide_chars: int = 14_000,
) -> YFinanceFetchSpec:
    """
    Read the yfinance guide + user intent → validated ``YFinanceFetchSpec``.

    Typical flow: ``spec = infer_yfinance_spec(...)`` then ``load_data(**spec.model_dump(exclude_none=True))``.
    """
    load_dotenv()
    m = model or os.environ.get("OPENAI_SMALL_MODEL")
    if not m:
        raise RuntimeError("OPENAI_SMALL_MODEL is not set.")

    guide = _guide_text(max_chars=max_guide_chars)
    system = (
        "You output ONLY a structured YFinanceFetchSpec. "
        "Choose tickers, period OR start/end, and interval from the guide. "
        "Use Yahoo Finance symbols. Set rationale briefly. "
        "Do not invent APIs outside yfinance.download parameters described."
    )
    user = (
        "## yfinance guide\n\n"
        f"{guide}\n\n"
        "## User data request\n\n"
        f"{user_instruction.strip()}\n"
    )
    cli = client or _client()
    completion = cli.chat.completions.parse(
        model=m,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        response_format=YFinanceFetchSpec,
    )
    parsed = completion.choices[0].message.parsed
    if parsed is None:
        raise RuntimeError("Model returned no structured output for YFinanceFetchSpec.")
    return cast(YFinanceFetchSpec, parsed)


def main() -> int:
    import argparse

    load_dotenv()
    model = os.environ.get("OPENAI_SMALL_MODEL")
    if not model:
        print("Missing OPENAI_SMALL_MODEL", file=sys.stderr)
        return 1

    p = argparse.ArgumentParser(description="Infer YFinanceFetchSpec from NL + yfinance guide")
    p.add_argument("instruction", nargs="*", help="What data to download")
    args = p.parse_args()
    text = " ".join(args.instruction).strip()
    if not text:
        p.print_help()
        return 1
    spec = infer_yfinance_spec(text, model=model)
    print(spec.model_dump_json(indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
