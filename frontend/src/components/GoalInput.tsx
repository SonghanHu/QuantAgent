import type { ReactNode } from 'react'

type GoalInputProps = {
  goal: string
  isRunning: boolean
  /** True while mandatory clarification panel is open (before run starts). */
  isClarifying?: boolean
  onGoalChange: (value: string) => void
  onSubmit: () => void
  /** Rendered inside the same card below the goal (e.g. mandatory ClarifyDialog). */
  footer?: ReactNode
}

export function GoalInput({
  goal,
  isRunning,
  isClarifying = false,
  onGoalChange,
  onSubmit,
  footer,
}: GoalInputProps) {
  const locked = isRunning || isClarifying
  return (
    <section className="rounded-3xl border border-white/10 bg-white/5 p-5 shadow-2xl shadow-black/20 backdrop-blur">
      <div className="mb-3 flex items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold text-white">QuantAgent Dashboard</h1>
          <p className="text-base text-slate-300">Multi-agent quant research: search, analyze, engineer features & alphas, train, backtest, and evaluate.</p>
        </div>
        <button
          className="rounded-full bg-cyan-400 px-5 py-2.5 text-base font-semibold text-slate-950 transition hover:bg-cyan-300 disabled:cursor-not-allowed disabled:opacity-60"
          disabled={locked || !goal.trim()}
          onClick={onSubmit}
        >
          {isRunning ? 'Running…' : isClarifying ? 'Clarifying…' : 'Run agent'}
        </button>
      </div>
      <textarea
        className="min-h-32 w-full rounded-2xl border border-white/10 bg-slate-950/70 px-4 py-3.5 text-base text-slate-100 outline-none ring-0 placeholder:text-slate-500 disabled:cursor-not-allowed disabled:opacity-80"
        placeholder="Describe the research task..."
        value={goal}
        readOnly={isClarifying}
        onChange={(event) => onGoalChange(event.target.value)}
        onKeyDown={(event) => {
          if ((event.metaKey || event.ctrlKey) && event.key === 'Enter' && !locked && goal.trim()) {
            event.preventDefault()
            onSubmit()
          }
        }}
      />
      <div className="mt-2 text-sm text-slate-500">
        {isClarifying
          ? 'Clarification is in progress. The goal is temporarily locked. When done, click "Use refined goal and start running".'
          : 'Press `Cmd/Ctrl + Enter` to enter the required goal clarification first, then start the task.'}
      </div>
      {footer}
    </section>
  )
}
