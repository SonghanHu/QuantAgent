import { useMemo } from 'react'

import type { AgentEvent } from '../types'

type WorkflowGraphProps = {
  events: AgentEvent[]
}

type PipelineNode = {
  id: number
  title: string
  description: string
  dependencies: number[]
  status: 'pending' | 'running' | 'done' | 'error' | 'skipped'
  toolName?: string
  toolSource?: string
  resultSummary?: string
  artifacts: string[]
  subRounds: SubRound[]
}

type SubRound = {
  round: number
  stage: string
  ready?: boolean
  reasoning?: string
}

const TOOL_STYLE: Record<string, { dot: string; badge: string; label: string }> = {
  web_search: { dot: 'bg-teal-400', badge: 'bg-teal-400/15 text-teal-300 ring-teal-400/30', label: 'Web Search' },
  load_data: { dot: 'bg-sky-400', badge: 'bg-sky-400/15 text-sky-300 ring-sky-400/30', label: 'Data Loader' },
  run_data_analyst: { dot: 'bg-amber-400', badge: 'bg-amber-400/15 text-amber-300 ring-amber-400/30', label: 'Data Analyst' },
  run_data_analysis: { dot: 'bg-amber-400', badge: 'bg-amber-400/15 text-amber-300 ring-amber-400/30', label: 'EDA Skill' },
  build_features: { dot: 'bg-violet-400', badge: 'bg-violet-400/15 text-violet-300 ring-violet-400/30', label: 'Feature Eng.' },
  build_alphas: { dot: 'bg-fuchsia-400', badge: 'bg-fuchsia-400/15 text-fuchsia-300 ring-fuchsia-400/30', label: 'Alpha Eng.' },
  train_model: { dot: 'bg-emerald-400', badge: 'bg-emerald-400/15 text-emerald-300 ring-emerald-400/30', label: 'Model Trainer' },
  run_backtest: { dot: 'bg-cyan-400', badge: 'bg-cyan-400/15 text-cyan-300 ring-cyan-400/30', label: 'Backtester' },
  evaluate_strategy: { dot: 'bg-rose-400', badge: 'bg-rose-400/15 text-rose-300 ring-rose-400/30', label: 'Evaluator' },
}

const DEFAULT_STYLE = { dot: 'bg-slate-400', badge: 'bg-slate-400/15 text-slate-300 ring-slate-400/30', label: 'Agent' }

function getToolStyle(toolName?: string) {
  if (!toolName) return DEFAULT_STYLE
  return TOOL_STYLE[toolName] ?? DEFAULT_STYLE
}

const STATUS_ICON: Record<string, string> = {
  pending: '○',
  running: '◉',
  done: '✓',
  error: '✗',
  skipped: '⏭',
}

function derivePipeline(events: AgentEvent[]): { nodes: PipelineNode[]; topoOrder: number[] } {
  const decompose = events.find((e) => e.type === 'decompose_done')
  if (!decompose) return { nodes: [], topoOrder: [] }

  const subtasks = decompose.subtasks as Array<{
    id: number
    title: string
    description: string
    dependencies: number[]
  }>

  const nodeMap = new Map<number, PipelineNode>()
  for (const st of subtasks) {
    nodeMap.set(st.id, {
      id: st.id,
      title: st.title,
      description: st.description,
      dependencies: st.dependencies,
      status: 'pending',
      artifacts: [],
      subRounds: [],
    })
  }

  let currentSubtaskId: number | null = null

  for (const ev of events) {
    if (ev.type === 'subtask_start') {
      currentSubtaskId = ev.subtask_id as number
      const node = nodeMap.get(currentSubtaskId)
      if (node) node.status = 'running'
    } else if (ev.type === 'subtask_tool_resolved') {
      const node = nodeMap.get(ev.subtask_id as number)
      if (node) {
        node.toolName = ev.tool_name as string
        node.toolSource = ev.source as string
      }
    } else if (ev.type === 'subtask_done') {
      const node = nodeMap.get(ev.subtask_id as number)
      if (node) {
        node.status = ev.status === 'ok' ? 'done' : ev.status === 'skipped' ? 'skipped' : 'error'
        node.resultSummary = ev.result_summary as string
      }
    } else if (ev.type === 'workspace_update' && currentSubtaskId !== null) {
      const node = nodeMap.get(currentSubtaskId)
      const artifactName = ev.artifact_name as string
      if (node && artifactName && !node.artifacts.includes(artifactName)) {
        node.artifacts.push(artifactName)
      }
    } else if (ev.type === 'data_analyst_round' && currentSubtaskId !== null) {
      const node = nodeMap.get(currentSubtaskId)
      if (node) {
        node.subRounds.push({
          round: ev.round as number,
          stage: ev.stage as string,
          ready: ev.ready as boolean | undefined,
          reasoning: ev.reasoning as string | undefined,
        })
      }
    }
  }

  const topoEvent = events.find((e) => e.type === 'workflow_topo_order')
  const topoOrder = (topoEvent?.order as number[]) ?? subtasks.map((s) => s.id)

  return { nodes: Array.from(nodeMap.values()), topoOrder }
}

function ArtifactBadge({ name }: { name: string }) {
  const icons: Record<string, string> = {
    raw_data: '📊',
    search_context: '🔍',
    feature_plan: '📋',
    alpha_plan: '🧬',
    engineered_data: '⚙️',
    model_output: '🧠',
    backtest_results: '📈',
    evaluation: '✅',
    final_report: '📝',
  }
  return (
    <span className="inline-flex items-center gap-1 rounded-full bg-indigo-400/10 px-2.5 py-1 text-xs text-indigo-300 ring-1 ring-indigo-400/20">
      {icons[name] ?? '📄'} {name}
    </span>
  )
}

function SubRoundIndicator({ rounds }: { rounds: SubRound[] }) {
  if (rounds.length === 0) return null
  const judgeRounds = rounds.filter((r) => r.stage === 'judge_done')
  const totalRounds = Math.max(...rounds.map((r) => r.round), 0)
  const readyRound = judgeRounds.find((r) => r.ready)

  return (
    <div className="mt-2 rounded-xl border border-amber-400/20 bg-amber-400/5 px-3 py-2">
      <div className="mb-1.5 text-xs font-medium uppercase tracking-widest text-amber-300/70">
        Sub-agent loop · {totalRounds} round{totalRounds > 1 ? 's' : ''}
      </div>
      <div className="flex gap-1">
        {Array.from({ length: totalRounds }, (_, i) => {
          const round = i + 1
          const judge = judgeRounds.find((r) => r.round === round)
          const isReady = judge?.ready
          const isFailed = !judge
          return (
            <div
              key={round}
              className={`group relative flex h-6 w-6 items-center justify-center rounded-md text-xs font-bold ${
                isReady
                  ? 'bg-emerald-400/20 text-emerald-300'
                  : isFailed
                    ? 'bg-slate-400/15 text-slate-500'
                    : 'bg-amber-400/20 text-amber-300'
              }`}
            >
              {round}
              {judge?.reasoning && (
                <div className="pointer-events-none absolute bottom-full left-1/2 z-20 mb-2 hidden w-56 -translate-x-1/2 rounded-lg border border-white/10 bg-slate-900 p-2 text-sm font-normal leading-snug text-slate-300 shadow-xl group-hover:block">
                  {judge.reasoning.slice(0, 200)}
                </div>
              )}
            </div>
          )
        })}
      </div>
      {readyRound && (
        <div className="mt-1 text-xs text-emerald-400/80">
          ✓ Ready at round {readyRound.round}
        </div>
      )}
      {!readyRound && totalRounds > 0 && (
        <div className="mt-1 text-xs text-amber-400/60">
          Hit max rounds — forced feature plan
        </div>
      )}
    </div>
  )
}

export function WorkflowGraph({ events }: WorkflowGraphProps) {
  const { nodes, topoOrder } = useMemo(() => derivePipeline(events), [events])

  if (nodes.length === 0) {
    return (
      <section className="rounded-3xl border border-white/10 bg-white/5 p-5">
        <h2 className="text-lg font-semibold text-white">Agent Workflow</h2>
        <p className="mt-1 text-base text-slate-400">The task decomposition and agent pipeline appear here once the run starts.</p>
      </section>
    )
  }

  const nodeMap = new Map(nodes.map((n) => [n.id, n]))
  const orderedNodes = topoOrder.map((id) => nodeMap.get(id)).filter(Boolean) as PipelineNode[]

  const toolGroups = new Map<string, number>()
  for (const n of orderedNodes) {
    if (n.toolName) {
      toolGroups.set(n.toolName, (toolGroups.get(n.toolName) ?? 0) + 1)
    }
  }

  return (
    <section className="rounded-3xl border border-white/10 bg-white/5 p-5">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold text-white">Agent Workflow</h2>
          <p className="text-base text-slate-400">
            {orderedNodes.length} subtasks · {toolGroups.size} agents collaborating
          </p>
        </div>
        <div className="flex flex-wrap gap-1.5">
          {Array.from(toolGroups.entries()).map(([tool, count]) => {
            const style = getToolStyle(tool)
            return (
              <span
                key={tool}
                className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1.5 text-sm ring-1 ${style.badge}`}
              >
                <span className={`h-2 w-2 rounded-full ${style.dot}`} />
                {style.label} ×{count}
              </span>
            )
          })}
        </div>
      </div>

      {/* Horizontal mini-pipeline */}
      <div className="mb-5 overflow-x-auto pb-2">
        <div className="flex items-center gap-0 px-2" style={{ minWidth: orderedNodes.length * 56 }}>
          {orderedNodes.map((node, idx) => {
            const style = getToolStyle(node.toolName)
            return (
              <div key={node.id} className="flex items-center">
                <div className="group relative flex flex-col items-center" style={{ width: 48 }}>
                  <div
                    className={`flex h-7 w-7 items-center justify-center rounded-full text-xs font-bold ring-2 ${
                      node.status === 'done'
                        ? `${style.dot} text-slate-950 ring-white/20`
                        : node.status === 'running'
                          ? `${style.dot} animate-pulse text-slate-950 ring-white/40`
                          : node.status === 'error'
                            ? 'bg-rose-500 text-white ring-rose-400/40'
                            : node.status === 'skipped'
                              ? 'bg-slate-600 text-slate-400 ring-slate-500/30'
                              : 'bg-slate-700 text-slate-400 ring-white/10'
                    }`}
                  >
                    {node.status === 'done' || node.status === 'error' || node.status === 'skipped'
                      ? STATUS_ICON[node.status]
                      : node.id}
                  </div>
                  <div className="mt-1 w-14 truncate text-center text-[11px] text-slate-500">
                    {node.title.slice(0, 6)}
                  </div>
                  <div className="pointer-events-none absolute bottom-full z-20 mb-2 hidden w-56 rounded-lg border border-white/10 bg-slate-900 p-2 text-sm text-slate-300 shadow-xl group-hover:block">
                    <div className="font-medium text-white">{node.title}</div>
                    {node.toolName && (
                      <div className={`mt-1 ${getToolStyle(node.toolName).badge.split(' ')[1]}`}>
                        {getToolStyle(node.toolName).label}
                      </div>
                    )}
                  </div>
                </div>
                {idx < orderedNodes.length - 1 && (
                  <div className="h-px w-2 bg-slate-700" />
                )}
              </div>
            )
          })}
        </div>
      </div>

      {/* Detailed node list */}
      <div className="relative space-y-0">
        {orderedNodes.map((node, idx) => {
          const style = getToolStyle(node.toolName)
          const statusColor =
            node.status === 'done'
              ? 'text-emerald-400'
              : node.status === 'running'
                ? 'text-cyan-400 animate-pulse'
                : node.status === 'error'
                  ? 'text-rose-400'
                  : node.status === 'skipped'
                    ? 'text-slate-500'
                    : 'text-slate-600'

          return (
            <div key={node.id} className="flex gap-4">
              {/* Left rail */}
              <div className="flex w-6 flex-shrink-0 flex-col items-center">
                <div className={`text-sm font-bold ${statusColor}`}>
                  {STATUS_ICON[node.status]}
                </div>
                {idx < orderedNodes.length - 1 && (
                  <div className="mt-1 w-px flex-1 bg-slate-700/60" />
                )}
              </div>

              {/* Node card */}
              <div className="mb-3 min-w-0 flex-1 rounded-2xl border border-white/[0.06] bg-slate-900/40 p-3">
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-bold text-slate-500">#{node.id}</span>
                      <span className="truncate text-base font-medium text-slate-100">
                        {node.title}
                      </span>
                    </div>
                    {node.dependencies.length > 0 && (
                      <div className="mt-0.5 text-sm text-slate-600">
                        depends on {node.dependencies.map((d) => `#${d}`).join(', ')}
                      </div>
                    )}
                  </div>
                  {node.toolName && (
                    <span
                      className={`inline-flex flex-shrink-0 items-center gap-1.5 rounded-full px-3 py-1.5 text-sm ring-1 ${style.badge}`}
                    >
                      <span className={`h-1.5 w-1.5 rounded-full ${style.dot}`} />
                      {style.label}
                    </span>
                  )}
                </div>

                {node.resultSummary && (
                  <div className="mt-1.5 text-sm text-slate-400">{node.resultSummary}</div>
                )}

                {node.artifacts.length > 0 && (
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    {node.artifacts.map((a) => (
                      <ArtifactBadge key={a} name={a} />
                    ))}
                  </div>
                )}

                <SubRoundIndicator rounds={node.subRounds} />
              </div>
            </div>
          )
        })}
      </div>
    </section>
  )
}
