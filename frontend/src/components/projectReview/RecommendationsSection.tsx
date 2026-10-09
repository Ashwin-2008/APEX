import { categoryNoun, severityLabel, severitySymbol } from '../../utils/labels'
import { recommendationKey, type DedupableFinding } from '../../utils/findingDedup'
import { ArrowRightIcon } from '../ui/Icons'

export function RecommendationsSection({
  recommendations,
}: {
  recommendations: DedupableFinding[]
}) {
  return (
    <section className="card pr-section pr-action-center" aria-label="What should I do next">
      <div className="pr-section-header-row">
        <div>
          <h2>WHAT SHOULD I DO NEXT?</h2>
          <p className="pr-section-note">Recommendations generated from the active findings</p>
        </div>
        <div className="action-center-badge">
          <span>PRIORITIZED REMEDIATION TASKS</span>
        </div>
      </div>

      {recommendations.length ? (
        <ol className="pr-recs">
          {recommendations.map((finding, idx) => {
            const sevKey = String(finding.severity || 'medium').toLowerCase()
            const stepNumber = String(idx + 1).padStart(2, '0')
            return (
              <li key={recommendationKey(finding.remediation)} className={`pr-rec-card card sev-border-${sevKey}`}>
                <div className="rec-card-top">
                  <div className="rec-index-badge">
                    <span className="rec-num">{stepNumber}</span>
                  </div>
                  <span className={`pr-sev pr-sev-${sevKey}`}>
                    <span aria-hidden="true" className="sev-dot-icon">{severitySymbol(finding.severity)}</span>{' '}
                    {severityLabel(finding.severity)}
                  </span>
                </div>

                <p className="pr-rec-action">{finding.remediation}</p>

                <div className="rec-card-bottom">
                  <span className="pr-rec-meta">
                    {categoryNoun(finding.category)} · {severityLabel(finding.severity)}
                  </span>

                  <span className="rec-view-link">
                    Action Plan <ArrowRightIcon size={12} className="inline ml-1" />
                  </span>
                </div>
              </li>
            )
          })}
        </ol>
      ) : (
        <p className="pr-empty">
          No remediation guidance is available yet. Remediation appears after the analyzers report evidence.
        </p>
      )}
    </section>
  )
}