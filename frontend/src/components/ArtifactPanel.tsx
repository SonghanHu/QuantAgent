import type { ArtifactPreview, WorkspaceManifest } from '../types'

type ArtifactPanelProps = {
  manifest: WorkspaceManifest | null
  selectedArtifact: string | null
  preview: ArtifactPreview | null
  isLoading: boolean
  onSelect: (artifactName: string) => void
}

export function ArtifactPanel({ manifest, selectedArtifact, preview, isLoading, onSelect }: ArtifactPanelProps) {
  const artifactEntries = Object.entries(manifest?.artifacts ?? {})

  return (
    <section className="rounded-3xl border border-white/10 bg-white/5 p-5">
      <div className="mb-4">
        <h2 className="text-lg font-semibold text-white">Workspace artifacts</h2>
        <p className="text-sm text-slate-300">{manifest?.summary ?? 'No workspace yet.'}</p>
      </div>
      <div className="grid gap-4 lg:grid-cols-[18rem_minmax(0,1fr)]">
        <div className="space-y-2">
          {artifactEntries.length === 0 ? (
            <div className="rounded-2xl border border-dashed border-white/10 px-4 py-6 text-sm text-slate-400">
              Artifacts appear here as tools write into the workspace.
            </div>
          ) : (
            artifactEntries.map(([name, meta]) => (
              <button
                key={name}
                className={`w-full rounded-2xl border px-4 py-3 text-left transition ${
                  selectedArtifact === name
                    ? 'border-cyan-400/50 bg-cyan-400/10'
                    : 'border-white/10 bg-slate-900/70 hover:border-white/20'
                }`}
                aria-pressed={selectedArtifact === name}
                onClick={() => onSelect(name)}
              >
                <div className="font-medium text-white">{name}</div>
                <div className="mt-1 text-xs text-slate-400">
                  {meta.kind}
                  {meta.shape ? ` · ${meta.shape.join(' x ')}` : ''}
                </div>
              </button>
            ))
          )}
        </div>
        <div className="rounded-2xl border border-white/10 bg-slate-950/70 p-4">
          {isLoading && selectedArtifact ? (
            <div className="space-y-3">
              <div className="flex items-center gap-3 text-sm text-cyan-300">
                <div className="h-4 w-4 animate-spin rounded-full border-2 border-cyan-400 border-t-transparent" />
                Loading `{selectedArtifact}`...
              </div>
              <div className="h-24 rounded-xl border border-dashed border-white/10 bg-slate-900/50" />
            </div>
          ) : !preview ? (
            <div className="text-sm text-slate-400">Select an artifact to preview it.</div>
          ) : preview.kind === 'json' ? (
            <pre className="max-h-[26rem] overflow-auto whitespace-pre-wrap text-sm text-slate-100">
              {JSON.stringify(preview.content, null, 2)}
            </pre>
          ) : (
            <div className="space-y-3">
              <div className="text-sm text-slate-300">
                Shape: {preview.shape.join(' x ')}
              </div>
              <div className="max-h-[26rem] overflow-auto rounded-xl border border-white/10">
                <table className="min-w-full text-left text-sm">
                  <thead className="sticky top-0 bg-slate-900/95 text-slate-300">
                    <tr>
                      {preview.preview_rows[0] &&
                        Object.keys(preview.preview_rows[0]).map((column) => (
                          <th key={column} className="border-b border-white/10 px-3 py-2 font-medium">
                            {column}
                          </th>
                        ))}
                    </tr>
                  </thead>
                  <tbody>
                    {preview.preview_rows.map((row, index) => (
                      <tr key={index} className="border-b border-white/5 text-slate-100">
                        {Object.entries(row).map(([column, value]) => (
                          <td key={column} className="px-3 py-2 align-top">
                            {typeof value === 'object' ? JSON.stringify(value) : String(value ?? '')}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </div>
      </div>
    </section>
  )
}
