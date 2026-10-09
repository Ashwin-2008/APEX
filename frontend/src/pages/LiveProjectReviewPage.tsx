import { useEffect, useMemo, useState } from 'react'
import { connectProject, getFailureHistory, stopMonitoring } from '../services/projectReviewApi'
import { useProjectEvents, type ProjectEvent } from '../hooks/useProjectEvents'
import { MistiqFailureIntelligence } from '../components/MistiqFailureIntelligence'
import { ConnectScreen } from '../components/projectReview/ConnectScreen'
import { monitoringView, ProjectHeader } from '../components/projectReview/ProjectHeader'
import { buildHealthCards, HealthCards } from '../components/projectReview/ProjectHealth'
import { ActivityFeed } from '../components/projectReview/ActivityFeed'
import { ProblemsSection } from '../components/projectReview/ProblemsSection'
import { RecentlyFixed, resolvedFromHistory, type ResolvedView } from '../components/projectReview/RecentlyFixed'
import { RequirementsSection } from '../components/projectReview/RequirementsSection'
import { RecommendationsSection } from '../components/projectReview/RecommendationsSection'
import { applyFindingEvent, dedupeActiveFindings, dedupeRecommendations, findingDisplayKey, seedFindings, type DedupableFinding } from '../utils/findingDedup'
import { appendActivity, categoryNoun, categoryTitle, severityLabel, translateEvent, type ActivityEntry } from '../utils/labels'
import { persistProjectContext, recordProjectNotification } from '../utils/projectNotifications'
import { useProject } from '../context/ProjectContext'
import type { FailureEvent, FailureHistoryRow, ProjectReview } from '../types/projectReview'
import '../styles/liveProjectReview.css'

interface ResolvedPayload {
  fingerprint?: string
  category?: string
  severity?: string
  component?: string | null
  file?: string | null
  resolved_at?: string
  resolution_evidence?: string | null
  related_commit?: string | null
}

function readString(value: unknown): string | null {
  return typeof value === 'string' && value ? value : null
}

function OnboardingSteps({ steps, onDismiss }: { steps: Array<{ label: string; done: boolean }>; onDismiss: () => void }) {
  const allDone = steps.every(step => step.done)
  return (
    <section className="pr-onboarding card" aria-label="Getting started">
      <div className="pr-onboarding-head">
        <span className="eyebrow">OBSERVABILITY ONBOARDING</span>
        <h3>Continuous Inspection Pipeline</h3>
      </div>
      <ol className="pr-onboarding-steps" aria-label="Getting started steps">
        {steps.map((step, index) => (
          <li key={step.label} className={step.done ? 'done' : 'pending'}>
            <span className="pr-step-index" aria-hidden="true">{step.done ? '✓' : index + 1}</span>
            <span className="pr-step-text">STEP {index + 1} {step.label}</span>
          </li>
        ))}
      </ol>
      {allDone && (
        <div className="pr-onboarding-done">
          <p>Your project is now being monitored. Save a file to see MISTIQ-APR analyze the change automatically.</p>
          <button type="button" className="button button-sm" onClick={onDismiss}>Got it</button>
        </div>
      )}
    </section>
  )
}

export function LiveProjectReviewPage() {
  const { connect: setGlobalProject, updateProject } = useProject()
  const [source, setSource] = useState<'local' | 'github'>('local')
  const [value, setValue] = useState('')
  const [connecting, setConnecting] = useState(false)
  const [error, setError] = useState('')

  const [projectId, setProjectId] = useState<number>()
  const [review, setReview] = useState<ProjectReview>()
  const [findings, setFindings] = useState<Record<string, FailureEvent>>({})
  const [failureDna, setFailureDna] = useState<Record<string, number>>({})
  const [refreshToken, setRefreshToken] = useState(0)

  const [activity, setActivity] = useState<ActivityEntry[]>([])
  const [historyIndex, setHistoryIndex] = useState<Map<string, FailureHistoryRow>>(new Map())
  const [historyResolved, setHistoryResolved] = useState<ResolvedView[]>([])
  const [sseResolved, setSseResolved] = useState<Map<string, ResolvedView>>(new Map())
  const [historyError, setHistoryError] = useState('')
  const [historyLoaded, setHistoryLoaded] = useState(false)
  const [repositoryPath, setRepositoryPath] = useState('')

  const [branch, setBranch] = useState<string | null>(null)
  const [commitSha, setCommitSha] = useState<string | null>(null)
  const [lastChange, setLastChange] = useState<string | null>(null)
  const [lastChecked, setLastChecked] = useState<string | null>(null)
  const [analyzing, setAnalyzing] = useState(false)
  const [analysisError, setAnalysisError] = useState('')
  const [monitoringPaused, setMonitoringPaused] = useState(false)
  const [stopping, setStopping] = useState(false)
  const [stopError, setStopError] = useState('')
  const [onboardingDismissed, setOnboardingDismissed] = useState(false)
  const [activeTab, setActiveTab] = useState<'overview' | 'changes' | 'problems' | 'fixed' | 'requirements' | 'next' | 'intelligence'>('overview')

  function handleEvent(event: ProjectEvent) {
    recordProjectNotification(event)
    const entry = translateEvent(event, 0)
    setActivity(previous => appendActivity(previous, entry))

    const nextBranch = readString(event.branch)
    const nextSha = readString(event.current_commit_sha)
    if (nextBranch) {
      setBranch(nextBranch)
      updateProject({ branch: nextBranch })
    }
    if (nextSha) {
      setCommitSha(nextSha)
      updateProject({ commitSha: nextSha })
    }

    switch (event.type) {
      case 'project.changed': {
        const files = Array.isArray(event.files) ? event.files : []
        if (files.length) setLastChange(String(files[0]))
        break
      }
      case 'analysis.started':
        setAnalyzing(true)
        setAnalysisError('')
        break
      case 'analysis.completed':
        setAnalyzing(false)
        setLastChecked(new Date().toLocaleTimeString())
        setRefreshToken(token => token + 1)
        break
      case 'analysis.failed':
        setAnalyzing(false)
        setAnalysisError(readString(event.message) || 'The latest analysis failed while scanning changes.')
        break
      case 'requirement.updated':
        setRefreshToken(token => token + 1)
        break
      case 'dna.updated':
        if (event.failure_dna && typeof event.failure_dna === 'object') {
          setFailureDna(event.failure_dna as Record<string, number>)
        }
        break
      case 'monitoring.status': {
        const nextStatus = readString(event.status)
        setMonitoringPaused(nextStatus !== 'active')
        if (nextStatus) updateProject({ monitoringStatus: nextStatus })
        break
      }
      case 'finding.resolved': {
        const payload = event as unknown as ResolvedPayload
        const fingerprint = String(payload.fingerprint || '')
        setFindings(previous => {
          const next = { ...previous }
          if (fingerprint && next[fingerprint]) {
            delete next[fingerprint]
            return next
          }
          if (!fingerprint) {
            for (const key of Object.keys(next)) {
              const known = next[key] as DedupableFinding
              if (payload.category && known.category === payload.category
                && (known.file || '') === (payload.file || '')
                && (known.component || '') === (payload.component || '')) {
                delete next[key]
              }
            }
          }
          return next
        })
        const known = fingerprint ? (findings[fingerprint] as DedupableFinding | undefined) : undefined
        const view: ResolvedView = {
          key: fingerprint || `${payload.category || ''}|${payload.file || ''}`,
          title: known ? categoryTitle(known) : (payload.category ? `${categoryNoun(payload.category)} issue` : 'Issue resolved'),
          location: {
            file: payload.file ?? known?.file ?? null,
            line: known?.line ?? null,
            component: payload.component ?? known?.component ?? null,
            evidence: known?.evidence ?? '',
          },
          severity: severityLabel(payload.severity ?? known?.severity),
          resolvedAt: payload.resolved_at ?? null,
          howResolved: payload.resolution_evidence ?? null,
          relatedCommit: payload.related_commit ?? null,
        }
        setSseResolved(previous => new Map(previous).set(view.key, view))
        break
      }
      default: {
        const finding = event.finding as FailureEvent | undefined
        if (finding) setFindings(previous => applyFindingEvent(previous, finding as DedupableFinding, event.type))
      }
    }
  }

  const sseState = useProjectEvents(projectId, handleEvent)

  useEffect(() => {
    if (!projectId) return
    let cancelled = false
    getFailureHistory(projectId)
      .then(result => {
        if (cancelled) return
        const index = new Map<string, FailureHistoryRow>()
        for (const row of result.findings) index.set(findingDisplayKey(row), row)
        setHistoryIndex(index)
        setHistoryResolved(resolvedFromHistory(result.findings))
        setRepositoryPath(result.project?.repository_path || '')
        setHistoryLoaded(true)
        setHistoryError('')
      })
      .catch(exception => {
        if (!cancelled) setHistoryError(exception instanceof Error ? exception.message : 'Failure history could not be loaded.')
      })
    return () => { cancelled = true }
  }, [projectId, refreshToken])

  async function connect() {
    setConnecting(true)
    setError('')
    try {
      const result = await connectProject(source, value.trim())
      setProjectId(result.project_id)
      setReview(result.analysis)
      setRepositoryPath(result.path || result.analysis.project.path)
      const ctx = {
        projectId: result.project_id,
        source,
        repositoryUrl: source === 'github' ? value.trim() : null,
        path: result.path || result.analysis.project.path,
        branch: result.branch,
        commitSha: result.current_commit_sha,
        monitoringStatus: result.monitoring_status,
      }
      persistProjectContext(ctx)
      setGlobalProject({
        ...ctx,
        name: (result.path || result.analysis.project.path).split(/[\\/]/).filter(Boolean).pop() || 'Connected project',
        review: result.analysis,
      })
      setFailureDna(result.analysis.failure_dna)
      setFindings(seedFindings(result.analysis.events))
      setMonitoringPaused(result.monitoring_status !== 'active')
      setOnboardingDismissed(false)
    } catch (exception) {
      setError(exception instanceof Error ? exception.message : 'Project connection failed.')
    } finally {
      setConnecting(false)
    }
  }

  async function stop() {
    if (!projectId) return
    setStopping(true)
    setStopError('')
    try {
      await stopMonitoring(projectId)
      setMonitoringPaused(true)
      updateProject({ monitoringStatus: 'paused' })
    } catch (exception) {
      setStopError(exception instanceof Error ? exception.message : 'Monitoring could not be stopped.')
    } finally {
      setStopping(false)
    }
  }

  const activeFindings = useMemo(() => dedupeActiveFindings(Object.values(findings)), [findings])
  const recommendations = useMemo(() => dedupeRecommendations(activeFindings), [activeFindings])
  const healthCards = useMemo(() => buildHealthCards(activeFindings), [activeFindings])
  const resolvedViews = useMemo(() => {
    const merged = new Map<string, ResolvedView>()
    for (const item of historyResolved) merged.set(item.key, item)
    for (const [key, item] of sseResolved) merged.set(key, item)
    return Array.from(merged.values()).sort((a, b) => String(b.resolvedAt || '').localeCompare(String(a.resolvedAt || '')))
  }, [historyResolved, sseResolved])

  if (!projectId || !review) {
    return (
      <ConnectScreen
        source={source}
        value={value}
        connecting={connecting}
        error={error}
        onSourceChange={setSource}
        onValueChange={setValue}
        onConnect={connect}
      />
    )
  }

  const projectName = review.project.path.split(/[\\/]/).filter(Boolean).pop() || 'Connected project'
  const pathForMode = (repositoryPath || review.project.path).toLowerCase()
  const showcase = pathForMode.includes('showcase') || pathForMode.includes('synthetic')
  const view = monitoringView({ sseState, analyzing, failed: Boolean(analysisError), stopped: monitoringPaused })
  const onboardingSteps = [
    { label: 'Connected', done: true },
    { label: 'Analyzing project', done: Boolean(review) },
    { label: 'Building engineering profile', done: historyLoaded },
    { label: 'Monitoring enabled', done: sseState === 'CONNECTED' && !monitoringPaused },
  ]

  const tabList = [
    ['overview', 'Overview'],
    ['changes', 'Changes'],
    ['problems', 'Problems'],
    ['fixed', 'Fixed'],
    ['requirements', 'Requirements'],
    ['next', 'Next steps'],
    ['intelligence', 'Failure intelligence'],
  ] as const

  return (
    <div className="pr-command-center">
      <div className="pr-mode-banner">
        <span className={`pr-mode ${showcase ? 'showcase' : 'live'}`}>
          {showcase ? 'SHOWCASE MODE' : 'LIVE MODE'}
        </span>
      </div>

      <ProjectHeader
        projectName={projectName}
        source={source}
        branch={branch}
        commitSha={commitSha}
        monitoring={view}
        lastChecked={lastChecked}
        lastChange={lastChange}
        monitoringPaused={monitoringPaused}
        stopping={stopping}
        onStop={stop}
      />

      {(stopError || analysisError || historyError) && (
        <p className="pr-error" role="alert">{stopError || analysisError || `Failure history unavailable: ${historyError}`}</p>
      )}

      {!onboardingDismissed && <OnboardingSteps steps={onboardingSteps} onDismiss={() => setOnboardingDismissed(true)} />}

      {/* CATEGORY NAVIGATION TABS */}
      <nav className="project-review-tabs" aria-label="Project review categories">
        {tabList.map(([key, label]) => (
          <button
            key={key}
            type="button"
            className={activeTab === key ? 'active' : ''}
            aria-current={activeTab === key ? 'page' : undefined}
            onClick={() => setActiveTab(key)}
          >
            {label}
          </button>
        ))}
      </nav>

      {/* HEALTH CARDS: SHOWN ON OVERVIEW AND PROBLEMS */}
      {(activeTab === 'overview' || activeTab === 'problems') && <HealthCards cards={healthCards} />}

      <div className={`pr-grid project-review-view project-review-${activeTab}`}>
        {activeTab === 'overview' && (
          <>
            <ProblemsSection findings={activeFindings.slice(0, 5)} historyIndex={historyIndex} />
            <ActivityFeed entries={activity.slice(0, 8)} />
            <RecommendationsSection recommendations={recommendations.slice(0, 5)} />
          </>
        )}
        {activeTab === 'changes' && <ActivityFeed entries={activity} />}
        {activeTab === 'problems' && <ProblemsSection findings={activeFindings} historyIndex={historyIndex} />}
        {activeTab === 'fixed' && <RecentlyFixed items={resolvedViews} />}
        {activeTab === 'requirements' && <RequirementsSection projectId={projectId} refreshToken={refreshToken} />}
        {activeTab === 'next' && <RecommendationsSection recommendations={recommendations.slice(0, 5)} />}
        {activeTab === 'intelligence' && (
          <MistiqFailureIntelligence
            projectId={projectId}
            source={source}
            sseState={sseState}
            failureDna={failureDna}
            refreshToken={refreshToken}
          />
        )}
      </div>
    </div>
  )
}
