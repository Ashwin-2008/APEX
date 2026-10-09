import type { DedupableFinding } from '../../utils/findingDedup'
import { ShieldIcon, AlertTriangleIcon, CheckCircleIcon, ActivityIcon } from '../ui/Icons'

export interface HealthCardModel {
  label: string
  value: string
  note: string
}

export function buildHealthCards(activeFindings: DedupableFinding[]): HealthCardModel[] {
  const live = activeFindings.filter(finding => String(finding.status || 'ACTIVE').toUpperCase() !== 'RESOLVED')
  const countFor = (category: string) => live.filter(finding => finding.category === category).length
  const highRisk = live.filter(finding => ['high', 'critical'].includes(String(finding.severity || '').toLowerCase())).length
  const issueLine = (count: number) => `${count} active issue${count === 1 ? '' : 's'}`
  const security = countFor('security')
  const testing = countFor('testing')
  const architecture = countFor('architecture')
  return [
    {
      label: 'Overall risk',
      value: highRisk
        ? `${highRisk} high or critical issue${highRisk === 1 ? '' : 's'}`
        : 'No high-risk issues detected',
      note: 'Active findings rated high or critical severity.',
    },
    {
      label: 'Security',
      value: security ? issueLine(security) : 'No security issues detected',
      note: security ? 'Secrets, authentication, and authorization evidence.' : 'No security evidence reported by the analyzers.',
    },
    {
      label: 'Testing',
      value: testing ? issueLine(testing) : 'No testing issues detected',
      note: testing ? 'Test inventory gaps reported by the analyzers.' : 'The test inventory analyzer reported no gaps.',
    },
    {
      label: 'Architecture',
      value: architecture ? issueLine(architecture) : 'No major issues detected',
      note: architecture ? 'Structural evidence reported by the analyzers.' : 'No architecture evidence reported by the analyzers.',
    },
  ]
}

export function HealthCards({ cards }: { cards: HealthCardModel[] }) {
  const getAccent = (label: string, value: string) => {
    const isClean = value.includes('No ')
    if (label === 'Overall risk') return isClean ? 'accent-success' : 'accent-critical'
    if (label === 'Security') return isClean ? 'accent-success' : 'accent-critical'
    if (label === 'Testing') return isClean ? 'accent-success' : 'accent-warning'
    return isClean ? 'accent-success' : 'accent-info'
  }

  const getIcon = (label: string) => {
    if (label === 'Overall risk') return AlertTriangleIcon
    if (label === 'Security') return ShieldIcon
    if (label === 'Testing') return ActivityIcon
    return CheckCircleIcon
  }

  return (
    <section className="pr-health-grid" aria-label="Project health">
      {cards.map(card => {
        const accent = getAccent(card.label, card.value)
        const Icon = getIcon(card.label)
        return (
          <div className={`pr-health-card card ${accent}`} key={card.label}>
            <div className="pr-health-card-header">
              <span className="pr-health-label">{card.label}</span>
              <span className="pr-health-icon-wrap" aria-hidden="true">
                <Icon size={14} />
              </span>
            </div>
            <strong className="pr-health-value">{card.value}</strong>
            <span className="pr-health-note">{card.note}</span>
          </div>
        )
      })}
    </section>
  )
}