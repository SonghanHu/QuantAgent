import { useMemo, useState } from 'react'

import type { EquityVizPayload } from '../types'

const W = 820
const H = 300
const PAD = { l: 52, r: 20, t: 20, b: 56 }

const BENCH_STROKE = ['#94a3b8', '#fbbf24', '#a78bfa', '#4ade80', '#fb7185', '#38bdf8']

function tradeColor(side: string) {
  const s = side.toLowerCase()
  if (s === 'buy') return '#4ade80'
  if (s === 'sell') return '#f87171'
  return '#fbbf24'
}

export function EquityVizPreview({ payload }: { payload: EquityVizPayload }) {
  const [selectedListIndex, setSelectedListIndex] = useState<number | null>(null)

  const { linePath, benchPaths, xScale, yScale, minE, maxE } = useMemo(() => {
    const eq = payload.equity
    const benches = payload.benchmarks ?? []
    const n = eq.length
    let minV = Math.min(...eq)
    let maxV = Math.max(...eq)
    for (const b of benches) {
      minV = Math.min(minV, ...b.equity)
      maxV = Math.max(maxV, ...b.equity)
    }
    const span = maxV - minV || 1
    const innerW = W - PAD.l - PAD.r
    const innerH = H - PAD.t - PAD.b
    const xs = (i: number) => PAD.l + (n <= 1 ? innerW / 2 : (i / (n - 1)) * innerW)
    const ys = (v: number) => PAD.t + (1 - (v - minV) / span) * innerH
    const parts: string[] = []
    for (let i = 0; i < n; i++) {
      const x = xs(i)
      const y = ys(eq[i])
      parts.push(i === 0 ? `M ${x} ${y}` : `L ${x} ${y}`)
    }
    const bpaths: string[] = []
    for (const b of benches) {
      const seg: string[] = []
      for (let i = 0; i < n; i++) {
        const x = xs(i)
        const y = ys(b.equity[i])
        seg.push(i === 0 ? `M ${x} ${y}` : `L ${x} ${y}`)
      }
      bpaths.push(seg.join(' '))
    }
    return {
      linePath: parts.join(' '),
      benchPaths: bpaths,
      xScale: xs,
      yScale: ys,
      minE: minV,
      maxE: maxV,
    }
  }, [payload.equity, payload.benchmarks])

  const xTickStep = Math.max(1, Math.floor(payload.dates.length / 7))

  function isTradeSelected(listIdx: number) {
    return selectedListIndex === listIdx
  }

  return (
    <div className="space-y-4">
      <p className="text-xs leading-relaxed text-slate-400">
        Interactive equity curve: cyan is the strategy; dashed lines are benchmarks (when the backtest outputs{' '}
        <code className="text-slate-500">benchmark_curves</code>). Click a point or a trade row below to
        highlight the corresponding date. Range:{' '}
        <span className="text-slate-300">
          {payload.dates[0] ?? '—'} — {payload.dates[payload.dates.length - 1] ?? '—'}
        </span>
      </p>
      <div className="rounded-xl border border-cyan-500/20 bg-slate-950/80 p-2">
        <svg
          viewBox={`0 0 ${W} ${H}`}
          className="h-auto w-full max-h-[min(360px,55vh)]"
          role="img"
          aria-label="Equity curve with trade markers"
        >
          <defs>
            <linearGradient id="eqFill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#22d3ee" stopOpacity="0.25" />
              <stop offset="100%" stopColor="#22d3ee" stopOpacity="0" />
            </linearGradient>
          </defs>
          <text x={PAD.l} y={16} fill="#94a3b8" style={{ fontSize: 11 }}>
            {minE.toLocaleString(undefined, { maximumFractionDigits: 0 })} —{' '}
            {maxE.toLocaleString(undefined, { maximumFractionDigits: 0 })}
          </text>
          {payload.benchmarks?.map((b, bi) => (
            <path
              key={`bench-${bi}-${b.label}`}
              d={benchPaths[bi]}
              fill="none"
              stroke={BENCH_STROKE[bi % BENCH_STROKE.length]}
              strokeWidth="1.5"
              strokeDasharray="6 4"
              className="pointer-events-none opacity-[0.92]"
            />
          ))}
          <path
            d={`${linePath} L ${xScale(payload.equity.length - 1)} ${H - PAD.b} L ${xScale(0)} ${H - PAD.b} Z`}
            fill="url(#eqFill)"
            className="pointer-events-none"
          />
          <path d={linePath} fill="none" stroke="#22d3ee" strokeWidth="2" strokeLinejoin="round" className="pointer-events-none" />
          {payload.dates.map((d, i) =>
            i % xTickStep === 0 || i === payload.dates.length - 1 ? (
              <text
                key={`xt-${i}`}
                x={xScale(i)}
                y={H - 18}
                textAnchor="middle"
                fill="#64748b"
                style={{ fontSize: 9 }}
              >
                {d.length >= 10 ? d.slice(2) : d}
              </text>
            ) : null,
          )}
          {payload.trades.map((t, ti) => {
            const i = t.index
            if (i < 0 || i >= payload.equity.length) return null
            const cx = xScale(i)
            const cy = yScale(payload.equity[i])
            const sel = isTradeSelected(ti)
            const r = sel ? 9 : 5
            const fill = tradeColor(t.side)
            return (
              <g key={`tr-${ti}-${i}`}>
                <circle
                  cx={cx}
                  cy={cy}
                  r={r + 6}
                  fill="transparent"
                  className="cursor-pointer"
                  onClick={() => setSelectedListIndex(ti)}
                />
                <circle
                  cx={cx}
                  cy={cy}
                  r={r}
                  fill={fill}
                  stroke={sel ? '#fff' : 'rgba(255,255,255,0.35)'}
                  strokeWidth={sel ? 2 : 1}
                  className="cursor-pointer transition-[r,stroke-width]"
                  onClick={() => setSelectedListIndex(ti)}
                />
              </g>
            )
          })}
        </svg>
      </div>

      {payload.benchmarks && payload.benchmarks.length > 0 ? (
        <div className="flex flex-wrap gap-x-4 gap-y-1 text-[10px] text-slate-400">
          <span className="inline-flex items-center gap-1.5">
            <span className="inline-block h-0.5 w-5 bg-cyan-400" aria-hidden />
            Strategy
          </span>
          {payload.benchmarks.map((b, bi) => (
            <span key={`leg-${bi}`} className="inline-flex items-center gap-1.5">
              <span
                className="inline-block h-[2px] w-5 shrink-0"
                style={{
                  background: `repeating-linear-gradient(90deg, ${BENCH_STROKE[bi % BENCH_STROKE.length]} 0 5px, transparent 5px 9px)`,
                }}
                aria-hidden
              />
              {b.label}
            </span>
          ))}
        </div>
      ) : null}

      {payload.trades.length > 0 ? (
        <div>
          <div className="mb-2 text-[11px] font-medium uppercase tracking-wider text-slate-500">Trade points</div>
          <ul className="max-h-48 space-y-1 overflow-y-auto rounded-lg border border-white/10 bg-slate-900/50 p-2">
            {payload.trades.map((t, ti) => {
              const sel = selectedListIndex === ti
              return (
                <li key={`row-${ti}`}>
                  <button
                    type="button"
                    onClick={() => setSelectedListIndex(sel ? null : ti)}
                    className={`w-full rounded-lg border px-3 py-2 text-left text-xs transition ${
                      sel
                        ? 'border-cyan-400/60 bg-cyan-500/15 text-white'
                        : 'border-transparent bg-transparent text-slate-300 hover:border-white/15 hover:bg-white/5'
                    }`}
                  >
                    <span className="font-mono text-slate-400">{t.date}</span>
                    <span
                      className="ml-2 font-medium"
                      style={{ color: tradeColor(t.side) }}
                    >
                      {t.side}
                    </span>
                    {t.label ? <span className="ml-2 text-slate-500">{t.label}</span> : null}
                    <span className="ml-2 text-slate-500">idx {t.index}</span>
                  </button>
                </li>
              )
            })}
          </ul>
        </div>
      ) : (
        <p className="text-xs text-slate-500">
          This backtest did not provide <code>trade_events</code>; only the equity curve is shown. Output a
          trade list in the backtest script to enable markers.
        </p>
      )}
    </div>
  )
}
