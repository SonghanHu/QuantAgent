# yfinance guide (for LLMs / researchers)

**Goal:** From a **natural-language task**, choose valid parameters for structured `YFinanceFetchSpec` (or equivalent kwargs). **Fixed application code** calls `yfinance` to download. Do **not** invent arbitrary Python to `exec`—only fill fields so tasks can differ while the execution path stays auditable.

---

## Core API (what this repo calls)

We use **`yfinance.download(...)`** for one or many tickers.

Common fields (aligned with `YFinanceFetchSpec` / `load_data`):

| Field | Meaning |
|-------|---------|
| `tickers` | List of strings or comma-separated Yahoo symbols: `SPY`, `AAPL`, `^GSPC`, `GC=F` (gold continuous), `ES=F` (E-mini S&P), etc. |
| `period` | When `start`/`end` omitted: `1d, 5d, 1mo, 3mo, 6mo, 1y, 2y, 5y, 10y, ytd, max` |
| `start` / `end` | `YYYY-MM-DD`; library resolves vs `period`. We prefer: if either is set, use the range; else `period` (default `1y`). |
| `interval` | `1m,2m,5m,15m,30m,60m,90m,1h,1d,5d,1wk,1mo,3mo` (intraday history limits apply—Yahoo constraints) |
| `auto_adjust` | Adjust OHLC for splits/dividends (default True) |
| `prepost` | Include extended hours (mainly for intraday) |
| `actions` | If True, may include dividend/split columns where applicable |

Multi-ticker downloads return a **MultiIndex** `DataFrame` (Ticker × OHLCV). Single-ticker frames usually have a flat column index.

---

## Choosing symbols (common cases)

- **US broad ETFs:** `SPY`, `QQQ`, `IWM`
- **Indices (caret prefix):** `^GSPC`, `^DJI`, `^VIX`
- **FX:** `EURUSD=X`
- **Commodity futures (continuous):** `GC=F`, `CL=F`, `ES=F`, …
- **China / HK (examples):** `000001.SS`, `0700.HK` (verify on Yahoo)

If the user only says “S&P”, “gold”, or “copper”, map to sensible Yahoo symbols and note the mapping in `rationale`.

---

## Horizon and frequency

- **Daily momentum / backtest:** `interval="1d"`, `period="2y"` or explicit `start`/`end` to avoid lookahead.
- **Weekly research:** download `1d` and resample downstream, or `interval="1wk"` (watch alignment).
- **Quick debug:** `period="5d"` or `1mo` to shrink payload.

---

## Failures and limits

- Bad symbols, halts, or delistings can yield **empty** data; the tool may return `error: empty_frame`.
- Very long ranges on minute bars are often rejected; shorten `period` or use daily.
- Yahoo is **not** a guaranteed real-time official feed; research and backtests should account for delay and adjustment choices.

---

## Downstream consumption

The tool returns JSON-friendly fields: `rows`, `columns`, `start_ts`, `end_ts`, `preview_rows`, etc. Feature code should read this metadata instead of assuming fixed column names (critical for multi-ticker panels).

---

## Example kwargs for `load_data`

```text
tickers: "SPY,TLT"
period: "2y"
interval: "1d"
auto_adjust: true
rationale: "US equity + bonds for cross-asset momentum"
```

If **`tickers`** is omitted, the **demo stub** path runs for pipeline testing only.
