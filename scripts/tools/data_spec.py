"""Structured parameters for yfinance downloads (LLM fills this; executor runs one code path)."""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, Field, field_validator


class YFinanceFetchSpec(BaseModel):
    """
    What to download via yfinance. Keep fields aligned with ``yf.download`` / ``Ticker.history``.

    The LLM should set this from the task + ``docs/yfinance_guide.md`` — not write arbitrary code.
    """

    tickers: list[str] = Field(
        min_length=1,
        description="Yahoo Finance symbols, e.g. SPY, AAPL, GC=F, ES=F.",
    )
    period: str | None = Field(
        None,
        description="Shortcut range if start/end omitted: 1d,5d,1mo,3mo,6mo,1y,2y,5y,10y,ytd,max",
    )
    start: str | None = Field(None, description="YYYY-MM-DD inclusive")
    end: str | None = Field(None, description="YYYY-MM-DD exclusive where applicable")
    interval: str = Field(
        "1d",
        description="1m,2m,5m,15m,30m,60m,90m,1h,1d,5d,1wk,1mo,3mo",
    )
    auto_adjust: bool = Field(True, description="Adjust OHLC for splits/dividends where supported")
    prepost: bool = Field(False, description="Include pre/post market (intraday)")
    actions: bool = Field(False, description="Include Dividends, Stock Splits columns when True")
    rationale: str | None = Field(None, description="Short note for logs only")

    @field_validator("tickers", mode="before")
    @classmethod
    def _coerce_tickers(cls, v: Any) -> list[str]:
        if v is None:
            raise ValueError("tickers is required (list or comma-separated string)")
        if isinstance(v, str):
            parts = re.split(r"[,;\s]+", v.strip())
            return [p for p in (x.strip() for x in parts) if p]
        if isinstance(v, list):
            return [str(x).strip() for x in v if str(x).strip()]
        raise TypeError("tickers must be str or list")

    @field_validator("period")
    @classmethod
    def _period_lower(cls, v: str | None) -> str | None:
        return v.lower().strip() if v else None

    @field_validator("interval")
    @classmethod
    def _interval_lower(cls, v: str) -> str:
        return v.lower().strip()
