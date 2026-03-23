import type { AgentEvent } from '../types'

type LogPanelProps = {
  events: AgentEvent[]
}

function eventTone(type: string) {
  if (type.includes('done')) return 'border-emerald-400/30 bg-emerald-400/10'
  if (type.includes('error') || type.includes('failed')) return 'border-rose-400/30 bg-rose-400/10'
  if (type.includes('workspace')) return 'border-violet-400/30 bg-violet-400/10'
  return 'border-white/10 bg-slate-900/80'
}

export function LogPanel({ events }: LogPanelProps) {
  return (
    <section className="rounded-3xl border border-white/10 bg-white/5 p-5">
      <div className="mb-4 flex items-center justify-between">
        <h2 className="text-lg font-semibold text-white">Live log</h2>
        <span className="text-xs text-slate-400">{events.length} events</span>
      </div>
      <div className="max-h-[34rem] space-y-3 overflow-auto pr-1">
        {events.length === 0 ? (
          <div className="rounded-2xl border border-dashed border-white/10 px-4 py-6 text-sm text-slate-400">
            Start a run to see live events.
          </div>
        ) : (
          events.map((event, index) => (
            <article key={`${event.ts}-${index}`} className={`rounded-2xl border p-3 ${eventTone(event.type)}`}>
              <div className="mb-2 flex items-center justify-between gap-3 text-xs uppercase tracking-[0.16em] text-slate-400">
                <span>{event.type}</span>
                <span>{new Date(event.ts).toLocaleTimeString()}</span>
              </div>
              <pre className="overflow-x-auto whitespace-pre-wrap text-sm text-slate-100">
                {JSON.stringify(event, null, 2)}
              </pre>
            </article>
          ))
        )}
      </div>
    </section>
  )
}
