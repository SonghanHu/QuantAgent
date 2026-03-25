export type AgentEvent = {
  type: string
  ts: string
  run_id?: string
  [key: string]: unknown
}

export type ArtifactSummary = {
  kind: string
  description: string
  shape?: number[]
}

export type AgentScriptSummary = {
  id: string
  filename: string
  label: string
  size_bytes?: number
}

export type WorkspaceManifest = {
  run_id: string
  workspace_dir: string
  summary: string
  artifacts: Record<string, ArtifactSummary>
  agent_scripts?: AgentScriptSummary[]
}

export type EquityVizTrade = {
  index: number
  date: string
  side: string
  label: string
}

export type EquityVizBenchmark = {
  label: string
  equity: number[]
}

export type EquityVizPayload = {
  version?: number
  dates: string[]
  equity: number[]
  trades: EquityVizTrade[]
  /** Optional benchmark equity series (same length as equity), for chart overlay */
  benchmarks?: EquityVizBenchmark[]
}

export function isEquityVizPayload(x: unknown): x is EquityVizPayload {
  if (!x || typeof x !== 'object') return false
  const o = x as Record<string, unknown>
  if (!Array.isArray(o.dates) || !Array.isArray(o.equity) || !Array.isArray(o.trades)) return false
  const n = o.dates.length
  if (!(n === o.equity.length && n > 1)) return false
  if (o.benchmarks !== undefined) {
    if (!Array.isArray(o.benchmarks)) return false
    for (const raw of o.benchmarks) {
      if (!raw || typeof raw !== 'object') return false
      const b = raw as Record<string, unknown>
      if (typeof b.label !== 'string' || !Array.isArray(b.equity)) return false
      if (b.equity.length !== n) return false
    }
  }
  return true
}

export type ArtifactPreview =
  | {
      artifact_name: string
      kind: 'json'
      content: unknown
    }
  | {
      artifact_name: string
      kind: 'dataframe'
      shape: number[]
      columns: string[]
      preview_rows: Record<string, unknown>[]
    }
  | {
      artifact_name: string
      kind: 'text'
      language?: string
      content: string
    }
  | {
      artifact_name: string
      kind: 'image'
      url: string
    }
