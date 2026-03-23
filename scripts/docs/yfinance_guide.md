# yfinance 使用说明（给 LLM / 研究员）

目标：根据**自然语言任务**选出合法参数，填进结构化 `YFinanceFetchSpec`（或等价 kwargs），由**固定代码**调用 `yfinance` 下载。**不要**生成任意 Python 去 `exec`；只填字段即可，这样每次任务可以不同，但执行路径唯一、可审计。

---

## 核心 API（本项目实际调用）

我们使用 **`yfinance.download(...)`** 批量下载（单只或多标的）。

常用参数（与 `YFinanceFetchSpec` / `load_data` 对齐）：

| 字段 | 含义 |
|------|------|
| `tickers` | 字符串列表，或逗号分隔。Yahoo Finance 代码，如 `SPY`、`AAPL`、`^GSPC`、`GC=F`（黄金期货连续）、`ES=F`（E-mini S&P 期货）等 |
| `period` | 当不用 `start`/`end` 时： `1d, 5d, 1mo, 3mo, 6mo, 1y, 2y, 5y, 10y, ytd, max` |
| `start` / `end` | `YYYY-MM-DD`；与 `period` 二选一逻辑由库处理，我们优先：若给了 `start` 或 `end` 则走区间，否则用 `period`（默认 `1y`） |
| `interval` | `1m,2m,5m,15m,30m,60m,90m,1h,1d,5d,1wk,1mo,3mo`（分钟级历史长度受限，注意 Yahoo 限制） |
| `auto_adjust` | 是否对 OHLC 做复权（默认 True） |
| `prepost` | 是否含盘前盘后（主要对日内数据有意义） |
| `actions` | True 时可能带股息/拆股等列（依标的而定） |

多标的时，返回的 `DataFrame` 列为 **MultiIndex**（Ticker, OHLCV 字段）。单标的时多为单层列名。

---

## 符号怎么选（常见）

- **美股大盘 ETF**：`SPY`, `QQQ`, `IWM`
- **指数（Yahoo 代码带 `^`）**：`^GSPC`, `^DJI`, `^VIX`
- **外汇**：`EURUSD=X`
- **商品期货（连续）**：`GC=F`, `CL=F`, `ES=F` 等
- **A 股 / 港股**：常见为 `000001.SS`, `0700.HK` 等（以 Yahoo 实际为准）

若用户只说「标普」「黄金」「铜」，你应映射到合理 Yahoo 符号并在 `rationale` 里写一句。

---

## 区间与频率建议

- **日频动量 / 回测**：`interval="1d"`, `period="2y"` 或明确 `start`/`end` 避免未来函数。
- **周频研究**：可先下 `1d` 再在下游 resample；或直接 `interval="1wk"`（注意对齐方式）。
- **短期调试**：`period="5d"` 或 `1mo` 减小体积。

---

## 失败与边界

- 错误代码、停牌、或退市可能导致 **空表**；工具会返回 `error: empty_frame`。
- 分钟线过长区间常被 Yahoo 拒绝；宜缩短 `period` 或改用日线。
- 数据源为 Yahoo，**非官方实时行情**；研究与回测需注意延迟与调整方式。

---

## 输出给下游

工具返回 JSON 友好字段：`rows`, `columns`, `start_ts`, `end_ts`, `preview_rows` 等。后续特征工程应读这些元数据，而不是假设固定列名（多标的时务必看 `columns`）。

---

## 与 `load_data` 的对应关系

调用工具时传 kwargs，例如：

```json
{
  "tickers": "SPY,TLT",
  "period": "2y",
  "interval": "1d",
  "auto_adjust": true,
  "rationale": "User asked US equity+bond cross-section; daily for momentum"
}
```

未提供 `tickers` 时走 **demo stub**（仅用于测试管线）。
