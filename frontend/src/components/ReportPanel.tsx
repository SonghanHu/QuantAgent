import type { AgentEvent } from '../types'

type ReportPanelProps = {
  finalEvent: AgentEvent | null
}

export function ReportPanel({ finalEvent }: ReportPanelProps) {
  const finalState = finalEvent?.final_state as
    | {
        status?: string
        execution_log?: Array<{ subtask_id: number; tool_name: string; status: string; result_summary: string }>
      }
    | undefined

  return (
    <section className="rounded-3xl border border-white/10 bg-white/5 p-5">
      <div className="mb-4">
        <h2 className="text-lg font-semibold text-white">Final report</h2>
        <p className="text-sm text-slate-300">
          {finalState ? `Run status: ${finalState.status}` : 'The final report appears when the run completes.'}
        </p>
      </div>
      {!finalState ? (
        <div className="rounded-2xl border border-dashed border-white/10 px-4 py-6 text-sm text-slate-400">
          Waiting for completion.
        </div>
      ) : (
        <div className="space-y-3">
          {(finalState.execution_log ?? []).map((entry) => (
            <article key={`${entry.subtask_id}-${entry.tool_name}`} className="rounded-2xl border border-white/10 bg-slate-900/70 p-4">
              <div className="flex items-center justify-between gap-3">
                <div className="text-sm font-medium text-white">
                  Subtask {entry.subtask_id} · {entry.tool_name}
                </div>
                <div
                  className={`rounded-full px-3 py-1 text-xs ${
                    entry.status === 'ok' ? 'bg-emerald-400/15 text-emerald-300' : 'bg-rose-400/15 text-rose-300'
                  }`}
                >
                  {entry.status}
                </div>
              </div>
              <p className="mt-2 text-sm text-slate-300">{entry.result_summary}</p>
            </article>
          ))}
        </div>
      )}
    </section>
  )
}
