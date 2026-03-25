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

export type EquityVizPayload = {
  version?: number
  dates: string[]
  equity: number[]
  trades: EquityVizTrade[]
}

export function isEquityVizPayload(x: unknown): x is EquityVizPayload {
  if (!x || typeof x !== 'object') return false
  const o = x as Record<string, unknown>
  if (!Array.isArray(o.dates) || !Array.isArray(o.equity) || !Array.isArray(o.trades)) return false
  return o.dates.length === o.equity.length && o.dates.length > 1
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
