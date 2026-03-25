import { useState } from 'react'

import { EquityVizPreview } from './EquityVizPreview'
import type { ArtifactPreview, WorkspaceManifest } from '../types'
import { isEquityVizPayload } from '../types'

type ArtifactPanelProps = {
  manifest: WorkspaceManifest | null
  selectedArtifact: string | null
  preview: ArtifactPreview | null
  isLoading: boolean
  onSelect: (artifactName: string) => void
  /** When true, parent will auto-load artifacts from workspace_update. */
  followLatest?: boolean
  onFollowLatestChange?: (value: boolean) => void
  /** Called when user picks an artifact manually (stops auto-follow until re-enabled). */
  onUserPickArtifact?: () => void
  sectionClassName?: string
}

export function ArtifactPanel({
  manifest,
  selectedArtifact,
  preview,
  isLoading,
  onSelect,
  followLatest = true,
  onFollowLatestChange,
  onUserPickArtifact,
  sectionClassName = '',
}: ArtifactPanelProps) {
  const [copied, setCopied] = useState(false)
  const artifactEntries = Object.entries(manifest?.artifacts ?? {})

  function handleSelect(name: string) {
    onUserPickArtifact?.()
    onSelect(name)
  }

  async function copyJson() {
    if (preview?.kind !== 'json') return
    try {
      await navigator.clipboard.writeText(JSON.stringify(preview.content, null, 2))
      setCopied(true)
      window.setTimeout(() => setCopied(false), 2000)
    } catch {
      setCopied(false)
    }
  }

  async function copyText() {
    if (preview?.kind !== 'text') return
    try {
      await navigator.clipboard.writeText(preview.content)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 2000)
    } catch {
      setCopied(false)
    }
  }

  function formatBytes(n: number | undefined) {
    if (n == null || Number.isNaN(n)) return ''
    if (n < 1024) return `${n} B`
    if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
    return `${(n / (1024 * 1024)).toFixed(1)} MB`
  }

  const agentScripts = manifest?.agent_scripts ?? []
  const hasArtifacts = artifactEntries.length > 0
  const hasScripts = agentScripts.length > 0
  const listIsEmpty = !hasArtifacts && !hasScripts

  return (
    <section
      className={`flex min-h-0 min-w-0 flex-col rounded-2xl border border-white/10 bg-white/5 p-4 ${sectionClassName}`}
    >
      <div className="mb-3 flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="text-base font-semibold text-white">Workspace</h2>
          <p className="mt-0.5 text-sm text-slate-400">{manifest?.summary ?? 'No workspace yet.'}</p>
        </div>
        {onFollowLatestChange && (
          <label className="flex cursor-pointer items-center gap-2 text-xs text-slate-400">
            <input
              type="checkbox"
              className="rounded border-white/20 bg-slate-900 text-cyan-500 focus:ring-cyan-500/40"
              checked={followLatest}
              onChange={(e) => onFollowLatestChange(e.target.checked)}
            />
            Follow latest artifact
          </label>
        )}
      </div>
      <div className="grid min-h-[min(52vh,520px)] flex-1 gap-4 lg:grid-cols-[220px_minmax(0,1fr)]">
        <div className="min-h-0 space-y-4 overflow-y-auto pr-1">
          {listIsEmpty ? (
            <div className="rounded-2xl border border-dashed border-white/10 px-4 py-6 text-sm text-slate-400">
              Artifacts and agent-generated scripts appear here as the run progresses.
            </div>
          ) : null}
          {hasArtifacts ? (
            <div className="space-y-1.5">
              <div className="px-1 text-[11px] font-medium uppercase tracking-wider text-slate-500">Artifacts</div>
              {artifactEntries.map(([name, meta]) => (
                <button
                  key={name}
                  className={`w-full rounded-xl border px-3 py-2.5 text-left transition ${
                    selectedArtifact === name
                      ? 'border-cyan-400/50 bg-cyan-400/10'
                      : 'border-white/10 bg-slate-900/70 hover:border-white/20'
                  }`}
                  aria-pressed={selectedArtifact === name}
                  onClick={() => handleSelect(name)}
                >
                  <div className="break-all text-sm font-medium text-white">{name}</div>
                  <div className="mt-0.5 text-xs text-slate-400">
                    {meta.kind}
                    {meta.shape ? ` · ${meta.shape.join('×')}` : ''}
                  </div>
                </button>
              ))}
            </div>
          ) : null}
          {hasScripts ? (
            <div className="space-y-1.5">
              <div className="px-1 text-[11px] font-medium uppercase tracking-wider text-slate-500">Agent scripts</div>
              {agentScripts.map((s) => {
                const key = `script:${s.id}`
                return (
                  <button
                    key={s.id}
                    className={`w-full rounded-xl border px-3 py-2.5 text-left transition ${
                      selectedArtifact === key
                        ? 'border-amber-400/45 bg-amber-400/10'
                        : 'border-white/10 bg-slate-900/70 hover:border-white/20'
                    }`}
                    aria-pressed={selectedArtifact === key}
                    onClick={() => handleSelect(key)}
                  >
                    <div className="text-sm font-medium text-amber-100/95">{s.label}</div>
                    <div className="mt-0.5 break-all text-xs text-slate-400">
                      {s.filename}
                      {s.size_bytes != null ? ` · ${formatBytes(s.size_bytes)}` : ''}
                    </div>
                  </button>
                )
              })}
            </div>
          ) : null}
        </div>
        <div className="flex min-h-0 min-w-0 flex-col rounded-xl border border-white/10 bg-slate-950/70">
          <div className="flex shrink-0 flex-wrap items-center justify-between gap-2 border-b border-white/10 px-3 py-2">
            <span className="truncate text-xs font-medium text-slate-400">
              {selectedArtifact ? `Preview · ${selectedArtifact}` : 'Preview'}
            </span>
            {preview?.kind === 'json' && (
              <button
                type="button"
                className="rounded-lg border border-white/10 px-2 py-1 text-xs text-slate-300 hover:bg-white/5"
                onClick={() => void copyJson()}
              >
                {copied ? 'Copied' : 'Copy JSON'}
              </button>
            )}
            {preview?.kind === 'text' && (
              <button
                type="button"
                className="rounded-lg border border-white/10 px-2 py-1 text-xs text-slate-300 hover:bg-white/5"
                onClick={() => void copyText()}
              >
                {copied ? 'Copied' : 'Copy code'}
              </button>
            )}
          </div>
          <div className="min-h-0 flex-1 overflow-auto p-3">
            {isLoading && selectedArtifact ? (
              <div className="space-y-3">
                <div className="flex items-center gap-3 text-sm text-cyan-300">
                  <div className="h-4 w-4 animate-spin rounded-full border-2 border-cyan-400 border-t-transparent" />
                  Loading…
                </div>
                <div className="h-32 rounded-lg border border-dashed border-white/10 bg-slate-900/50" />
              </div>
            ) : !preview ? (
              <div className="text-sm leading-relaxed text-slate-500">
                Select an artifact on the left, or enable <strong className="text-slate-400">Follow latest artifact</strong>{' '}
                to open new files as they are written.
              </div>
            ) : preview.kind === 'json' && isEquityVizPayload(preview.content) ? (
              <EquityVizPreview payload={preview.content} />
            ) : preview.kind === 'json' ? (
              <pre className="whitespace-pre-wrap break-words text-xs leading-relaxed text-slate-100">
                {JSON.stringify(preview.content, null, 2)}
              </pre>
            ) : preview.kind === 'image' ? (
              <div className="flex flex-col items-center gap-3">
                <img
                  src={preview.url}
                  alt={preview.artifact_name}
                  className="max-h-[min(480px,60vh)] w-full max-w-full rounded-lg border border-white/10 object-contain"
                />
                <a
                  href={preview.url}
                  target="_blank"
                  rel="noreferrer"
                  className="text-xs text-cyan-400/90 hover:underline"
                >
                  在新标签页打开图片
                </a>
              </div>
            ) : preview.kind === 'text' ? (
              <pre className="whitespace-pre-wrap break-words font-mono text-xs leading-relaxed text-emerald-100/90">
                {preview.content}
              </pre>
            ) : (
              <div className="space-y-2">
                <div className="text-xs text-slate-400">
                  Shape: {preview.shape.join(' × ')} · {preview.columns.length} columns
                </div>
                <div className="max-w-full overflow-x-auto rounded-lg border border-white/10">
                  <table className="min-w-max text-left text-xs">
                    <thead className="sticky top-0 z-10 bg-slate-900/98 text-slate-300">
                      <tr>
                        {preview.preview_rows[0] &&
                          Object.keys(preview.preview_rows[0]).map((column) => (
                            <th
                              key={column}
                              className="max-w-[14rem] border-b border-white/10 px-2 py-1.5 font-medium break-words"
                            >
                              {column}
                            </th>
                          ))}
                      </tr>
                    </thead>
                    <tbody>
                      {preview.preview_rows.map((row, index) => (
                        <tr key={index} className="border-b border-white/5 text-slate-200">
                          {Object.entries(row).map(([column, value]) => (
                            <td key={column} className="max-w-[14rem] px-2 py-1.5 align-top break-words">
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
      </div>
    </section>
  )
}
