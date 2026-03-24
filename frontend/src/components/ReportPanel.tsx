import { useEffect, useMemo, useState } from 'react'

import type { AgentEvent } from '../types'

type ReportPanelProps = {
  events: AgentEvent[]
  /** Used to load `final_report.json` if `run_done` omitted the report payload (e.g. strict JSON issues). */
  runId: string | null
}

type LLMReport = {
  title: string
  executive_summary: string
  sections: { heading: string; body: string }[]
  key_findings: string[]
  recommendations: string[]
  limitations: string[]
  conclusion: string
}

type RunMetrics = {
  status: string
  goal: string
  goalSummary: string
  totalSubtasks: number
  completedSubtasks: number
  failedSubtasks: number
  toolBreakdown: Record<string, { count: number; ok: number; error: number }>
  artifacts: string[]
  modelMetrics?: { model: string; train_r2: number; test_r2: number; test_rmse: number }
  backtestMetrics?: {
    sharpe: number
    max_drawdown: number
    total_return?: number
    annual_return?: number
    win_rate?: number
    stub?: boolean
  }
  durationSec?: number
  report?: LLMReport
  isGeneratingReport: boolean
}

function extractMetrics(events: AgentEvent[]): RunMetrics | null {
  const runStart = events.find((e) => e.type === 'run_start')
  const runDone = events.find((e) => e.type === 'run_done')
  if (!runStart) return null

  const decompose = events.find((e) => e.type === 'decompose_done')
  const subtaskDone = events.filter((e) => e.type === 'subtask_done')
  const workspaceUpdates = events.filter((e) => e.type === 'workspace_update')
  const isGeneratingReport = events.some((e) => e.type === 'report_generating') && !runDone

  const toolBreakdown: Record<string, { count: number; ok: number; error: number }> = {}
  for (const ev of subtaskDone) {
    const tool = ev.tool_name as string
    if (!toolBreakdown[tool]) toolBreakdown[tool] = { count: 0, ok: 0, error: 0 }
    toolBreakdown[tool].count++
    if (ev.status === 'ok') toolBreakdown[tool].ok++
    else toolBreakdown[tool].error++
  }

  let modelMetrics: RunMetrics['modelMetrics']
  let backtestMetrics: RunMetrics['backtestMetrics']

  for (const ev of subtaskDone) {
    const output = ev.output as Record<string, unknown> | undefined
    if (!output) continue

    if (ev.tool_name === 'train_model' && typeof output.test_r2 === 'number') {
      modelMetrics = {
        model: String(output.model ?? ''),
        train_r2: output.train_r2 as number,
        test_r2: output.test_r2 as number,
        test_rmse: output.test_rmse as number,
      }
    }

    if (ev.tool_name === 'run_backtest' && typeof output.sharpe === 'number') {
      backtestMetrics = {
        sharpe: output.sharpe as number,
        max_drawdown: output.max_drawdown as number,
        total_return: output.total_return as number | undefined,
        annual_return: output.annual_return as number | undefined,
        win_rate: output.win_rate as number | undefined,
        stub: output.stub as boolean | undefined,
      }
    }
  }

  let durationSec: number | undefined
  if (runStart && runDone) {
    const start = new Date(runStart.ts).getTime()
    const end = new Date(runDone.ts).getTime()
    durationSec = Math.round((end - start) / 1000)
  }

  const rawReport = runDone?.report
  const report =
    rawReport && typeof rawReport === 'object' && !Array.isArray(rawReport)
      ? (rawReport as LLMReport)
      : undefined

  return {
    status: (runDone?.status as string) ?? 'running',
    goal: String(runStart.goal ?? ''),
    goalSummary: String(decompose?.goal_summary ?? ''),
    totalSubtasks: (decompose?.total_subtasks as number) ?? 0,
    completedSubtasks: subtaskDone.filter((e) => e.status === 'ok').length,
    failedSubtasks: subtaskDone.filter((e) => e.status !== 'ok').length,
    toolBreakdown,
    artifacts: workspaceUpdates.map((e) => e.artifact_name as string).filter(Boolean),
    modelMetrics,
    backtestMetrics,
    durationSec,
    report: report ?? undefined,
    isGeneratingReport,
  }
}

function MetricCard({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="rounded-xl border border-white/[0.06] bg-slate-900/50 px-3 py-2.5">
      <div className="text-[10px] uppercase tracking-widest text-slate-500">{label}</div>
      <div className="mt-0.5 text-lg font-semibold text-white">{value}</div>
      {sub && <div className="text-[11px] text-slate-500">{sub}</div>}
    </div>
  )
}

function isFallbackReport(r: LLMReport): boolean {
  const lim = r.limitations ?? []
  return (
    r.title === 'Research run summary' ||
    (lim.length > 0 &&
      lim.some(
        (l) =>
          typeof l === 'string' &&
          (l.includes('without a fresh LLM') || l.includes('LLM report generation failed')),
      ))
  )
}

function renderMarkdown(text: string) {
  const lines = text.split('\n')
  return lines.map((line, i) => {
    const boldReplaced = line.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    const codeReplaced = boldReplaced.replace(/`(.+?)`/g, '<code class="rounded bg-slate-800 px-1 py-0.5 text-[11px] text-cyan-300">$1</code>')

    if (line.startsWith('- ') || line.startsWith('• ')) {
      return (
        <li key={i} className="ml-4 list-disc" dangerouslySetInnerHTML={{ __html: codeReplaced.slice(2) }} />
      )
    }
    if (line.trim() === '') return <br key={i} />
    return <p key={i} dangerouslySetInnerHTML={{ __html: codeReplaced }} />
  })
}

export function ReportPanel({ events, runId }: ReportPanelProps) {
  const [hydratedReport, setHydratedReport] = useState<LLMReport | null>(null)
  const [reportMarkdown, setReportMarkdown] = useState<string | null>(null)

  useEffect(() => {
    setHydratedReport(null)
    setReportMarkdown(null)
  }, [runId])

  useEffect(() => {
    const runDone = events.find((e) => e.type === 'run_done')
    const hasReport =
      runDone &&
      runDone.report &&
      typeof runDone.report === 'object' &&
      !Array.isArray(runDone.report)
    if (!runId || !runDone || hasReport) return

    void fetch(`/api/workspace/${runId}/final_report`)
      .then((res) => (res.ok ? res.json() : null))
      .then((data: { kind?: string; content?: unknown } | null) => {
        if (data?.kind !== 'json' || !data.content || typeof data.content !== 'object') return
        const c = data.content as Record<string, unknown>
        setHydratedReport({
          title: String(c.title ?? 'Report'),
          executive_summary: String(c.executive_summary ?? ''),
          sections: Array.isArray(c.sections) ? (c.sections as LLMReport['sections']) : [],
          key_findings: Array.isArray(c.key_findings) ? (c.key_findings as string[]) : [],
          recommendations: Array.isArray(c.recommendations) ? (c.recommendations as string[]) : [],
          limitations: Array.isArray(c.limitations) ? (c.limitations as string[]) : [],
          conclusion: String(c.conclusion ?? ''),
        })
      })
      .catch(() => {})
  }, [events, runId])

  useEffect(() => {
    if (!runId) return
    const runDone = events.find((e) => e.type === 'run_done')
    if (!runDone) return
    void fetch(`/api/workspace/${runId}/report.md`)
      .then((res) => (res.ok ? res.text() : null))
      .then((text) => {
        if (text) setReportMarkdown(text)
      })
      .catch(() => {})
  }, [events, runId])

  const baseMetrics = useMemo(() => extractMetrics(events), [events])
  const metrics = useMemo(() => {
    if (!baseMetrics) return null
    if (baseMetrics.report) return baseMetrics
    if (hydratedReport) return { ...baseMetrics, report: hydratedReport }
    return baseMetrics
  }, [baseMetrics, hydratedReport])

  const runDone = events.find((e) => e.type === 'run_done')

  if (!metrics) {
    return (
      <section className="rounded-3xl border border-white/10 bg-white/5 p-5">
        <h2 className="text-lg font-semibold text-white">Final report</h2>
        <p className="mt-1 text-sm text-slate-400">The report generates when the run completes.</p>
      </section>
    )
  }

  if (metrics.isGeneratingReport && !runDone) {
    return (
      <section className="rounded-3xl border border-white/10 bg-white/5 p-5">
        <h2 className="text-lg font-semibold text-white">Final report</h2>
        <div className="mt-3 flex items-center gap-3 rounded-2xl border border-cyan-400/20 bg-cyan-400/5 px-4 py-4">
          <div className="h-4 w-4 animate-spin rounded-full border-2 border-cyan-400 border-t-transparent" />
          <span className="text-sm text-cyan-300">Generating report with LLM...</span>
        </div>
      </section>
    )
  }

  if (!runDone) {
    return (
      <section className="rounded-3xl border border-white/10 bg-white/5 p-5">
        <h2 className="text-lg font-semibold text-white">Final report</h2>
        <p className="mt-1 text-sm text-slate-400">The report generates when the run completes.</p>
      </section>
    )
  }

  const statusColor = metrics.status === 'done' ? 'text-emerald-400' : 'text-rose-400'
  const statusBg =
    metrics.status === 'done'
      ? 'bg-emerald-400/10 border-emerald-400/20'
      : 'bg-rose-400/10 border-rose-400/20'

  const report = metrics.report

  return (
    <section className="rounded-3xl border border-white/10 bg-white/5 p-5">
      <div className="mb-4 flex items-center justify-between">
        <h2 className="text-lg font-semibold text-white">Final report</h2>
        <div className="flex items-center gap-2">
          {reportMarkdown && (
            <button
              className="rounded-full border border-white/10 px-3 py-1 text-xs text-slate-300 transition hover:border-white/20 hover:text-white"
              onClick={() => {
                const blob = new Blob([reportMarkdown], { type: 'text/markdown' })
                const url = URL.createObjectURL(blob)
                const a = document.createElement('a')
                a.href = url
                a.download = `report-${runId}.md`
                a.click()
                URL.revokeObjectURL(url)
              }}
            >
              ↓ .md
            </button>
          )}
          <span className={`rounded-full border px-3 py-1 text-xs font-medium ${statusBg} ${statusColor}`}>
            {metrics.status}
          </span>
        </div>
      </div>

      {/* LLM-generated report */}
      {report ? (
        <div className="space-y-4">
          {isFallbackReport(report) && (
            <div className="rounded-xl border border-amber-400/25 bg-amber-400/10 px-3 py-2 text-xs text-amber-200/90">
              Showing a <strong>template summary</strong> (execution log + artifacts). The primary LLM report step
              failed or your model may not support structured output — see Limitations below or server logs.
            </div>
          )}
          {/* Title + executive summary */}
          <div className="rounded-2xl border border-white/[0.06] bg-slate-900/40 p-4">
            <h3 className="text-base font-semibold text-white">{report.title}</h3>
            <p className="mt-2 text-sm leading-relaxed text-slate-300">{report.executive_summary}</p>
            <div className="mt-2 flex flex-wrap gap-3 text-[11px] text-slate-500">
              <span>
                {metrics.completedSubtasks}/{metrics.totalSubtasks} subtasks
              </span>
              {metrics.failedSubtasks > 0 && (
                <span className="text-rose-400">{metrics.failedSubtasks} failed</span>
              )}
              {metrics.durationSec !== undefined && <span>{metrics.durationSec}s</span>}
            </div>
          </div>

          {/* Key metrics grid */}
          {(metrics.modelMetrics || metrics.backtestMetrics) && (
            <div>
              <div className="mb-2 text-xs font-medium uppercase tracking-widest text-slate-500">
                Key metrics
              </div>
              <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
                {metrics.modelMetrics && (
                  <>
                    <MetricCard
                      label="Model"
                      value={metrics.modelMetrics.model}
                      sub={`Train R² ${metrics.modelMetrics.train_r2.toFixed(3)}`}
                    />
                    <MetricCard
                      label="Test R²"
                      value={metrics.modelMetrics.test_r2.toFixed(4)}
                      sub={`RMSE ${metrics.modelMetrics.test_rmse.toFixed(4)}`}
                    />
                  </>
                )}
                {metrics.backtestMetrics && (
                  <>
                    <MetricCard
                      label="Sharpe"
                      value={metrics.backtestMetrics.sharpe?.toFixed(2) ?? '—'}
                      sub={metrics.backtestMetrics.stub ? 'stub' : undefined}
                    />
                    <MetricCard
                      label="Max Drawdown"
                      value={`${((metrics.backtestMetrics.max_drawdown ?? 0) * 100).toFixed(1)}%`}
                    />
                    {metrics.backtestMetrics.total_return !== undefined && (
                      <MetricCard
                        label="Total Return"
                        value={`${(metrics.backtestMetrics.total_return * 100).toFixed(1)}%`}
                      />
                    )}
                    {metrics.backtestMetrics.win_rate !== undefined && (
                      <MetricCard
                        label="Win Rate"
                        value={`${(metrics.backtestMetrics.win_rate * 100).toFixed(1)}%`}
                      />
                    )}
                  </>
                )}
              </div>
            </div>
          )}

          {/* Report sections */}
          {(report.sections ?? []).length > 0 && (
            <div className="space-y-3">
              {(report.sections ?? []).map((section, i) => (
                <div
                  key={i}
                  className="rounded-2xl border border-white/[0.06] bg-slate-900/40 p-4"
                >
                  <h4 className="mb-2 text-sm font-semibold text-white">{section.heading}</h4>
                  <div className="space-y-1 text-sm leading-relaxed text-slate-400">
                    {renderMarkdown(section.body)}
                  </div>
                </div>
              ))}
            </div>
          )}

          {/* Key findings */}
          {(report.key_findings ?? []).length > 0 && (
            <div className="rounded-2xl border border-emerald-400/15 bg-emerald-400/5 p-4">
              <div className="mb-2 text-xs font-medium uppercase tracking-widest text-emerald-400/70">
                Key findings
              </div>
              <ul className="space-y-1 text-sm text-slate-300">
                {(report.key_findings ?? []).map((f, i) => (
                  <li key={i} className="flex gap-2">
                    <span className="flex-shrink-0 text-emerald-400">•</span>
                    {f}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* Recommendations */}
          {(report.recommendations ?? []).length > 0 && (
            <div className="rounded-2xl border border-sky-400/15 bg-sky-400/5 p-4">
              <div className="mb-2 text-xs font-medium uppercase tracking-widest text-sky-400/70">
                Recommendations
              </div>
              <ul className="space-y-1 text-sm text-slate-300">
                {(report.recommendations ?? []).map((r, i) => (
                  <li key={i} className="flex gap-2">
                    <span className="flex-shrink-0 text-sky-400">→</span>
                    {r}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* Limitations */}
          {(report.limitations ?? []).length > 0 && (
            <div className="rounded-2xl border border-amber-400/15 bg-amber-400/5 p-4">
              <div className="mb-2 text-xs font-medium uppercase tracking-widest text-amber-400/70">
                Limitations
              </div>
              <ul className="space-y-1 text-sm text-slate-400">
                {(report.limitations ?? []).map((l, i) => (
                  <li key={i} className="flex gap-2">
                    <span className="flex-shrink-0 text-amber-400">⚠</span>
                    {l}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* Conclusion */}
          {report.conclusion && (
            <div className="rounded-2xl border border-white/[0.06] bg-slate-900/40 p-4">
              <div className="mb-1 text-xs font-medium uppercase tracking-widest text-slate-500">
                Conclusion
              </div>
              <p className="text-sm font-medium leading-relaxed text-slate-200">
                {report.conclusion}
              </p>
            </div>
          )}

          {/* Agent breakdown (collapsed) */}
          <details className="group">
            <summary className="cursor-pointer text-xs font-medium uppercase tracking-widest text-slate-500 hover:text-slate-400">
              Agent breakdown & artifacts
            </summary>
            <div className="mt-2 space-y-1">
              {Object.entries(metrics.toolBreakdown).map(([tool, stats]) => (
                <div
                  key={tool}
                  className="flex items-center justify-between rounded-lg border border-white/[0.04] bg-slate-900/30 px-3 py-1.5 text-xs"
                >
                  <span className="font-medium text-slate-300">{tool}</span>
                  <div className="flex gap-2 text-slate-500">
                    <span>{stats.count}×</span>
                    {stats.ok > 0 && <span className="text-emerald-400/70">{stats.ok} ok</span>}
                    {stats.error > 0 && <span className="text-rose-400/70">{stats.error} err</span>}
                  </div>
                </div>
              ))}
              {metrics.artifacts.length > 0 && (
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {[...new Set(metrics.artifacts)].map((a) => (
                    <span
                      key={a}
                      className="rounded-full bg-indigo-400/10 px-2.5 py-1 text-[11px] text-indigo-300 ring-1 ring-indigo-400/20"
                    >
                      {a}
                    </span>
                  ))}
                </div>
              )}
            </div>
          </details>
        </div>
      ) : (
        /* Fallback: no LLM report available */
        <div className="space-y-4">
          <div className="rounded-2xl border border-white/[0.06] bg-slate-900/40 p-4">
            <div className="text-sm font-medium text-white">
              {metrics.goalSummary || metrics.goal}
            </div>
            <div className="mt-2 flex flex-wrap gap-3 text-xs text-slate-400">
              <span>
                {metrics.completedSubtasks}/{metrics.totalSubtasks} subtasks completed
              </span>
              {metrics.failedSubtasks > 0 && (
                <span className="text-rose-400">{metrics.failedSubtasks} failed</span>
              )}
              {metrics.durationSec !== undefined && <span>{metrics.durationSec}s elapsed</span>}
            </div>
          </div>
          <div className="rounded-xl border border-amber-400/15 bg-amber-400/5 p-3 text-xs text-amber-300/80">
            LLM report was not generated for this run. Check the log for details.
          </div>
        </div>
      )}
    </section>
  )
}
