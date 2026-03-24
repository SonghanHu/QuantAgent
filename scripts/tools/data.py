"""Load price / OHLCV data: yfinance when ``tickers`` provided, else small demo stub."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pandas as pd
import yfinance as yf

from .data_spec import YFinanceFetchSpec

if TYPE_CHECKING:
    from agent.workspace import Workspace

# Yahoo often has no series for common shorthand symbols; map to symbols that return bars.
_YAHOO_TICKER_ALIASES: dict[str, str] = {
    "DXY": "DX-Y.NYB",
    "USDX": "DX-Y.NYB",
    "USDOLLAR": "DX-Y.NYB",
    "XAUUSD": "GC=F",
    "GOLD": "GC=F",
}


def _resolve_yahoo_symbol(ticker: str) -> str:
    t = ticker.strip()
    return _YAHOO_TICKER_ALIASES.get(t.upper(), t)


def _ordered_unique(symbols: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for s in symbols:
        if s not in seen:
            seen.add(s)
            out.append(s)
    return out


def _first_requested_per_yahoo(
    pairs: list[tuple[str, str]],
) -> tuple[dict[str, str], list[str]]:
    yahoo_to_requested: dict[str, str] = {}
    warnings: list[str] = []
    for req, yh in pairs:
        if yh not in yahoo_to_requested:
            yahoo_to_requested[yh] = req
        elif yahoo_to_requested[yh] != req:
            warnings.append(
                f"Both {yahoo_to_requested[yh]!r} and {req!r} resolve to Yahoo {yh!r}; "
                f"columns use suffix {yahoo_to_requested[yh]!r}."
            )
    return yahoo_to_requested, warnings


def _rename_column_suffixes_to_requested(
    df: pd.DataFrame, yahoo_to_requested: dict[str, str]
) -> pd.DataFrame:
    rename_map: dict[str, str] = {}
    for col in df.columns:
        parts = str(col).rsplit("_", 1)
        if len(parts) != 2:
            rename_map[col] = col
            continue
        base, yh = parts[0], parts[1]
        req = yahoo_to_requested.get(yh)
        if req is not None and req != yh:
            rename_map[col] = f"{base}_{req}"
        else:
            rename_map[col] = col
    return df.rename(columns=rename_map)


def _backfill_adj_from_close(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    for c in list(out.columns):
        if not str(c).startswith("Adj Close_"):
            continue
        suf = str(c)[len("Adj Close_") :]
        cl = f"Close_{suf}"
        if cl not in out.columns:
            continue
        if out[c].notna().any():
            continue
        if out[cl].notna().any():
            out[c] = out[cl]
    return out


def _ensure_adj_close_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Multi-ticker ``auto_adjust`` frames may omit Adj Close; mirror Close per ticker suffix."""
    out = df.copy()
    suffixes: set[str] = set()
    for c in out.columns:
        cs = str(c)
        if cs.startswith("Close_"):
            suffixes.add(cs[len("Close_") :])
    for suf in suffixes:
        ac, cl = f"Adj Close_{suf}", f"Close_{suf}"
        if ac not in out.columns and cl in out.columns:
            out[ac] = out[cl]
    return out


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

    spec_in = YFinanceFetchSpec(
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
    requested_list = list(spec_in.tickers)
    pairs = [(r, _resolve_yahoo_symbol(r)) for r in requested_list]
    resolved_unique = _ordered_unique([yh for _, yh in pairs])
    yahoo_to_req, alias_warnings = _first_requested_per_yahoo(pairs)
    spec = spec_in.model_copy(update={"tickers": resolved_unique})

    df, meta = _fetch_yfinance(spec)

    meta["tickers"] = requested_list
    meta["yahoo_download_tickers"] = resolved_unique
    aliases_applied = [{"requested": a, "yahoo": b} for a, b in pairs if a != b]
    if aliases_applied:
        meta["yahoo_ticker_aliases_applied"] = aliases_applied
    if alias_warnings:
        meta["ticker_alias_warnings"] = alias_warnings

    if df is not None:
        df = _flatten_columns(df)
        df = _rename_column_suffixes_to_requested(df, yahoo_to_req)
        df = _ensure_adj_close_columns(df)
        df = _backfill_adj_from_close(df)
        meta["columns"] = list(df.columns)
        meta["rows"] = int(len(df))
        meta["start_ts"] = str(df.index.min())
        meta["end_ts"] = str(df.index.max())
        pv = df.head(5).reset_index()
        pv.columns = [str(c) for c in pv.columns]
        meta["preview_rows"] = pv.astype(object).where(pd.notnull(pv), None).to_dict(orient="records")

    if df is not None and workspace is not None:
        path = workspace.save_df(
            "raw_data",
            df,
            description=f"OHLCV from yfinance: {requested_list}",
        )
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
