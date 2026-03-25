import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import { ArtifactPanel } from './components/ArtifactPanel'
import { ClarifyDialog } from './components/ClarifyDialog'
import { GoalInput } from './components/GoalInput'
import { LogPanel } from './components/LogPanel'
import { ProgressBar } from './components/ProgressBar'
import { ReportPanel } from './components/ReportPanel'
import { WorkflowGraph } from './components/WorkflowGraph'
import { useAgentSocket } from './hooks/useAgentSocket'
import type { AgentEvent, ArtifactPreview, WorkspaceManifest } from './types'
import { computePipelineProgress } from './utils/pipelineProgress'

const defaultGoal =
  'Download 1 year of SPY daily data, search for relevant alpha factors, engineer features, train a ridge model, backtest, and evaluate the result.'

type MainTab = 'activity' | 'workspace' | 'report'

const TABS: { id: MainTab; label: string; short: string; kbd: string }[] = [
  { id: 'activity', label: 'Activity', short: 'Log & pipeline', kbd: '1' },
  { id: 'workspace', label: 'Workspace', short: 'Artifacts & preview', kbd: '2' },
  { id: 'report', label: 'Report', short: 'Results & chat', kbd: '3' },
]

function App() {
  const [goal, setGoal] = useState(defaultGoal)
  const [runId, setRunId] = useState<string | null>(null)
  const [manifest, setManifest] = useState<WorkspaceManifest | null>(null)
  const [selectedArtifact, setSelectedArtifact] = useState<string | null>(null)
  const [preview, setPreview] = useState<ArtifactPreview | null>(null)
  const [isPreviewLoading, setIsPreviewLoading] = useState(false)
  const [isStarting, setIsStarting] = useState(false)
  const [errorMessage, setErrorMessage] = useState<string | null>(null)
  const [showClarify, setShowClarify] = useState(false)
  const [activeTab, setActiveTab] = useState<MainTab>('activity')
  const [followLatestArtifact, setFollowLatestArtifact] = useState(true)
  const [artifactSelectionLocked, setArtifactSelectionLocked] = useState(false)
  const artifactRequestIdRef = useRef(0)
  const lastFollowedArtifactRef = useRef('')
  const { events, connectionStatus } = useAgentSocket(runId)
  const latestEvent = events.at(-1) ?? null

  const pipelineProgress = useMemo(() => computePipelineProgress(events as AgentEvent[]), [events])
  const currentSubtaskEvent = useMemo(
    () => [...events].reverse().find((event) => event.type === 'subtask_start') ?? null,
    [events],
  )
  const finalEvent = useMemo(
    () => [...events].reverse().find((event) => event.type === 'run_done') ?? null,
    [events],
  )
  const isRunning = Boolean(runId) && finalEvent === null
  const totalSubtasks = pipelineProgress.total
  const completedSubtasks = pipelineProgress.completed
  const progressPhaseHint =
    pipelineProgress.replanRound > 0
      ? `当前为第 ${pipelineProgress.replanRound} 次重规划后的执行段；进度仅统计本段内子任务（重试合并为一步）。`
      : undefined
  const currentStep =
    typeof currentSubtaskEvent?.subtask_title === 'string'
      ? (currentSubtaskEvent.subtask_title as string)
      : 'Waiting for the next event'

  const lastWorkspaceArtifact = useMemo(() => {
    for (let i = events.length - 1; i >= 0; i--) {
      const e = events[i]
      if (e.type === 'workspace_update' && e.artifact_name) return String(e.artifact_name)
    }
    return ''
  }, [events])

  const artifactCount = Object.keys(manifest?.artifacts ?? {}).length
  const agentScriptCount = manifest?.agent_scripts?.length ?? 0
  const workspaceItemCount = artifactCount + agentScriptCount

  const refreshManifest = useCallback(async (id: string) => {
    try {
      const response = await fetch(`/api/workspace/${id}`)
      if (!response.ok) return
      const data = (await response.json()) as WorkspaceManifest
      setManifest(data)
    } catch (error: unknown) {
      setErrorMessage(error instanceof Error ? error.message : 'Failed to refresh workspace')
    }
  }, [])

  useEffect(() => {
    if (!runId) return
    void refreshManifest(runId)
  }, [runId, refreshManifest])

  useEffect(() => {
    if (!runId) return
    const shouldRefreshWorkspace =
      latestEvent?.type === 'workspace_update' ||
      latestEvent?.type === 'run_done' ||
      latestEvent?.type === 'subtask_done'
    if (!shouldRefreshWorkspace) return
    void refreshManifest(runId)
  }, [latestEvent, runId, refreshManifest])

  useEffect(() => {
    lastFollowedArtifactRef.current = ''
    setArtifactSelectionLocked(false)
    setFollowLatestArtifact(true)
    setActiveTab('activity')
  }, [runId])

  const loadArtifact = useCallback(
    async (artifactName: string) => {
      if (!runId) return
      const requestId = artifactRequestIdRef.current + 1
      artifactRequestIdRef.current = requestId
      setSelectedArtifact(artifactName)
      setPreview(null)
      setIsPreviewLoading(true)
      setErrorMessage(null)
      try {
        const scriptPrefix = 'script:'
        const url = artifactName.startsWith(scriptPrefix)
          ? `/api/workspace/${runId}/agent-scripts/${artifactName.slice(scriptPrefix.length)}`
          : `/api/workspace/${runId}/${artifactName}`
        const response = await fetch(url)
        if (!response.ok) {
          throw new Error(`Failed to load artifact ${artifactName}`)
        }
        const data = (await response.json()) as ArtifactPreview
        if (artifactRequestIdRef.current !== requestId) return
        setPreview(data)
      } catch (error: unknown) {
        if (artifactRequestIdRef.current !== requestId) return
        setErrorMessage(error instanceof Error ? error.message : `Failed to load artifact ${artifactName}`)
      } finally {
        if (artifactRequestIdRef.current === requestId) {
          setIsPreviewLoading(false)
        }
      }
    },
    [runId],
  )

  useEffect(() => {
    if (!runId || !lastWorkspaceArtifact) return
    if (!followLatestArtifact || artifactSelectionLocked) return
    if (lastWorkspaceArtifact === lastFollowedArtifactRef.current) return
    if (!manifest?.artifacts[lastWorkspaceArtifact]) return
    lastFollowedArtifactRef.current = lastWorkspaceArtifact
    void loadArtifact(lastWorkspaceArtifact)
  }, [
    artifactSelectionLocked,
    followLatestArtifact,
    lastWorkspaceArtifact,
    loadArtifact,
    manifest,
    runId,
  ])

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.metaKey || e.altKey || e.ctrlKey) return
      const t = e.target as HTMLElement
      if (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.isContentEditable) return
      if (e.key === '1') setActiveTab('activity')
      if (e.key === '2') setActiveTab('workspace')
      if (e.key === '3') setActiveTab('report')
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  function handleRunClick() {
    setShowClarify(true)
  }

  function handleClarifyConfirm(refinedGoal: string) {
    setShowClarify(false)
    setGoal(refinedGoal)
    void doStartRun(refinedGoal)
  }

  function handleClarifySkip() {
    setShowClarify(false)
    void doStartRun(goal)
  }

  function handleClarifyCancel() {
    setShowClarify(false)
  }

  async function doStartRun(runGoal: string) {
    setIsStarting(true)
    setErrorMessage(null)
    setManifest(null)
    setSelectedArtifact(null)
    setPreview(null)
    setIsPreviewLoading(false)
    artifactRequestIdRef.current += 1
    try {
      const response = await fetch('/api/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ goal: runGoal }),
      })
      if (!response.ok) {
        throw new Error(`Failed to start run: ${response.status}`)
      }
      const data = (await response.json()) as { run_id: string }
      setRunId(data.run_id)
    } catch (error: unknown) {
      setErrorMessage(error instanceof Error ? error.message : 'Failed to start run')
    } finally {
      setIsStarting(false)
    }
  }

  return (
    <main className="min-h-screen bg-[radial-gradient(ellipse_120%_80%_at_50%_-20%,rgba(56,189,248,0.14),transparent),linear-gradient(180deg,#0c1222,#030712)] px-3 py-6 text-slate-100 sm:px-5 sm:py-8">
      <div className="mx-auto flex w-full max-w-6xl flex-col gap-4">
        <GoalInput goal={goal} isRunning={isStarting || isRunning} onGoalChange={setGoal} onSubmit={handleRunClick} />

        {showClarify && !isStarting && !isRunning && (
          <ClarifyDialog
            goal={goal}
            onConfirm={handleClarifyConfirm}
            onSkip={handleClarifySkip}
            onCancel={handleClarifyCancel}
          />
        )}

        {errorMessage && (
          <div className="rounded-xl border border-rose-400/25 bg-rose-950/30 px-4 py-3 text-sm text-rose-200">
            {errorMessage}
          </div>
        )}

        <ProgressBar
          completed={completedSubtasks}
          total={totalSubtasks}
          currentStep={currentStep}
          connectionStatus={connectionStatus}
          phaseHint={progressPhaseHint}
        />

        {/* Main tabbed shell: each tab gets full width — no artifact vs log squeeze */}
        <div className="flex min-h-0 flex-col rounded-2xl border border-white/[0.07] bg-slate-950/40 shadow-xl shadow-black/20 backdrop-blur-sm">
          <div
            className="flex flex-wrap gap-1 border-b border-white/[0.06] p-1.5 sm:gap-2"
            role="tablist"
            aria-label="Dashboard sections"
          >
            {TABS.map((tab) => (
              <button
                key={tab.id}
                type="button"
                role="tab"
                aria-selected={activeTab === tab.id}
                className={`flex min-w-0 flex-1 flex-col items-center rounded-xl px-2 py-2 text-center transition sm:flex-row sm:items-baseline sm:justify-center sm:gap-2 sm:px-4 ${
                  activeTab === tab.id
                    ? 'bg-cyan-500/15 text-white ring-1 ring-cyan-400/35'
                    : 'text-slate-400 hover:bg-white/[0.04] hover:text-slate-200'
                }`}
                onClick={() => setActiveTab(tab.id)}
              >
                <span className="text-sm font-medium">{tab.label}</span>
                <span className="hidden text-[11px] text-slate-500 sm:inline">{tab.short}</span>
                <kbd className="ml-1 hidden rounded bg-slate-800 px-1 font-mono text-[10px] text-slate-500 sm:inline">
                  {tab.kbd}
                </kbd>
                {tab.id === 'workspace' && workspaceItemCount > 0 && (
                  <span className="ml-1 rounded-full bg-violet-500/20 px-1.5 py-0.5 text-[10px] text-violet-200">
                    {workspaceItemCount}
                  </span>
                )}
              </button>
            ))}
          </div>

          <div
            className="min-h-[min(72vh,720px)] p-3 sm:p-4"
            role="tabpanel"
            hidden={activeTab !== 'activity'}
          >
            {activeTab === 'activity' && (
              <div className="flex h-[min(68vh,680px)] min-h-[420px] flex-col gap-3">
                <WorkflowGraph events={events as AgentEvent[]} compact />
                <LogPanel events={events as AgentEvent[]} className="min-h-0 flex-1" />
              </div>
            )}
          </div>

          <div
            className="min-h-[min(72vh,720px)] p-3 sm:p-4"
            role="tabpanel"
            hidden={activeTab !== 'workspace'}
          >
            {activeTab === 'workspace' && (
              <ArtifactPanel
                manifest={manifest}
                selectedArtifact={selectedArtifact}
                preview={preview}
                isLoading={isPreviewLoading}
                onSelect={(name) => void loadArtifact(name)}
                followLatest={followLatestArtifact}
                onFollowLatestChange={(v) => {
                  setFollowLatestArtifact(v)
                  if (v) {
                    setArtifactSelectionLocked(false)
                    lastFollowedArtifactRef.current = ''
                  }
                }}
                onUserPickArtifact={() => setArtifactSelectionLocked(true)}
                sectionClassName="min-h-[min(68vh,680px)] border-0 bg-transparent p-0"
              />
            )}
          </div>

          <div
            className="min-h-[min(72vh,720px)] p-3 sm:p-4"
            role="tabpanel"
            hidden={activeTab !== 'report'}
          >
            {activeTab === 'report' && <ReportPanel events={events as AgentEvent[]} runId={runId} />}
          </div>
        </div>

        <p className="text-center text-[11px] text-slate-600">
          Tabs: <kbd className="rounded bg-slate-800/80 px-1">1</kbd> Activity ·{' '}
          <kbd className="rounded bg-slate-800/80 px-1">2</kbd> Workspace ·{' '}
          <kbd className="rounded bg-slate-800/80 px-1">3</kbd> Report
        </p>
      </div>
    </main>
  )
}

export default App
