import { render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ConnectScreen } from '../components/projectReview/ConnectScreen'
import { monitoringView, ProjectHeader } from '../components/projectReview/ProjectHeader'
import { buildHealthCards, HealthCards } from '../components/projectReview/ProjectHealth'
import { ActivityFeed } from '../components/projectReview/ActivityFeed'
import { ProblemsSection } from '../components/projectReview/ProblemsSection'
import { RecentlyFixed, resolvedFromHistory } from '../components/projectReview/RecentlyFixed'
import { RecommendationsSection } from '../components/projectReview/RecommendationsSection'
import { RequirementsSection } from '../components/projectReview/RequirementsSection'
import { findingDisplayKey, type DedupableFinding } from '../utils/findingDedup'
import type { ActivityEntry } from '../utils/labels'
import type { FailureHistoryRow, RequirementReport } from '../types/projectReview'

function jsonResponse(body: unknown, status = 200) {
  return Promise.resolve({ ok: status >= 200 && status < 300, status, json: async () => body } as Response)
}

afterEach(() => { vi.unstubAllGlobals() })

describe('connect screen', () => {
  it('offers both connection sources with the required copy', () => {
    render(
      <ConnectScreen source="local" value="" connecting={false} error=""
        onSourceChange={() => {}} onValueChange={() => {}} onConnect={() => {}} />,
    )
    expect(screen.getByRole('heading', { level: 1, name: 'CONNECT YOUR PROJECT' })).toBeTruthy()
    expect(screen.getByText('How do you want to connect?')).toBeTruthy()
    expect(screen.getByText('Local Project')).toBeTruthy()
    expect(screen.getByText('Connect a folder from this computer.')).toBeTruthy()
    expect(screen.getByText('GitHub')).toBeTruthy()
    expect(screen.getByText('Connect a repository.')).toBeTruthy()
    expect(screen.getByLabelText('Project path')).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Connect Project' })).toBeTruthy()
    expect(screen.queryByLabelText('Repository URL')).toBeNull()
  })

  it('switches to the GitHub field and shows the connection progress steps', () => {
    const onSourceChange = vi.fn()
    const { rerender } = render(
      <ConnectScreen source="local" value="" connecting={false} error=""
        onSourceChange={onSourceChange} onValueChange={() => {}} onConnect={() => {}} />,
    )
    screen.getByRole('button', { name: /^GitHub/ }).click()
    expect(onSourceChange).toHaveBeenCalledWith('github')
    rerender(
      <ConnectScreen source="github" value="https://github.com/acme/app" connecting error=""
        onSourceChange={onSourceChange} onValueChange={() => {}} onConnect={() => {}} />,
    )
    expect(screen.getByLabelText('Repository URL')).toBeTruthy()
    expect((screen.getByRole('button', { name: 'Connecting…' }) as HTMLButtonElement).disabled).toBe(true)
    const progress = screen.getByRole('list')
    expect(within(progress).getByText('Connecting…')).toBeTruthy()
    expect(within(progress).getByText('Analyzing project…')).toBeTruthy()
    expect(within(progress).getByText('Monitoring active.')).toBeTruthy()
  })

  it('surfaces connection errors', () => {
    render(
      <ConnectScreen source="local" value="/tmp/x" connecting={false} error="Project connection failed."
        onSourceChange={() => {}} onValueChange={() => {}} onConnect={() => {}} />,
    )
    expect(screen.getByRole('alert').textContent).toBe('Project connection failed.')
  })
})

describe('monitoring indicator', () => {
  it('maps connection state to the four required labels', () => {
    expect(monitoringView({ sseState: 'CONNECTED', analyzing: false, failed: false, stopped: false }).label).toBe('LIVE MONITORING')
    expect(monitoringView({ sseState: 'CONNECTED', analyzing: true, failed: false, stopped: false }).label).toBe('ANALYZING CHANGES…')
    expect(monitoringView({ sseState: 'DISCONNECTED', analyzing: false, failed: false, stopped: false }).label).toBe('MONITORING PAUSED')
    expect(monitoringView({ sseState: 'CONNECTED', analyzing: false, failed: true, stopped: false }).label).toBe('MONITORING ERROR')
  })
})

describe('project header', () => {
  it('shows source, branch, short commit, last change, and a stop control', () => {
    render(
      <ProjectHeader
        projectName="demo-app"
        source="local"
        branch="main"
        commitSha="abc1234def5678"
        monitoring={{ label: 'LIVE MONITORING', modifier: 'live', glyph: '●' }}
        lastChecked="10:57:12 AM"
        lastChange="src/auth/login.py"
        monitoringPaused={false}
        stopping={false}
        onStop={() => {}}
      />,
    )
    expect(screen.getByRole('heading', { level: 1, name: 'demo-app' })).toBeTruthy()
    expect(screen.getByText(/Source: Local folder/)).toBeTruthy()
    expect(screen.getByText(/Branch: /).textContent).toContain('main')
    expect(screen.getByText(/Last commit:/).textContent).toContain('abc1234')
    expect(screen.queryByText(/abc1234def5678/)).toBeNull()
    expect(screen.getByText(/Monitoring: LIVE MONITORING/)).toBeTruthy()
    expect(screen.getByText('10:57:12 AM')).toBeTruthy()
    expect(screen.getByText('src/auth/login.py')).toBeTruthy()
    expect((screen.getByRole('button', { name: 'Stop Monitoring' }) as HTMLButtonElement).disabled).toBe(false)
  })

  it('explains missing git data instead of guessing it', () => {
    render(
      <ProjectHeader
        projectName="demo-app"
        source="github"
        branch={null}
        commitSha={null}
        monitoring={{ label: 'MONITORING PAUSED', modifier: 'paused', glyph: '○' }}
        lastChecked={null}
        lastChange={null}
        monitoringPaused
        stopping={false}
        onStop={() => {}}
      />,
    )
    expect(screen.getByText(/Branch: /).textContent).toContain('not available')
    expect(screen.getByText(/Last commit:/).textContent).toContain('not available')
    expect(screen.getByText('Not yet')).toBeTruthy()
    expect(screen.getByText('None reported')).toBeTruthy()
    expect((screen.getByRole('button', { name: 'Monitoring stopped' }) as HTMLButtonElement).disabled).toBe(true)
  })
})

describe('project health cards', () => {
  const finding = (overrides: Partial<DedupableFinding>): DedupableFinding => ({
    category: 'security', severity: 'high', confidence: 0.9, timestamp: '2026-10-08T10:00:00Z',
    evidence: 'secret in file', analyzer_source: 'secret_detector', status: 'ACTIVE',
    remediation: 'Rotate it', ...overrides,
  })

  it('counts active issues per area without unexplained numbers', () => {
    const cards = buildHealthCards([
      finding({}),
      finding({ category: 'security', severity: 'critical' }),
      finding({ category: 'testing', severity: 'medium' }),
      finding({ category: 'testing', severity: 'low' }),
      finding({ category: 'architecture', severity: 'low' }),
    ])
    expect(cards[0].value).toBe('2 high or critical issues')
    expect(cards[1].value).toBe('2 active issues')
    expect(cards[2].value).toBe('2 active issues')
    expect(cards[3].value).toBe('1 active issue')
    expect(cards.every(card => card.note.length > 0)).toBe(true)
  })

  it('uses plain sentences when there is nothing to report', () => {
    const cards = buildHealthCards([])
    expect(cards.map(card => card.value)).toEqual([
      'No high-risk issues detected',
      'No security issues detected',
      'No testing issues detected',
      'No major issues detected',
    ])
    render(<HealthCards cards={cards} />)
    expect(screen.getByText('Overall risk')).toBeTruthy()
    expect(screen.getByText('No major issues detected')).toBeTruthy()
  })

  it('excludes resolved findings from the counts', () => {
    const cards = buildHealthCards([finding({ status: 'RESOLVED' })])
    expect(cards[1].value).toBe('No security issues detected')
  })
})

describe('activity feed', () => {
  const entries: ActivityEntry[] = [
    { key: 'a', time: new Date('2026-10-08T10:57:12Z'), message: 'Analyzing the latest changes', file: 'src/app.py', receivedAt: 1 },
    { key: 'b', time: new Date('2026-10-08T10:56:00Z'), message: 'Security issue resolved', receivedAt: 2 },
  ]

  it('renders the required heading and a plain-language history', () => {
    render(<ActivityFeed entries={entries} />)
    expect(screen.getByRole('heading', { name: 'WHAT CHANGED?' })).toBeTruthy()
    const list = screen.getByRole('list')
    const items = within(list).getAllByRole('listitem')
    expect(items).toHaveLength(2)
    expect(items[0].textContent).toContain('Analyzing the latest changes')
    expect(items[0].textContent).toContain('src/app.py')
    expect(items[0].querySelector('time')?.getAttribute('datetime')).toBe('2026-10-08T10:57:12.000Z')
    expect(items[1].textContent).toContain('Security issue resolved')
  })

  it('shows an honest empty state', () => {
    render(<ActivityFeed entries={[]} />)
    expect(screen.getByText(/No project activity has been observed yet/)).toBeTruthy()
  })
})

describe('problems to fix', () => {
  const secret: DedupableFinding = {
    category: 'security', severity: 'critical', confidence: 0.95,
    timestamp: '2026-10-08T10:00:00Z',
    evidence: 'Potential hard-coded secret at src/config/app.py:33, token=demo',
    analyzer_source: 'secret_detector', status: 'open', remediation: 'Move the credential to a secret manager and rotate it.',
  }

  const historyRow: FailureHistoryRow = {
    fingerprint: 'fp', category: 'security', severity: 'critical', confidence: 0.95,
    component: null, file: null, line: null, evidence: secret.evidence,
    analyzer_source: 'secret_detector', remediation: secret.remediation, status: 'OPEN',
    occurrences: 3, review_numbers: [1, 2, 3], first_seen: '2026-10-01T09:00:00',
    last_seen: '2026-10-08T10:00:00', resolved_at: null, resolution_evidence: null, related_commit: null,
  }

  it('renders title, location, severity, status, why, what to do, and evidence', () => {
    const index = new Map([[findingDisplayKey(secret), historyRow]])
    render(<ProblemsSection findings={[secret]} historyIndex={index} />)
    expect(screen.getByRole('heading', { name: 'PROBLEMS TO FIX' })).toBeTruthy()
    const card = screen.getByRole('article')
    expect(card.textContent).toContain('Hard-coded secret detected')
    expect(card.textContent).toContain('src/config/app.py:33')
    expect(card.textContent).toContain('● CRITICAL')
    expect(card.textContent).toContain('ACTIVE')
    expect(card.textContent).toContain('Why this matters')
    expect(card.textContent).toContain('What to do')
    expect(card.textContent).toContain('Move the credential to a secret manager and rotate it.')
    expect(card.textContent).toContain('First detected')
    expect(card.textContent).toContain('Seen in 3 reviews (reviews 1, 2, 3)')
    const evidence = within(card).getByText('View evidence').closest('details') as HTMLElement
    expect(evidence.textContent).toContain('Potential hard-coded secret at src/config/app.py:33')
  })

  it('hides additional locations behind an expander', () => {
    const multi: DedupableFinding = {
      ...secret,
      evidence: 'Found in src/a.py:1 and src/b.py:2 and src/c.py:3',
    }
    render(<ProblemsSection findings={[multi]} historyIndex={new Map()} />)
    const card = screen.getByRole('article')
    expect(card.textContent).toContain('src/a.py:1')
    const more = within(card).getByText(/Show all locations \(\+ 2\)/).closest('details') as HTMLElement
    expect(more.textContent).toContain('src/b.py:2')
    expect(more.textContent).toContain('src/c.py:3')
  })

  it('shows the required no-issues sentence', () => {
    render(<ProblemsSection findings={[]} historyIndex={new Map()} />)
    expect(screen.getByText('Good news — no engineering issues were detected by the current analyzers.')).toBeTruthy()
  })
})

describe('recently fixed', () => {
  const rows: FailureHistoryRow[] = [
    {
      fingerprint: 'fp-1', category: 'dependency', severity: 'medium', confidence: 0.8,
      component: 'deps', file: 'requirements.txt', line: null, evidence: 'Outdated package pin',
      analyzer_source: 'dependency_analyzer', remediation: 'Pin runtime dependencies', status: 'RESOLVED',
      occurrences: 1, review_numbers: [2], first_seen: '2026-10-01T09:00:00', last_seen: '2026-10-01T09:00:00',
      resolved_at: '2026-10-05T12:00:00', resolution_evidence: 'Pinned to patched version', related_commit: 'abc1234',
    },
    {
      fingerprint: 'fp-2', category: 'testing', severity: 'high', confidence: 0.7,
      component: null, file: null, line: null, evidence: 'No test files',
      analyzer_source: 'test_inventory', remediation: 'Add tests', status: 'OPEN',
      occurrences: 1, review_numbers: [1], first_seen: '2026-10-01T09:00:00', last_seen: '2026-10-01T09:00:00',
      resolved_at: null, resolution_evidence: null, related_commit: null,
    },
  ]

  it('lists only resolved findings with how they were resolved', () => {
    const items = resolvedFromHistory(rows)
    expect(items).toHaveLength(1)
    render(<RecentlyFixed items={items} />)
    expect(screen.getByRole('heading', { name: 'RECENTLY FIXED' })).toBeTruthy()
    const entry = screen.getByRole('listitem')
    expect(entry.textContent).toContain('Dependency management gap')
    expect(entry.textContent).toContain('requirements.txt')
    expect(entry.textContent).toContain('MEDIUM')
    expect(entry.textContent).toContain('Pinned to patched version')
    expect(entry.textContent).toContain('abc1234')
  })

  it('shows an honest empty state', () => {
    render(<RecentlyFixed items={[]} />)
    expect(screen.getByText(/No issues have been resolved in the recorded project history yet/)).toBeTruthy()
  })
})

describe('recommendations', () => {
  it('renders numbered remediation with severity and category', () => {
    render(<RecommendationsSection recommendations={[{
      category: 'security', severity: 'critical', confidence: 0.9, timestamp: '2026-10-08T10:00:00Z',
      evidence: 'secret', analyzer_source: 'secret_detector', status: 'ACTIVE',
      remediation: 'Rotate exposed credentials.',
    }]} />)
    expect(screen.getByRole('heading', { name: 'WHAT SHOULD I DO NEXT?' })).toBeTruthy()
    const item = screen.getByRole('listitem')
    expect(item.textContent).toContain('● CRITICAL')
    expect(item.textContent).toContain('Rotate exposed credentials.')
    expect(item.textContent).toContain('Security · CRITICAL')
  })

  it('shows an honest empty state', () => {
    render(<RecommendationsSection recommendations={[]} />)
    expect(screen.getByText(/No remediation guidance is available yet/)).toBeTruthy()
  })
})

describe('requirements', () => {
  const report: RequirementReport = {
    requirements: [
      { requirement_key: 'r1', title: 'Users can sign in', source: 'docs', coverage: { status: 'COVERED', confidence: 0.8, evidence: 'auth.py and test_auth.py', implementation: { files: ['auth.py'] }, tests: { files: ['test_auth.py'] } } },
      { requirement_key: 'r2', title: 'Export data as CSV', source: 'docs', coverage: { status: 'PARTIALLY_COVERED', confidence: 0.5, evidence: 'export.py exists, no tests', implementation: { files: ['export.py'] }, tests: { files: [] } } },
      { requirement_key: 'r3', title: 'Audit log retention', source: 'docs', coverage: { status: 'UNKNOWN', confidence: 0, evidence: 'No deterministic implementation evidence found; coverage is unknown.', implementation: { files: [] }, tests: { files: [] } } },
    ],
    message: null,
  }

  it('shows coverage counts and lists uncovered requirements with evidence', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse(report)))
    render(<RequirementsSection projectId={7} refreshToken={0} />)
    await waitFor(() => expect(screen.getByRole('heading', { name: 'REQUIREMENTS' })).toBeTruthy())
    const counts = screen.getByRole('list', { name: 'Coverage counts' })
    expect(within(counts).getByText('Covered')).toBeTruthy()
    expect(within(counts).getByText('Partially covered')).toBeTruthy()
    expect(within(counts).getByText('Unknown')).toBeTruthy()
    expect(screen.queryByText('Not covered')).toBeNull()
    const list = screen.getAllByRole('list')[1]
    const items = within(list).getAllByRole('listitem')
    expect(items).toHaveLength(2)
    expect(items[0].textContent).toContain('Partially covered')
    expect(items[0].textContent).toContain('Export data as CSV')
    expect(items[1].textContent).toContain('Unknown')
    expect(items[1].textContent).toContain('Audit log retention')
    const evidence = within(items[1]).getByText('View evidence').closest('details') as HTMLElement
    expect(evidence.textContent).toContain('No deterministic implementation evidence found; coverage is unknown.')
  })

  it('shows the backend message when no requirements were detected', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse({ requirements: [], message: 'No structured requirements were detected.' })))
    render(<RequirementsSection projectId={7} refreshToken={0} />)
    await waitFor(() => expect(screen.getByText('No structured requirements were detected.')).toBeTruthy())
  })
})