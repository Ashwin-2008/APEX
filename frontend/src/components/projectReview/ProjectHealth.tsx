import type { DedupableFinding } from '../../utils/findingDedup'

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
  return (
    <section className="pr-health" aria-label="Project health">
      {cards.map(card => (
        <div className="pr-health-card" key={card.label}>
          <span className="pr-health-label">{card.label}</span>
          <strong className="pr-health-value">{card.value}</strong>
          <span className="pr-health-note">{card.note}</span>
        </div>
      ))}
    </section>
  )
}