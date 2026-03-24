import { useEffect, useMemo, useState } from 'react'

import { ArtifactPanel } from './components/ArtifactPanel'
import { ClarifyDialog } from './components/ClarifyDialog'
import { GoalInput } from './components/GoalInput'
import { LogPanel } from './components/LogPanel'
import { ProgressBar } from './components/ProgressBar'
import { ReportPanel } from './components/ReportPanel'
import { WorkflowGraph } from './components/WorkflowGraph'
import { useAgentSocket } from './hooks/useAgentSocket'
import type { AgentEvent, ArtifactPreview, WorkspaceManifest } from './types'

const defaultGoal =
  'Download 1 year of SPY daily data, search for relevant alpha factors, engineer features, train a ridge model, backtest, and evaluate the result.'

function App() {
  const [goal, setGoal] = useState(defaultGoal)
  const [runId, setRunId] = useState<string | null>(null)
  const [manifest, setManifest] = useState<WorkspaceManifest | null>(null)
  const [selectedArtifact, setSelectedArtifact] = useState<string | null>(null)
  const [preview, setPreview] = useState<ArtifactPreview | null>(null)
  const [isStarting, setIsStarting] = useState(false)
  const [errorMessage, setErrorMessage] = useState<string | null>(null)
  const [showClarify, setShowClarify] = useState(false)
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
      })
      .catch((error: unknown) => {
        setErrorMessage(error instanceof Error ? error.message : 'Failed to refresh workspace')
      })
  }, [latestEvent, runId])

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

  async function doStartRun(runGoal: string) {
    setIsStarting(true)
    setErrorMessage(null)
    setManifest(null)
    setSelectedArtifact(null)
    setPreview(null)
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
    } catch (error: unknown) {
      setErrorMessage(error instanceof Error ? error.message : `Failed to load artifact ${artifactName}`)
    }
  }

  return (
    <main className="min-h-screen bg-[radial-gradient(circle_at_top,_rgba(34,211,238,0.12),_transparent_28%),linear-gradient(180deg,_#0f172a,_#020617)] px-4 py-8 text-slate-100">
      <div className="mx-auto flex w-full max-w-7xl flex-col gap-5">
        <GoalInput goal={goal} isRunning={isStarting || isRunning} onGoalChange={setGoal} onSubmit={handleRunClick} />

        {showClarify && !isStarting && !isRunning && (
          <ClarifyDialog goal={goal} onConfirm={handleClarifyConfirm} onSkip={handleClarifySkip} />
        )}

        {errorMessage && (
          <div className="rounded-2xl border border-rose-400/20 bg-rose-400/5 px-4 py-3 text-sm text-rose-300">
            {errorMessage}
          </div>
        )}

        <ProgressBar
          completed={completedSubtasks}
          total={totalSubtasks}
          currentStep={currentStep}
          connectionStatus={connectionStatus}
        />

        <WorkflowGraph events={events as AgentEvent[]} />

        <div className="grid gap-5 xl:grid-cols-[1.05fr_0.95fr]">
          <LogPanel events={events as AgentEvent[]} />
          <div className="space-y-5">
            <ArtifactPanel
              manifest={manifest}
              selectedArtifact={selectedArtifact}
              preview={preview}
              onSelect={(artifactName) => void loadArtifact(artifactName)}
            />
            <ReportPanel events={events as AgentEvent[]} runId={runId} />
          </div>
        </div>
      </div>
    </main>
  )
}

export default App
