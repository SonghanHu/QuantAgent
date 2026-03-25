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
