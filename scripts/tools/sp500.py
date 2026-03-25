"""Current S&P 500 constituents from a public CSV (no historical membership)."""

from __future__ import annotations

import io
import ssl
from typing import TYPE_CHECKING, Any
from urllib.request import Request, urlopen

import pandas as pd

if TYPE_CHECKING:
    from agent.workspace import Workspace

SP500_CSV = (
    "https://raw.githubusercontent.com/datasets/s-and-p-500-companies/main/data/constituents.csv"
)


def _ssl_context() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    try:
        import certifi

        ctx.load_verify_locations(certifi.where())
    except ImportError:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    return ctx


def fetch_sp500_tickers(timeout: int = 60) -> list[str]:
    """Current S&P 500 symbols (no historical membership; survivorship bias)."""
    req = Request(SP500_CSV, headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(req, timeout=timeout, context=_ssl_context()) as resp:
        buf = resp.read()
    df = pd.read_csv(io.BytesIO(buf))
    sym = df["Symbol"].astype(str).str.replace(".", "-", regex=False).str.strip()
    return sorted(sym.unique().tolist())


def fetch_sp500_tickers_tool(
    timeout: int = 60,
    workspace: Workspace | None = None,
) -> dict[str, Any]:
    """
    Agent tool: download constituents CSV and return sorted Yahoo-style symbols.

    Optionally saves ``sp500_tickers`` JSON to the workspace for downstream steps.
    """
    try:
        tickers = fetch_sp500_tickers(timeout=timeout)
    except Exception as exc:  # noqa: BLE001
        return {"error": "fetch_failed", "message": str(exc), "source_url": SP500_CSV}

    out: dict[str, Any] = {
        "tickers": tickers,
        "n": len(tickers),
        "source_url": SP500_CSV,
        "notes": "Current membership only; no historical index changes (survivorship bias if used for backtests).",
    }
    if workspace is not None:
        workspace.save_json(
            "sp500_tickers",
            {"tickers": tickers, "n": len(tickers), "source_url": SP500_CSV},
            description="S&P 500 symbol list (current constituents)",
        )
        out["workspace_artifact"] = "sp500_tickers"
    return out
