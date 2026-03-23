type GoalInputProps = {
  goal: string
  isRunning: boolean
  onGoalChange: (value: string) => void
  onSubmit: () => void
}

export function GoalInput({ goal, isRunning, onGoalChange, onSubmit }: GoalInputProps) {
  return (
    <section className="rounded-3xl border border-white/10 bg-white/5 p-5 shadow-2xl shadow-black/20 backdrop-blur">
      <div className="mb-3 flex items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold text-white">Real-time Agent Dashboard</h1>
          <p className="text-sm text-slate-300">Run the research agent and watch each step stream into the UI.</p>
        </div>
        <button
          className="rounded-full bg-cyan-400 px-5 py-2 text-sm font-semibold text-slate-950 transition hover:bg-cyan-300 disabled:cursor-not-allowed disabled:opacity-60"
          disabled={isRunning || !goal.trim()}
          onClick={onSubmit}
        >
          {isRunning ? 'Running…' : 'Run agent'}
        </button>
      </div>
      <textarea
        className="min-h-28 w-full rounded-2xl border border-white/10 bg-slate-950/70 px-4 py-3 text-sm text-slate-100 outline-none ring-0 placeholder:text-slate-500"
        placeholder="Describe the research task..."
        value={goal}
        onChange={(event) => onGoalChange(event.target.value)}
      />
    </section>
  )
}
