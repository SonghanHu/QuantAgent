type ProgressBarProps = {
  completed: number
  total: number
  currentStep: string
  connectionStatus: string
}

export function ProgressBar({ completed, total, currentStep, connectionStatus }: ProgressBarProps) {
  const percent = total > 0 ? Math.round((completed / total) * 100) : 0

  return (
    <section className="rounded-3xl border border-white/10 bg-white/5 p-5">
      <div className="mb-3 flex items-center justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold text-white">Progress</h2>
          <p className="text-sm text-slate-300">{currentStep || 'Waiting for run to start'}</p>
        </div>
        <div className="rounded-full border border-white/10 bg-slate-900/80 px-3 py-1 text-xs text-slate-300">
          {connectionStatus}
        </div>
      </div>
      <div className="h-3 overflow-hidden rounded-full bg-slate-900/90">
        <div
          className="h-full rounded-full bg-gradient-to-r from-cyan-400 via-sky-400 to-indigo-400 transition-all duration-500"
          style={{ width: `${percent}%` }}
        />
      </div>
      <div className="mt-3 flex items-center justify-between text-sm text-slate-300">
        <span>
          {completed} / {total || '?'} subtasks
        </span>
        <span>{percent}%</span>
      </div>
    </section>
  )
}
