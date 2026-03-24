import { useState } from 'react'

type ClarifyResult = {
  understood: boolean
  refined_goal: string
  questions: string[]
  assumptions: string[]
  summary: string
}

type ClarifyDialogProps = {
  goal: string
  onConfirm: (refinedGoal: string) => void
  onSkip: () => void
}

export function ClarifyDialog({ goal, onConfirm, onSkip }: ClarifyDialogProps) {
  const [conversation, setConversation] = useState<{ role: string; content: string }[]>([])
  const [result, setResult] = useState<ClarifyResult | null>(null)
  const [loading, setLoading] = useState(false)
  const [answer, setAnswer] = useState('')
  const [started, setStarted] = useState(false)

  async function clarify(conv: { role: string; content: string }[]) {
    setLoading(true)
    try {
      const res = await fetch('/api/clarify', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ goal, conversation: conv.length > 0 ? conv : undefined }),
      })
      if (!res.ok) throw new Error(`clarify failed: ${res.status}`)
      const data = (await res.json()) as ClarifyResult
      setResult(data)
    } catch {
      onSkip()
    } finally {
      setLoading(false)
    }
  }

  function handleStart() {
    setStarted(true)
    void clarify([])
  }

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
    void clarify(newConv)
  }

  if (!started) {
    return (
      <div className="rounded-2xl border border-cyan-400/20 bg-cyan-400/5 p-4">
        <div className="flex items-center justify-between gap-3">
          <div>
            <div className="text-sm font-medium text-cyan-300">Pre-run clarification</div>
            <div className="text-xs text-slate-400">Let the agent understand your goal before executing</div>
          </div>
          <div className="flex gap-2">
            <button
              className="rounded-full border border-white/10 px-3 py-1.5 text-xs text-slate-300 transition hover:border-white/20"
              onClick={onSkip}
            >
              Skip
            </button>
            <button
              className="rounded-full bg-cyan-400/20 px-3 py-1.5 text-xs font-medium text-cyan-300 transition hover:bg-cyan-400/30"
              onClick={handleStart}
            >
              Clarify goal
            </button>
          </div>
        </div>
      </div>
    )
  }

  if (loading) {
    return (
      <div className="rounded-2xl border border-cyan-400/20 bg-cyan-400/5 p-4">
        <div className="flex items-center gap-3">
          <div className="h-4 w-4 animate-spin rounded-full border-2 border-cyan-400 border-t-transparent" />
          <span className="text-sm text-cyan-300">Analyzing your goal...</span>
        </div>
      </div>
    )
  }

  if (!result) return null

  if (result.understood) {
    return (
      <div className="space-y-3 rounded-2xl border border-emerald-400/20 bg-emerald-400/5 p-4">
        <div className="flex items-center gap-2">
          <span className="text-emerald-400">✓</span>
          <span className="text-sm font-medium text-emerald-300">Goal understood</span>
        </div>
        {result.summary && (
          <p className="text-sm text-slate-300">{result.summary}</p>
        )}
        {result.assumptions.length > 0 && (
          <div>
            <div className="mb-1 text-[10px] font-medium uppercase tracking-widest text-slate-500">Assumptions</div>
            <ul className="space-y-0.5 text-xs text-slate-400">
              {result.assumptions.filter(Boolean).map((a, i) => (
                <li key={i} className="flex gap-1.5">
                  <span className="text-slate-600">•</span> {a}
                </li>
              ))}
            </ul>
          </div>
        )}
        <div className="flex gap-2 pt-1">
          <button
            className="rounded-full bg-emerald-400/20 px-4 py-1.5 text-xs font-medium text-emerald-300 transition hover:bg-emerald-400/30"
            onClick={() => onConfirm(result.refined_goal || goal)}
          >
            Proceed with refined goal
          </button>
          <button
            className="rounded-full border border-white/10 px-3 py-1.5 text-xs text-slate-400 transition hover:border-white/20"
            onClick={onSkip}
          >
            Use original goal
          </button>
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-3 rounded-2xl border border-amber-400/20 bg-amber-400/5 p-4">
      <div className="text-sm font-medium text-amber-300">A few questions before starting:</div>
      <ol className="space-y-1.5">
        {result.questions.map((q, i) => (
          <li key={i} className="flex gap-2 text-sm text-slate-300">
            <span className="flex-shrink-0 font-medium text-amber-400">{i + 1}.</span>
            {q}
          </li>
        ))}
      </ol>
      <div className="flex gap-2">
        <input
          className="flex-1 rounded-xl border border-white/10 bg-slate-950/70 px-3 py-2 text-sm text-slate-100 outline-none placeholder:text-slate-500"
          placeholder="Your answers..."
          value={answer}
          onChange={(e) => setAnswer(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && handleAnswer()}
        />
        <button
          className="rounded-xl bg-amber-400/20 px-3 py-2 text-xs font-medium text-amber-300 transition hover:bg-amber-400/30"
          onClick={handleAnswer}
          disabled={!answer.trim()}
        >
          Answer
        </button>
        <button
          className="rounded-xl border border-white/10 px-3 py-2 text-xs text-slate-400 transition hover:border-white/20"
          onClick={handleDefaults}
        >
          Use defaults
        </button>
        <button
          className="rounded-xl border border-white/10 px-3 py-2 text-xs text-slate-500 transition hover:border-white/20"
          onClick={onSkip}
        >
          Skip
        </button>
      </div>
    </div>
  )
}
