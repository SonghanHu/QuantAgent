import type { AgentEvent } from '../types'

/**
 * After replan or retries, raw `subtask_done` count can exceed `decompose_done.total_subtasks`.
 * Progress should reflect the **current** topo pass: events after the last `workflow_topo_order`,
 * with at most one terminal outcome per `subtask_id` (latest `subtask_done` wins).
 */
export function computePipelineProgress(events: AgentEvent[]): {
  total: number
  /** Distinct subtask ids with a `subtask_done` in the current segment */
  completed: number
  replanRound: number
  /** Latest status per subtask id in the current segment */
  terminalBySubtask: Map<number, string>
} {
  let lastTopoIdx = -1
  for (let i = 0; i < events.length; i++) {
    if (events[i].type === 'workflow_topo_order') lastTopoIdx = i
  }
  const window = lastTopoIdx >= 0 ? events.slice(lastTopoIdx) : events

  const terminalBySubtask = new Map<number, string>()
  for (const e of window) {
    if (e.type === 'subtask_done' && typeof e.subtask_id === 'number') {
      terminalBySubtask.set(e.subtask_id, String(e.status ?? ''))
    }
  }

  const lastTopo = [...events].reverse().find((e) => e.type === 'workflow_topo_order')
  const replanRound =
    lastTopo && typeof lastTopo.replan_round === 'number' ? (lastTopo.replan_round as number) : 0

  let total = 0
  if (lastTopo && Array.isArray(lastTopo.order)) {
    total = (lastTopo.order as unknown[]).length
  }
  const decompose = events.find((e) => e.type === 'decompose_done')
  if (total === 0 && typeof decompose?.total_subtasks === 'number') {
    total = decompose.total_subtasks as number
  }
  const lastStart = [...events].reverse().find((e) => e.type === 'subtask_start')
  if (total === 0 && typeof lastStart?.total === 'number') {
    total = lastStart.total as number
  }

  return {
    total,
    completed: terminalBySubtask.size,
    replanRound,
    terminalBySubtask,
  }
}
