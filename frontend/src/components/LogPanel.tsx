import { useEffect, useRef, useState, type ReactNode } from 'react'

import type { AgentEvent } from '../types'

type LogPanelProps = {
  events: AgentEvent[]
}

function summarizeText(text: string, maxLength = 120) {
  const compact = text.replace(/\s+/g, ' ').trim()
  if (compact.length <= maxLength) return compact
  return `${compact.slice(0, maxLength).trimEnd()}...`
}

function formatEvent(event: AgentEvent): { icon: string; label: string; detail: string; tone: string } {
  switch (event.type) {
    case 'run_start':
      return {
        icon: '🚀',
        label: 'Run started',
        detail: summarizeText(String(event.goal ?? ''), 90),
        tone: 'border-cyan-400/20 bg-cyan-400/5',
      }
    case 'decompose_done':
      return {
        icon: '🧩',
        label: `Decomposed → ${event.total_subtasks} subtasks`,
        detail: String(event.goal_summary ?? ''),
        tone: 'border-indigo-400/20 bg-indigo-400/5',
      }
    case 'workflow_topo_order':
      return {
        icon: '📐',
        label: 'Topological order computed',
        detail: `Execution order: ${(event.order as number[])?.join(' → ') ?? ''}`,
        tone: 'border-white/10 bg-slate-900/60',
      }
    case 'subtask_start':
      return {
        icon: '▶',
        label: `Subtask #${event.subtask_id}: ${event.subtask_title}`,
        detail: `Step ${event.position}/${event.total}`,
        tone: 'border-sky-400/20 bg-sky-400/5',
      }
    case 'subtask_tool_resolved':
      return {
        icon: '🔀',
        label: `Routed → ${event.tool_name}`,
        detail: `#${event.subtask_id} "${event.subtask_title}" via ${event.source}`,
        tone: 'border-white/10 bg-slate-900/60',
      }
    case 'subtask_done': {
      const isSkipped = event.status === 'skipped'
      const isError = event.status !== 'ok' && !isSkipped
      return {
        icon: isSkipped ? '⏭' : isError ? '✗' : '✓',
        label: `#${event.subtask_id} ${isSkipped ? 'skipped' : isError ? 'failed' : 'done'}: ${event.tool_name}`,
        detail: String(event.result_summary ?? ''),
        tone: isSkipped
          ? 'border-slate-400/20 bg-slate-400/5'
          : isError
            ? 'border-rose-400/20 bg-rose-400/5'
            : 'border-emerald-400/20 bg-emerald-400/5',
      }
    }
    case 'workspace_update':
      return {
        icon: '💾',
        label: `Artifact: ${event.artifact_name}`,
        detail: `${(event.artifact as Record<string, unknown>)?.kind ?? ''} ${
          (event.artifact as Record<string, unknown>)?.shape
            ? `· ${((event.artifact as Record<string, unknown>).shape as number[]).join(' × ')}`
            : ''
        }`,
        tone: 'border-violet-400/20 bg-violet-400/5',
      }
    case 'data_analyst_round': {
      const stage = event.stage as string
      if (stage === 'analysis_start') {
        return {
          icon: '🔬',
          label: `Analysis round ${event.round}`,
          detail: String(event.instruction ?? '').slice(0, 120),
          tone: 'border-amber-400/15 bg-amber-400/5',
        }
      }
      if (stage === 'judge_done') {
        return {
          icon: event.ready ? '✅' : '🔄',
          label: `Judge round ${event.round}: ${event.ready ? 'Ready' : 'Continue'}`,
          detail: String(event.reasoning ?? '').slice(0, 150),
          tone: event.ready ? 'border-emerald-400/15 bg-emerald-400/5' : 'border-amber-400/15 bg-amber-400/5',
        }
      }
      if (stage === 'analysis_failed') {
        return {
          icon: '⚠️',
          label: `Analysis round ${event.round} failed`,
          detail: `returncode=${event.returncode}`,
          tone: 'border-rose-400/15 bg-rose-400/5',
        }
      }
      return {
        icon: '📊',
        label: `Analyst: ${stage}`,
        detail: '',
        tone: 'border-amber-400/15 bg-amber-400/5',
      }
    }
    case 'report_generating':
      return {
        icon: '📝',
        label: 'Generating final report',
        detail: 'LLM is writing the report...',
        tone: 'border-cyan-400/15 bg-cyan-400/5',
      }
    case 'run_done': {
      const status = event.status as string
      return {
        icon: status === 'done' ? '🏁' : '❌',
        label: `Run ${status}`,
        detail: String(event.workspace_summary ?? ''),
        tone: status === 'done' ? 'border-emerald-400/25 bg-emerald-400/5' : 'border-rose-400/25 bg-rose-400/5',
      }
    }
    default:
      return {
        icon: '•',
        label: event.type,
        detail: '',
        tone: 'border-white/10 bg-slate-900/60',
      }
  }
}

function renderExpandedSummary(event: AgentEvent, detail: string): ReactNode {
  if (event.type === 'run_start') {
    return (
      <div className="space-y-1.5">
        <div className="text-[10px] font-medium uppercase tracking-widest text-slate-500">Goal</div>
        <div className="text-xs leading-relaxed text-slate-300">{String(event.goal ?? '')}</div>
      </div>
    )
  }

  if (detail) {
    return <div className="text-xs leading-relaxed text-slate-300">{detail}</div>
  }

  return <div className="text-xs text-slate-500">No additional summary.</div>
}

export function LogPanel({ events }: LogPanelProps) {
  const [expandedIndex, setExpandedIndex] = useState<number | null>(null)
  const [autoScroll, setAutoScroll] = useState(true)
  const listRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    if (!autoScroll || !listRef.current) return
    listRef.current.scrollTop = listRef.current.scrollHeight
  }, [autoScroll, events])

  function handleScroll() {
    if (!listRef.current) return
    const { scrollTop, scrollHeight, clientHeight } = listRef.current
    const isNearBottom = scrollHeight - scrollTop - clientHeight < 24
    setAutoScroll(isNearBottom)
  }

  return (
    <section className="rounded-2xl border border-white/10 bg-white/5 p-3 sm:p-4">
      <div className="mb-2 flex items-center justify-between gap-2">
        <div>
          <h2 className="text-sm font-semibold tracking-wide text-white">Live log</h2>
          <div className="tabular-nums text-[10px] text-slate-500">{events.length} events</div>
        </div>
        <div className="flex items-center gap-2">
          {!autoScroll && events.length > 0 && (
            <button
              type="button"
              className="rounded-full border border-cyan-400/20 px-2 py-1 text-[10px] text-cyan-300 transition hover:border-cyan-400/40 hover:bg-cyan-400/10"
              onClick={() => {
                setAutoScroll(true)
                requestAnimationFrame(() => {
                  if (listRef.current) {
                    listRef.current.scrollTop = listRef.current.scrollHeight
                  }
                })
              }}
            >
              Jump to latest
            </button>
          )}
          <button
            type="button"
            className={`rounded-full border px-2 py-1 text-[10px] transition ${
              autoScroll
                ? 'border-cyan-400/20 bg-cyan-400/10 text-cyan-300'
                : 'border-white/10 text-slate-400 hover:border-white/20'
            }`}
            onClick={() => setAutoScroll((current) => !current)}
          >
            Auto-scroll
          </button>
        </div>
      </div>
      <div
        ref={listRef}
        className="max-h-[min(36rem,70vh)] space-y-1 overflow-auto pr-0.5"
        onScroll={handleScroll}
      >
        {events.length === 0 ? (
          <div className="rounded-lg border border-dashed border-white/10 px-3 py-4 text-xs text-slate-400">
            Start a run to see live events.
          </div>
        ) : (
          events.map((event, index) => {
            const { icon, label, detail, tone } = formatEvent(event)
            const isExpanded = expandedIndex === index
            return (
              <article key={`${event.ts}-${index}`} className={`rounded-lg border ${tone}`}>
                <button
                  type="button"
                  className="w-full rounded-lg px-2 py-1.5 text-left transition-colors hover:bg-white/[0.03] active:bg-white/[0.05]"
                  aria-expanded={isExpanded}
                  onClick={() => setExpandedIndex(isExpanded ? null : index)}
                >
                  <div className="flex items-start gap-1.5">
                    <span className="mt-0.5 flex-shrink-0 text-[11px] leading-none opacity-90">{icon}</span>
                    <div className="min-w-0 flex-1">
                      <div className="flex items-baseline justify-between gap-2">
                        <span className="truncate text-[11px] font-medium leading-snug text-slate-200">{label}</span>
                        <span className="flex items-center gap-1.5">
                          <span className="flex-shrink-0 text-[9px] tabular-nums text-slate-600">
                            {new Date(event.ts).toLocaleTimeString()}
                          </span>
                          <span className="text-[10px] text-slate-500">{isExpanded ? '−' : '+'}</span>
                        </span>
                      </div>
                      {detail && !isExpanded && (
                        <div className="mt-0.5 truncate text-[10px] leading-snug text-slate-500">{detail}</div>
                      )}
                    </div>
                  </div>
                </button>
                {isExpanded && (
                  <div className="mx-2 mb-2 space-y-2">
                    <div className="rounded-md bg-slate-950/40 p-2">
                      {renderExpandedSummary(event, detail)}
                    </div>
                    <details className="rounded-md bg-slate-950/30 p-2">
                      <summary className="cursor-pointer text-[10px] text-slate-500 hover:text-slate-400">
                        Raw event
                      </summary>
                      <pre className="mt-2 max-h-40 overflow-auto text-[10px] leading-relaxed text-slate-400">
                        {JSON.stringify(event, null, 2)}
                      </pre>
                    </details>
                  </div>
                )}
              </article>
            )
          })
        )}
      </div>
    </section>
  )
}
