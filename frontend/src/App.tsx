import { useEffect, useMemo, useState } from 'react'

import { ArtifactPanel } from './components/ArtifactPanel'
import { GoalInput } from './components/GoalInput'
import { LogPanel } from './components/LogPanel'
import { ProgressBar } from './components/ProgressBar'
import { ReportPanel } from './components/ReportPanel'
import { useAgentSocket } from './hooks/useAgentSocket'
import type { AgentEvent, ArtifactPreview, WorkspaceManifest } from './types'

const defaultGoal =
  'Download 1 year of SPY daily data, analyze it, engineer features, train a ridge model, backtest, and evaluate the result.'

function App() {
  const [goal, setGoal] = useState(defaultGoal)
  const [runId, setRunId] = useState<string | null>(null)
  const [manifest, setManifest] = useState<WorkspaceManifest | null>(null)
  const [selectedArtifact, setSelectedArtifact] = useState<string | null>(null)
  const [preview, setPreview] = useState<ArtifactPreview | null>(null)
  const [isStarting, setIsStarting] = useState(false)
  const [errorMessage, setErrorMessage] = useState<string | null>(null)
  const [statusMessage, setStatusMessage] = useState<string>('Ready')
  const { events, connectionStatus } = useAgentSocket(runId)
  const latestEvent = events.at(-1) ?? null

  const decomposeEvent = useMemo(
    () => events.find((event) => event.type === 'decompose_done') ?? null,
    [events],
  )
  const subtaskDoneEvents = useMemo(
    () => events.filter((event) => event.type === 'subtask_done'),
    [events],
  )
  const currentSubtaskEvent = useMemo(
    () => [...events].reverse().find((event) => event.type === 'subtask_start') ?? null,
    [events],
  )
  const finalEvent = useMemo(
    () => [...events].reverse().find((event) => event.type === 'run_done') ?? null,
    [events],
  )
  const isRunning = Boolean(runId) && finalEvent === null
  const totalSubtasks =
    typeof decomposeEvent?.total_subtasks === 'number' ? (decomposeEvent.total_subtasks as number) : 0
  const completedSubtasks = subtaskDoneEvents.length
  const currentStep =
    typeof currentSubtaskEvent?.subtask_title === 'string'
      ? (currentSubtaskEvent.subtask_title as string)
      : 'Waiting for the next event'

  useEffect(() => {
    if (!runId) return
    const shouldRefreshWorkspace =
      latestEvent?.type === 'workspace_update' || latestEvent?.type === 'run_done'
    if (!shouldRefreshWorkspace) return
    void fetch(`/api/workspace/${runId}`)
      .then((response) => response.json())
      .then((data: WorkspaceManifest) => {
        setManifest(data)
        setStatusMessage(`Workspace updated: ${Object.keys(data.artifacts).length} artifact(s)`)
      })
      .catch((error: unknown) => {
        setErrorMessage(error instanceof Error ? error.message : 'Failed to refresh workspace')
      })
  }, [latestEvent, runId])

  useEffect(() => {
    if (!latestEvent) return
    if (latestEvent.type === 'subtask_start' && typeof latestEvent.subtask_title === 'string') {
      setStatusMessage(`Running: ${latestEvent.subtask_title}`)
    } else if (latestEvent.type === 'run_done') {
      setStatusMessage(`Run finished: ${String(latestEvent.status ?? 'unknown')}`)
    }
  }, [latestEvent])

  async function startRun() {
    setIsStarting(true)
    setErrorMessage(null)
    setStatusMessage('Starting run...')
    setManifest(null)
    setSelectedArtifact(null)
    setPreview(null)
    try {
      const response = await fetch('/api/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ goal }),
      })
      if (!response.ok) {
        throw new Error(`Failed to start run: ${response.status}`)
      }
      const data = (await response.json()) as { run_id: string }
      setRunId(data.run_id)
      setStatusMessage(`Run started: ${data.run_id}`)
    } catch (error: unknown) {
      setErrorMessage(error instanceof Error ? error.message : 'Failed to start run')
      setStatusMessage('Run failed to start')
    } finally {
      setIsStarting(false)
    }
  }

  async function loadArtifact(artifactName: string) {
    if (!runId) return
    setSelectedArtifact(artifactName)
    setErrorMessage(null)
    try {
      const response = await fetch(`/api/workspace/${runId}/${artifactName}`)
      if (!response.ok) {
        throw new Error(`Failed to load artifact ${artifactName}`)
      }
      const data = (await response.json()) as ArtifactPreview
      setPreview(data)
      setStatusMessage(`Loaded artifact: ${artifactName}`)
    } catch (error: unknown) {
      setErrorMessage(error instanceof Error ? error.message : `Failed to load artifact ${artifactName}`)
    }
  }

  return (
    <main className="min-h-screen bg-[radial-gradient(circle_at_top,_rgba(34,211,238,0.12),_transparent_28%),linear-gradient(180deg,_#0f172a,_#020617)] px-4 py-8 text-slate-100">
      <div className="mx-auto flex w-full max-w-7xl flex-col gap-6">
        <GoalInput goal={goal} isRunning={isStarting || isRunning} onGoalChange={setGoal} onSubmit={() => void startRun()} />
        <section className="rounded-3xl border border-white/10 bg-white/5 px-5 py-4 text-sm text-slate-200">
          <div className="font-medium text-white">Status</div>
          <div className="mt-1">{statusMessage}</div>
          {errorMessage ? <div className="mt-2 text-rose-300">Error: {errorMessage}</div> : null}
        </section>
        <ProgressBar
          completed={completedSubtasks}
          total={totalSubtasks}
          currentStep={currentStep}
          connectionStatus={connectionStatus}
        />
        <div className="grid gap-6 xl:grid-cols-[1.05fr_0.95fr]">
          <LogPanel events={events as AgentEvent[]} />
          <div className="space-y-6">
            <ArtifactPanel
              manifest={manifest}
              selectedArtifact={selectedArtifact}
              preview={preview}
              onSelect={(artifactName) => void loadArtifact(artifactName)}
            />
            <ReportPanel finalEvent={finalEvent as AgentEvent | null} />
          </div>
        </div>
      </div>
    </main>
  )
}

export default App
