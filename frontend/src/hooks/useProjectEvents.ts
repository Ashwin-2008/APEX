import { useEffect, useRef, useState } from 'react'

export type ProjectEvent = { type: string; project_id: number; files?: string[]; finding?: unknown; [key: string]: unknown }
export type EventConnectionState = 'CONNECTING' | 'CONNECTED' | 'DISCONNECTED' | 'RECONNECTING' | 'STOPPED'

export function useProjectEvents(projectId: number | undefined, onEvent: (event: ProjectEvent) => void) {
  const [state, setState] = useState<EventConnectionState>('STOPPED')
  const callback = useRef(onEvent); callback.current = onEvent
  useEffect(() => {
    if (!projectId) { setState('STOPPED'); return }
    let source: EventSource | null = null; let timer: number | undefined; let stopped = false
    const connect = () => {
      if (stopped) return
      setState(timer ? 'RECONNECTING' : 'CONNECTING')
      source = new EventSource(`/api/project-reviews/${projectId}/events`)
      const handle = (message: MessageEvent) => { try { callback.current(JSON.parse(message.data) as ProjectEvent) } catch { /* ignore malformed event */ } }
      source.onopen = () => setState('CONNECTED')
      source.onmessage = handle
      const eventTypes = ['project.changed', 'analysis.started', 'analysis.completed', 'analysis.failed', 'finding.created', 'finding.updated', 'finding.resolved', 'requirement.updated', 'dna.updated', 'prediction.updated', 'llm.explanation.completed', 'monitoring.status']
      eventTypes.forEach(type => source?.addEventListener(type, handle))
      source.onerror = () => { source?.close(); if (!stopped) { setState('DISCONNECTED'); timer = window.setTimeout(connect, 2000) } }
    }
    connect()
    return () => { stopped = true; if (timer) window.clearTimeout(timer); source?.close(); setState('STOPPED') }
  }, [projectId])
  return state
}
