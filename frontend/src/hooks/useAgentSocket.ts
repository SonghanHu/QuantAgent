import { useEffect, useMemo, useState } from 'react'

import type { AgentEvent } from '../types'

export function useAgentSocket(runId: string | null) {
  const [events, setEvents] = useState<AgentEvent[]>([])
  const [connectionStatus, setConnectionStatus] = useState<'idle' | 'connecting' | 'open' | 'closed' | 'error'>('idle')

  useEffect(() => {
    if (!runId) {
      setEvents([])
      setConnectionStatus('idle')
      return
    }

    const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws'
    const socket = new WebSocket(`${protocol}://${window.location.host}/ws/${runId}`)
    setEvents([])
    setConnectionStatus('connecting')

    socket.onopen = () => setConnectionStatus('open')
    socket.onerror = () => setConnectionStatus('error')
    socket.onclose = () => setConnectionStatus('closed')
    socket.onmessage = (message) => {
      try {
        const event = JSON.parse(message.data) as AgentEvent
        setEvents((current) => [...current, event])
      } catch {
        // Ignore malformed events so the UI stays responsive.
      }
    }

    return () => {
      socket.close()
    }
  }, [runId])

  const latestEvent = useMemo(() => events.at(-1) ?? null, [events])

  return { events, latestEvent, connectionStatus }
}
