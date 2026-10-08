import { categoryNoun, severityLabel, severitySymbol } from '../../utils/labels'
import { recommendationKey, type DedupableFinding } from '../../utils/findingDedup'

export function RecommendationsSection({ recommendations }: { recommendations: DedupableFinding[] }) {
  return (
    <section className="card pr-section" aria-label="What should I do next">
      <h2>WHAT SHOULD I DO NEXT?</h2>
      <p className="pr-section-note">Recommendations generated from the active findings</p>
      {recommendations.length ? (
        <ol className="pr-recs">
          {recommendations.map(finding => (
            <li key={recommendationKey(finding.remediation)}>
              <span className={`pr-sev pr-sev-${String(finding.severity || 'medium').toLowerCase()}`}>
                <span aria-hidden="true">{severitySymbol(finding.severity)}</span> {severityLabel(finding.severity)}
              </span>
              <p className="pr-rec-action">{finding.remediation}</p>
              <span className="pr-rec-meta">{categoryNoun(finding.category)} · {severityLabel(finding.severity)}</span>
            </li>
          ))}
        </ol>
      ) : (
        <p className="pr-empty">No remediation guidance is available yet. Remediation appears after the analyzers report evidence.</p>
      )}
    </section>
  )
}