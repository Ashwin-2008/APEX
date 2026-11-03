import { useEffect, useRef, useState } from 'react'

export type ProjectEvent = { type: string; project_id: number; files?: string[]; finding?: unknown; [key: string]: unknown }
export type EventConnectionState = 'CONNECTING' | 'CONNECTED' | 'DISCONNECTED' | 'RECONNECTING' | 'STOPPED'

async function getSSETicket(projectId: number): Promise<string | null> {
  try {
    const token = localStorage.getItem('apex_token')
    if (!token) return null
    const res = await fetch('/api/auth/sse-ticket', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify({ project_id: projectId }),
    })
    if (!res.ok) return null
    const data = await res.json()
    return data.ticket || null
  } catch {
    return null
  }
}

export function useProjectEvents(projectId: number | undefined, onEvent: (event: ProjectEvent) => void) {
  const [state, setState] = useState<EventConnectionState>('STOPPED')
  const callback = useRef(onEvent)
  callback.current = onEvent

  useEffect(() => {
    if (!projectId) {
      setState('STOPPED')
      return
    }
    let source: EventSource | null = null
    let timer: number | undefined
    let stopped = false

    const connect = async () => {
      if (stopped) return
      setState(timer ? 'RECONNECTING' : 'CONNECTING')

      const ticket = await getSSETicket(projectId)
      if (stopped) return

      const url = ticket
        ? `/api/project-reviews/${projectId}/events?ticket=${encodeURIComponent(ticket)}`
        : `/api/project-reviews/${projectId}/events`

      source = new EventSource(url)
      const handle = (message: MessageEvent) => {
        try {
          callback.current(JSON.parse(message.data) as ProjectEvent)
        } catch {
          /* ignore malformed event */
        }
      }
      source.onopen = () => setState('CONNECTED')
      source.onmessage = handle
      const eventTypes = [
        'project.changed',
        'analysis.started',
        'analysis.completed',
        'analysis.failed',
        'finding.created',
        'finding.updated',
        'finding.resolved',
        'requirement.updated',
        'dna.updated',
        'prediction.updated',
        'llm.explanation.completed',
        'monitoring.status',
      ]
      eventTypes.forEach((type) => source?.addEventListener(type, handle))
      source.onerror = () => {
        source?.close()
        if (!stopped) {
          setState('DISCONNECTED')
          timer = window.setTimeout(connect, 2000)
        }
      }
    }

    connect()
    return () => {
      stopped = true
      if (timer) window.clearTimeout(timer)
      source?.close()
      setState('STOPPED')
    }
  }, [projectId])

  return state
}
