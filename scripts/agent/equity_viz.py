"""
Build equity curve visualization artifacts from ``backtest_results`` (post-backtest / end of run).

Writes:

- ``equity_viz.json`` — dates, equity series, normalized trade markers for the dashboard.
- ``equity_chart.png`` — static overview plot (matplotlib).

Trade markers come from optional ``trade_events`` / ``equity_dates`` on ``backtest_results``; dates are
otherwise interpolated between ``test_start`` and ``test_end``.
"""

from __future__ import annotations

import io
import json
from typing import Any

import pandas as pd

from agent.workspace import Workspace


def _is_placeholder_date_series(dates: list[str]) -> bool:
    """Reject obviously bogus date labels such as repeated Unix epoch placeholders."""
    cleaned = [str(d)[:10] for d in dates if str(d).strip()]
    if not cleaned:
        return True
    unique = set(cleaned)
    if len(unique) == 1 and next(iter(unique)) == "1970-01-01":
        return True
    if len(unique) == 1 and len(cleaned) > 3:
        return True
    return False


def _build_date_series(bt: dict[str, Any], n: int) -> list[str]:
    raw = bt.get("equity_dates")
    if isinstance(raw, list) and len(raw) == n:
        parsed = [str(x)[:10] if x is not None else "" for x in raw]
        if not _is_placeholder_date_series(parsed):
            return parsed

    ts = bt.get("test_start")
    te = bt.get("test_end")
    if ts and te and n > 0:
        try:
            start = str(ts)[:10]
            end = str(te)[:10]
            dr = pd.date_range(start=start, end=end, periods=n)
            parsed = [d.strftime("%Y-%m-%d") for d in dr]
            if not _is_placeholder_date_series(parsed):
                return parsed
        except Exception:  # noqa: BLE001
            pass
    return [str(i) for i in range(n)]


def _parse_benchmark_curves(backtest: dict[str, Any], n: int) -> list[dict[str, Any]]:
    """
    Accept ``benchmark_curves`` (list of {label, equity}) or ``benchmarks`` as a dict label -> series.
    Only includes series whose length matches ``n``.
    """
    raw = backtest.get("benchmark_curves")
    if raw is None:
        raw = backtest.get("benchmarks")
    out: list[dict[str, Any]] = []
    if isinstance(raw, list):
        for item in raw:
            if not isinstance(item, dict):
                continue
            label = str(item.get("label") or item.get("name") or "Benchmark").strip() or "Benchmark"
            eq = item.get("equity") if "equity" in item else item.get("values")
            if not isinstance(eq, list) or len(eq) != n:
                continue
            try:
                vals = [float(x) for x in eq]
            except (TypeError, ValueError):
                continue
            out.append({"label": label[:160], "equity": vals})
    elif isinstance(raw, dict):
        for label, eq in raw.items():
            if not isinstance(eq, list) or len(eq) != n:
                continue
            try:
                vals = [float(x) for x in eq]
            except (TypeError, ValueError):
                continue
            lab = str(label).strip() or "Benchmark"
            out.append({"label": lab[:160], "equity": vals})
    return out


def _normalize_trades(trades: Any, dates: list[str]) -> list[dict[str, Any]]:
    if not isinstance(trades, list):
        return []
    date_to_i = {d: i for i, d in enumerate(dates) if d}
    out: list[dict[str, Any]] = []
    for raw in trades:
        if not isinstance(raw, dict):
            continue
        idx: int | None = None
        if raw.get("index") is not None:
            try:
                idx = int(raw["index"])
            except (TypeError, ValueError):
                idx = None
        if idx is None and raw.get("date") is not None:
            ds = str(raw["date"])[:10]
            idx = date_to_i.get(ds)
        if idx is None or idx < 0 or idx >= len(dates):
            continue
        side = str(raw.get("side", "trade") or "trade").lower()
        if side not in ("buy", "sell", "trade"):
            side = "trade"
        label = raw.get("label") or raw.get("note") or raw.get("reason") or ""
        out.append(
            {
                "index": idx,
                "date": dates[idx],
                "side": side,
                "label": str(label)[:240],
            }
        )
    return out


def build_equity_viz_payload(backtest: dict[str, Any]) -> dict[str, Any] | None:
    curve = backtest.get("equity_curve")
    if not isinstance(curve, list) or len(curve) < 2:
        return None
    try:
        equity = [float(x) for x in curve]
    except (TypeError, ValueError):
        return None
    n = len(equity)
    dates = _build_date_series(backtest, n)
    trades = _normalize_trades(backtest.get("trade_events"), dates)
    benchmarks = _parse_benchmark_curves(backtest, n)
    payload: dict[str, Any] = {
        "version": 1,
        "dates": dates,
        "equity": equity,
        "trades": trades,
    }
    if benchmarks:
        payload["benchmarks"] = benchmarks
    return payload


_BENCH_COLORS = ("#94a3b8", "#fbbf24", "#a78bfa", "#4ade80", "#fb7185", "#38bdf8")


def _render_png(
    dates: list[str],
    equity: list[float],
    trades: list[dict[str, Any]],
    benchmarks: list[dict[str, Any]] | None = None,
) -> bytes:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(10, 4.2), dpi=120)
    xs = list(range(len(equity)))
    ax.plot(xs, equity, color="#22d3ee", linewidth=1.4, label="Strategy", zorder=3)
    ax.fill_between(xs, equity, alpha=0.12, color="#22d3ee", zorder=1)
    if benchmarks:
        for i, b in enumerate(benchmarks):
            beq = b.get("equity")
            lbl = str(b.get("label", f"Benchmark {i + 1}"))
            if not isinstance(beq, list) or len(beq) != len(equity):
                continue
            c = _BENCH_COLORS[i % len(_BENCH_COLORS)]
            ax.plot(xs, beq, color=c, linewidth=1.0, linestyle="--", alpha=0.95, label=lbl[:48], zorder=2)
    by_side = {"buy": "#4ade80", "sell": "#f87171", "trade": "#fbbf24"}
    for t in trades:
        i = int(t["index"])
        if i < 0 or i >= len(equity):
            continue
        side = str(t.get("side", "trade"))
        ax.scatter(
            [i],
            [equity[i]],
            s=36,
            zorder=5,
            color=by_side.get(side, by_side["trade"]),
            edgecolors="white",
            linewidths=0.4,
        )
    ax.set_title("Equity vs benchmarks" if benchmarks else "Equity curve")
    if benchmarks:
        ax.legend(loc="upper left", fontsize=7, framealpha=0.88)
    if dates and all(d.isdigit() for d in dates[: min(len(dates), 5)]):
        ax.set_xlabel("Trading day index")
    else:
        ax.set_xlabel("Trading day")
    ax.set_ylabel("Portfolio value")
    if dates and len(dates) == len(equity):
        step = max(1, len(dates) // 8)
        ax.set_xticks(xs[::step])
        ax.set_xticklabels([dates[j] for j in xs[::step]], rotation=35, ha="right", fontsize=7)
    ax.grid(True, alpha=0.2)
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight")
    plt.close(fig)
    return buf.getvalue()


def write_equity_viz_for_workspace(ws: Workspace) -> bool:
    """
    If ``backtest_results`` exists with a usable equity curve, write ``equity_viz.json`` and
    ``equity_chart.png``. Returns True when new artifacts were written.
    """
    if not ws.has("backtest_results"):
        return False
    try:
        bt = ws.load_json("backtest_results")
    except (OSError, json.JSONDecodeError, KeyError):
        return False
    if not isinstance(bt, dict):
        return False
    payload = build_equity_viz_payload(bt)
    if payload is None:
        return False

    try:
        png = _render_png(
            payload["dates"],
            payload["equity"],
            payload["trades"],
            payload.get("benchmarks"),
        )
    except Exception:  # noqa: BLE001
        png = b""
    # Save PNG first, then JSON, so manifest iteration order ends on ``equity_viz`` and
    # “follow latest artifact” opens the interactive chart.
    if png:
        ws.save_binary(
            "equity_chart",
            filename="equity_chart.png",
            data=png,
            kind="image",
            description="Static equity curve plot (PNG)",
        )
    ws.save_json(
        "equity_viz",
        payload,
        description="Equity curve + trade markers for interactive chart",
    )
    return True
