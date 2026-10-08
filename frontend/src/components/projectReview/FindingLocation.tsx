import { findingLocations, type LocationSource } from '../../utils/findingDedup'

export function FindingLocation({ finding, showHeading = false }: { finding: LocationSource; showHeading?: boolean }) {
  const { primary, component, additional } = findingLocations(finding)
  return (
    <div className="pr-loc">
      <span className="pr-loc-primary">
        {showHeading ? 'Location: ' : ''}
        <code>{primary}</code>
      </span>
      {component && <span className="pr-loc-component">Component: {component}</span>}
      {additional.length > 0 && (
        <details className="pr-loc-more">
          <summary>Show all locations (+ {additional.length})</summary>
          <ul>
            {additional.map(location => <li key={location}><code>{location}</code></li>)}
          </ul>
        </details>
      )}
    </div>
  )
}