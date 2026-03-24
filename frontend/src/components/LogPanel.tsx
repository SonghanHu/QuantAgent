import { useState } from 'react'

import type { AgentEvent } from '../types'

type LogPanelProps = {
  events: AgentEvent[]
}

function formatEvent(event: AgentEvent): { icon: string; label: string; detail: string; tone: string } {
  switch (event.type) {
    case 'run_start':
      return {
        icon: '🚀',
        label: 'Run started',
        detail: String(event.goal ?? ''),
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

export function LogPanel({ events }: LogPanelProps) {
  const [expandedIndex, setExpandedIndex] = useState<number | null>(null)

  return (
    <section className="rounded-3xl border border-white/10 bg-white/5 p-5">
      <div className="mb-4 flex items-center justify-between">
        <h2 className="text-lg font-semibold text-white">Live log</h2>
        <span className="text-xs text-slate-400">{events.length} events</span>
      </div>
      <div className="max-h-[40rem] space-y-1.5 overflow-auto pr-1">
        {events.length === 0 ? (
          <div className="rounded-2xl border border-dashed border-white/10 px-4 py-6 text-sm text-slate-400">
            Start a run to see live events.
          </div>
        ) : (
          events.map((event, index) => {
            const { icon, label, detail, tone } = formatEvent(event)
            const isExpanded = expandedIndex === index
            return (
              <article
                key={`${event.ts}-${index}`}
                className={`cursor-pointer rounded-xl border p-2.5 transition-colors hover:bg-white/[0.02] ${tone}`}
                onClick={() => setExpandedIndex(isExpanded ? null : index)}
              >
                <div className="flex items-start gap-2">
                  <span className="mt-px flex-shrink-0 text-sm leading-none">{icon}</span>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center justify-between gap-2">
                      <span className="truncate text-sm font-medium text-slate-200">{label}</span>
                      <span className="flex-shrink-0 text-[10px] text-slate-600">
                        {new Date(event.ts).toLocaleTimeString()}
                      </span>
                    </div>
                    {detail && !isExpanded && (
                      <div className="mt-0.5 truncate text-xs text-slate-500">{detail}</div>
                    )}
                    {isExpanded && (
                      <pre className="mt-2 max-h-60 overflow-auto rounded-lg bg-slate-950/60 p-2 text-[11px] leading-relaxed text-slate-400">
                        {JSON.stringify(event, null, 2)}
                      </pre>
                    )}
                  </div>
                </div>
              </article>
            )
          })
        )}
      </div>
    </section>
  )
}
