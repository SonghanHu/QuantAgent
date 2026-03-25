import { useCallback, useRef, useState } from 'react'

type ChatMessage = { role: 'user' | 'assistant'; content: string }

type PostRunChatProps = {
  runId: string
  /** Original goal from run_start — helps the model even if artifacts are thin */
  runGoal?: string
}

export function PostRunChat({ runId, runGoal }: PostRunChatProps) {
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const bottomRef = useRef<HTMLDivElement>(null)

  const scrollToBottom = useCallback(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [])

  async function send() {
    const text = input.trim()
    if (!text || loading) return
    setError(null)
    const nextMessages: ChatMessage[] = [...messages, { role: 'user', content: text }]
    setMessages(nextMessages)
    setInput('')
    setLoading(true)
    try {
      const res = await fetch(`/api/run/${runId}/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          messages: nextMessages.map((m) => ({ role: m.role, content: m.content })),
          goal: runGoal || undefined,
        }),
      })
      const data = (await res.json().catch(() => ({}))) as {
        reply?: string
        detail?: string | Array<{ msg?: string }>
      }
      if (!res.ok) {
        const d = data.detail
        const msg =
          typeof d === 'string'
            ? d
            : Array.isArray(d)
              ? d.map((x) => x.msg ?? JSON.stringify(x)).join('; ')
              : `Chat failed (${res.status})`
        throw new Error(msg)
      }
      const reply = data.reply ?? ''
      setMessages((prev) => [...prev, { role: 'assistant', content: reply }])
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Chat request failed')
      setMessages((prev) => prev.slice(0, -1))
    } finally {
      setLoading(false)
      setTimeout(scrollToBottom, 0)
    }
  }

  return (
    <div className="mt-6 rounded-2xl border border-violet-400/20 bg-violet-950/20 p-4">
      <div className="mb-3 flex items-center justify-between gap-2">
        <h3 className="text-base font-semibold text-white">Ask about this run</h3>
        <span className="text-xs uppercase tracking-widest text-slate-500">{runId}</span>
      </div>
      <p className="mb-3 text-sm text-slate-400">
        Follow-up questions use the same workspace context as the final report (artifacts, evaluation, backtest
        summary, etc.). Not a substitute for re-running the pipeline with new data.
      </p>

      <div className="max-h-72 space-y-3 overflow-y-auto rounded-xl border border-white/[0.06] bg-slate-950/50 p-3 text-sm">
        {messages.length === 0 && (
          <p className="text-slate-500">e.g. &ldquo;Why did Sharpe drop in the last year?&rdquo; or &ldquo;What
            assumptions were in the feature plan?&rdquo;</p>
        )}
        {messages.map((m, i) => (
          <div
            key={i}
            className={
              m.role === 'user'
                ? 'ml-4 rounded-lg border border-slate-700/80 bg-slate-800/60 px-3 py-2 text-slate-200'
                : 'mr-4 rounded-lg border border-violet-500/20 bg-violet-950/30 px-3 py-2 text-slate-300'
            }
          >
            <div className="mb-1 text-xs font-medium uppercase tracking-wider text-slate-500">
              {m.role === 'user' ? 'You' : 'Assistant'}
            </div>
            <div className="whitespace-pre-wrap leading-relaxed">{m.content}</div>
          </div>
        ))}
        {loading && (
          <div className="flex items-center gap-2 text-slate-500">
            <div className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-violet-400 border-t-transparent" />
            Thinking…
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      {error && (
        <div className="mt-2 rounded-lg border border-rose-500/20 bg-rose-950/30 px-3 py-2 text-sm text-rose-200">
          {error}
        </div>
      )}

      <div className="mt-3 flex gap-2">
        <textarea
          className="min-h-[44px] flex-1 resize-y rounded-xl border border-white/10 bg-slate-900/80 px-3 py-2 text-sm text-slate-100 placeholder:text-slate-600 focus:border-violet-500/40 focus:outline-none"
          placeholder="Type a follow-up question…"
          rows={2}
          value={input}
          disabled={loading}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault()
              void send()
            }
          }}
        />
        <button
          type="button"
          disabled={loading || !input.trim()}
          className="self-end rounded-xl border border-violet-500/30 bg-violet-600/20 px-4 py-2 text-sm font-medium text-violet-100 transition hover:bg-violet-600/30 disabled:opacity-40"
          onClick={() => void send()}
        >
          Send
        </button>
      </div>
    </div>
  )
}
