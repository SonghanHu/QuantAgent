"""Load price / OHLCV data: yfinance when ``tickers`` provided, else small demo stub."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pandas as pd
import yfinance as yf

from .data_spec import YFinanceFetchSpec

if TYPE_CHECKING:
    from agent.workspace import Workspace


def _stub(dataset: str) -> tuple[pd.DataFrame | None, dict[str, Any]]:
    return None, {
        "source": "stub",
        "rows": 1000,
        "columns": 20,
        "dataset": dataset,
    }


def _fetch_yfinance(spec: YFinanceFetchSpec) -> tuple[pd.DataFrame | None, dict[str, Any]]:
    kwargs: dict[str, Any] = {
        "tickers": spec.tickers,
        "interval": spec.interval,
        "auto_adjust": spec.auto_adjust,
        "prepost": spec.prepost,
        "actions": spec.actions,
        "progress": False,
        "threads": True,
    }
    if spec.start or spec.end:
        kwargs["start"] = spec.start
        kwargs["end"] = spec.end
    else:
        kwargs["period"] = spec.period or "1y"

    df = yf.download(**kwargs)
    if df is None or df.empty:
        return None, {
            "source": "yfinance",
            "error": "empty_frame",
            "tickers": spec.tickers,
            "rows": 0,
            "columns": [],
            "kwargs_used": {k: v for k, v in kwargs.items() if k != "progress"},
        }

    cols = [str(c) for c in df.columns]
    pv = df.head(5).reset_index()
    pv.columns = [str(c) for c in pv.columns]
    preview = pv.astype(object).where(pd.notnull(pv), None).to_dict(orient="records")
    meta = {
        "source": "yfinance",
        "tickers": spec.tickers,
        "rows": int(len(df)),
        "columns": cols,
        "start_ts": str(df.index.min()),
        "end_ts": str(df.index.max()),
        "interval": spec.interval,
        "period": spec.period,
        "start": spec.start,
        "end": spec.end,
        "preview_rows": preview,
        "rationale": spec.rationale,
    }
    return df, meta


def load_data(
    tickers: list[str] | str | None = None,
    period: str | None = "1y",
    start: str | None = None,
    end: str | None = None,
    interval: str = "1d",
    auto_adjust: bool = True,
    prepost: bool = False,
    actions: bool = False,
    dataset: str | None = None,
    rationale: str | None = None,
    workspace: Workspace | None = None,
) -> dict[str, Any]:
    """
    If ``tickers`` is set, download via yfinance using a **fixed** code path (safe).
    If omitted (or legacy ``dataset="demo"`` only), return a deterministic stub.

    When *workspace* is provided the DataFrame is persisted as ``raw_data.parquet``
    so downstream tools can access it via ``workspace.load_df("raw_data")``.
    """
    if dataset == "demo" and not tickers:
        _, meta = _stub("demo")
        return meta
    if tickers is None or tickers == "" or tickers == []:
        _, meta = _stub(dataset or "demo")
        return meta
    if isinstance(tickers, str) and not tickers.strip():
        _, meta = _stub(dataset or "demo")
        return meta

    spec = YFinanceFetchSpec(
        tickers=tickers,
        period=period,
        start=start,
        end=end,
        interval=interval,
        auto_adjust=auto_adjust,
        prepost=prepost,
        actions=actions,
        rationale=rationale,
    )
    df, meta = _fetch_yfinance(spec)

    if df is not None and workspace is not None:
        df = _flatten_columns(df)
        meta["columns"] = list(df.columns)
        path = workspace.save_df("raw_data", df, description=f"OHLCV from yfinance: {spec.tickers}")
        meta["workspace_artifact"] = "raw_data"
        meta["workspace_path"] = str(path)

    return meta


def _flatten_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Flatten yfinance MultiIndex columns into simple strings."""
    if not isinstance(df.columns, pd.MultiIndex):
        return df
    levels = df.columns.nlevels
    if levels == 2:
        unique_l1 = df.columns.get_level_values(1).unique()
        if len(unique_l1) == 1:
            df.columns = df.columns.get_level_values(0)
        else:
            df.columns = [f"{a}_{b}" for a, b in df.columns]
    else:
        df.columns = ["_".join(str(x) for x in col).strip("_") for col in df.columns]
    return df
