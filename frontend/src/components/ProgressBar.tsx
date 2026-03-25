type ProgressBarProps = {
  completed: number
  total: number
  currentStep: string
  connectionStatus: string
  /** e.g. replan round — explains why counts reset vs initial decomposition */
  phaseHint?: string
}

export function ProgressBar({ completed, total, currentStep, connectionStatus, phaseHint }: ProgressBarProps) {
  const safeTotal = total > 0 ? total : 0
  const safeDone = safeTotal > 0 ? Math.min(completed, safeTotal) : completed
  const percent = safeTotal > 0 ? Math.min(100, Math.round((safeDone / safeTotal) * 100)) : 0
  const connectionLabel =
    connectionStatus === 'open'
      ? 'Streaming'
      : connectionStatus === 'connecting'
        ? 'Connecting'
        : connectionStatus === 'closed'
          ? 'Disconnected'
          : connectionStatus === 'error'
            ? 'Connection error'
            : 'Idle'

  return (
    <section className="rounded-3xl border border-white/10 bg-white/5 p-5">
      <div className="mb-3 flex items-center justify-between gap-3">
        <div className="min-w-0">
          <h2 className="text-lg font-semibold text-white">Progress</h2>
          <p className="text-base text-slate-300">{currentStep || 'Waiting for run to start'}</p>
          {phaseHint ? <p className="mt-1 text-xs text-slate-500">{phaseHint}</p> : null}
        </div>
        <div className="rounded-full border border-white/10 bg-slate-900/80 px-3 py-1.5 text-sm text-slate-300">
          {connectionLabel}
        </div>
      </div>
      <div className="h-3 overflow-hidden rounded-full bg-slate-900/90">
        <div
          className="h-full rounded-full bg-gradient-to-r from-cyan-400 via-sky-400 to-indigo-400 transition-all duration-500"
          style={{ width: `${percent}%` }}
        />
      </div>
      <div className="mt-3 flex items-center justify-between text-base text-slate-300">
        <span>
          {safeDone} / {safeTotal || '?'} subtasks
        </span>
        <span>{percent}%</span>
      </div>
    </section>
  )
}
