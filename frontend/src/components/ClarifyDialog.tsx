import { useEffect, useState } from 'react'

type ClarifyResult = {
  understood: boolean
  refined_goal: string
  questions: string[]
  assumptions: string[]
  summary: string
}

type ClarifyDialogProps = {
  goal: string
  /** When true, panel is shown and clarification runs automatically (no separate “start” step). */
  open: boolean
  /** Increment when user clicks Run so each attempt triggers a fresh clarify (StrictMode-safe). */
  clarifySession: number
  onConfirm: (refinedGoal: string) => void
  /** User backs out of the clarify flow without starting a run. */
  onAbort: () => void
}

export function ClarifyDialog({ goal, open, clarifySession, onConfirm, onAbort }: ClarifyDialogProps) {
  const [conversation, setConversation] = useState<{ role: string; content: string }[]>([])
  const [result, setResult] = useState<ClarifyResult | null>(null)
  const [loading, setLoading] = useState(false)
  const [answer, setAnswer] = useState('')
  const [error, setError] = useState<string | null>(null)

  async function clarify(conv: { role: string; content: string }[]) {
    setLoading(true)
    setError(null)
    try {
      const res = await fetch('/api/clarify', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ goal, conversation: conv.length > 0 ? conv : undefined }),
      })
      if (!res.ok) throw new Error(`clarify failed: ${res.status}`)
      const data = (await res.json()) as ClarifyResult
      setResult(data)
    } catch (err: unknown) {
      setResult(null)
      setError(err instanceof Error ? err.message : 'Unable to clarify the goal right now.')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (!open) {
      setConversation([])
      setResult(null)
      setError(null)
      setAnswer('')
      setLoading(false)
      return
    }
    void clarify([])
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, goal, clarifySession])

  function handleAnswer() {
    if (!answer.trim() || !result) return
    const newConv = [
      ...conversation,
      { role: 'user', content: goal },
      { role: 'assistant', content: 'Questions: ' + result.questions.join(' | ') },
      { role: 'user', content: answer.trim() },
    ]
    setConversation(newConv)
    setAnswer('')
    setResult(null)
    setError(null)
    void clarify(newConv)
  }

  function handleDefaults() {
    if (!result) return
    const newConv = [
      ...conversation,
      { role: 'user', content: goal },
      { role: 'assistant', content: 'Questions: ' + result.questions.join(' | ') },
      { role: 'user', content: 'Use reasonable defaults for all questions.' },
    ]
    setConversation(newConv)
    setResult(null)
    setError(null)
    void clarify(newConv)
  }

  function handleRetry() {
    void clarify(conversation)
  }

  if (!open) return null

  return (
    <div className="space-y-3 border-t border-white/10 pt-4">
      <div className="flex items-center justify-between gap-2">
        <div>
          <div className="text-sm font-medium text-cyan-300">Goal Clarification (Required)</div>
          <div className="text-xs text-slate-500">
            Complete this step before running; it is unrelated to the Activity / Workspace tabs below.
          </div>
        </div>
        <button
          type="button"
          className="shrink-0 rounded-full border border-white/10 px-3 py-1.5 text-xs text-slate-400 transition hover:border-white/20 hover:text-slate-200"
          onClick={onAbort}
          disabled={loading}
        >
          Back to edit goal
        </button>
      </div>

      {error && (
        <div className="space-y-3 rounded-2xl border border-rose-400/20 bg-rose-400/5 p-4">
          <div className="text-sm font-medium text-rose-300">Clarification service unavailable</div>
          <p className="text-sm text-slate-300">
            {error}. Please retry, or go back to edit your goal text; you can’t start a run until clarification
            is completed.
          </p>
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              className="rounded-xl bg-rose-400/15 px-3 py-2 text-sm font-medium text-rose-200 transition hover:bg-rose-400/25"
              onClick={handleRetry}
            >
              Retry
            </button>
            <button
              type="button"
              className="rounded-xl border border-white/10 px-3 py-2 text-sm text-slate-400 transition hover:border-white/20"
              onClick={onAbort}
            >
              Back to edit goal
            </button>
          </div>
        </div>
      )}

      {loading && !error && (
        <div className="flex items-center gap-3 rounded-2xl border border-cyan-400/20 bg-cyan-400/5 p-4">
          <div className="h-4 w-4 animate-spin rounded-full border-2 border-cyan-400 border-t-transparent" />
          <span className="text-sm text-cyan-300">Understanding your goal…</span>
        </div>
      )}

      {!loading && !error && result?.understood && (
        <div className="space-y-3 rounded-2xl border border-emerald-400/20 bg-emerald-400/5 p-4">
          <div className="flex items-center gap-2">
            <span className="text-emerald-400">✓</span>
            <span className="text-sm font-medium text-emerald-300">Goal understood</span>
          </div>
          {result.summary && <p className="text-sm text-slate-300">{result.summary}</p>}
          {result.assumptions.length > 0 && (
            <div>
              <div className="mb-1 text-xs font-medium uppercase tracking-widest text-slate-500">Assumptions</div>
              <ul className="space-y-0.5 text-sm text-slate-400">
                {result.assumptions.filter(Boolean).map((a, i) => (
                  <li key={i} className="flex gap-1.5">
                    <span className="text-slate-600">•</span> {a}
                  </li>
                ))}
              </ul>
            </div>
          )}
          <button
            type="button"
            className="rounded-full bg-emerald-400/20 px-4 py-2 text-sm font-medium text-emerald-300 transition hover:bg-emerald-400/30"
            onClick={() => onConfirm(result.refined_goal || goal)}
          >
            Use refined goal and start running
          </button>
        </div>
      )}

      {!loading && !error && result && !result.understood && (
        <div className="space-y-3 rounded-2xl border border-amber-400/20 bg-amber-400/5 p-4">
          <div className="text-sm font-medium text-amber-300">Please answer before starting:</div>
          <ol className="space-y-1.5">
            {result.questions.map((q, i) => (
              <li key={i} className="flex gap-2 text-sm text-slate-300">
                <span className="flex-shrink-0 font-medium text-amber-400">{i + 1}.</span>
                {q}
              </li>
            ))}
          </ol>
          <div className="flex flex-col gap-2 sm:flex-row sm:flex-wrap">
            <input
              className="min-w-0 flex-1 rounded-xl border border-white/10 bg-slate-950/70 px-3 py-2 text-sm text-slate-100 outline-none placeholder:text-slate-500"
              placeholder="Answer here…"
              value={answer}
              onChange={(e) => setAnswer(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleAnswer()}
            />
            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                className="rounded-xl bg-amber-400/20 px-3 py-2 text-sm font-medium text-amber-300 transition hover:bg-amber-400/30"
                onClick={handleAnswer}
                disabled={!answer.trim()}
              >
                Submit answer
              </button>
              <button
                type="button"
                className="rounded-xl border border-white/10 px-3 py-2 text-sm text-slate-400 transition hover:border-white/20"
                onClick={handleDefaults}
              >
                Use all default assumptions
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
