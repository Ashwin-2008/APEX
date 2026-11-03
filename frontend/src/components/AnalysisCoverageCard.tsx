import { useEffect, useState } from 'react'
import type { AnalysisCoverageReport } from '../types/projectReview'
import { fetchProjectCoverage } from '../api/projectsApi'

interface AnalysisCoverageCardProps {
  coverage?: AnalysisCoverageReport | null
  projectId?: number
}

export function AnalysisCoverageCard({ coverage: propCoverage, projectId }: AnalysisCoverageCardProps) {
  const [coverage, setCoverage] = useState<AnalysisCoverageReport | null>(propCoverage || null)
  const [expanded, setExpanded] = useState(false)

  useEffect(() => {
    if (propCoverage) {
      setCoverage(propCoverage)
    } else if (projectId) {
      fetchProjectCoverage(projectId).then(setCoverage).catch(() => {})
    }
  }, [propCoverage, projectId])

  if (!coverage) {
    return (
      <div className="p-4 rounded-xl border border-slate-800 bg-slate-900/60 text-xs text-slate-400">
        Analysis coverage metrics pending initial scan.
      </div>
    )
  }

  const getStatusBadge = (status: string) => {
    switch (status.toUpperCase()) {
      case 'COMPLETE':
        return <span className="px-2 py-0.5 rounded text-[10px] font-semibold bg-emerald-500/20 text-emerald-300">COMPLETE</span>
      case 'PARTIAL':
        return <span className="px-2 py-0.5 rounded text-[10px] font-semibold bg-amber-500/20 text-amber-300">PARTIAL</span>
      case 'FAILED':
        return <span className="px-2 py-0.5 rounded text-[10px] font-semibold bg-red-500/20 text-red-300">FAILED</span>
      case 'NOT_APPLICABLE':
      default:
        return <span className="px-2 py-0.5 rounded text-[10px] font-semibold bg-slate-700/50 text-slate-400">N / A</span>
    }
  }

  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/80 p-5 shadow-sm">
      <div className="flex items-center justify-between border-b border-slate-800 pb-3 mb-4">
        <div>
          <div className="flex items-center gap-2">
            <h3 className="text-sm font-bold text-white">Repository Analysis Coverage</h3>
            {getStatusBadge(coverage.overall_status)}
          </div>
          <p className="text-xs text-slate-400 mt-0.5">
            Transparent disclosure of scanned source files and analyzer health
          </p>
        </div>
        <div className="text-right">
          <div className="text-2xl font-black text-indigo-400 font-mono">
            {coverage.coverage_percentage}%
          </div>
          <div className="text-[10px] text-slate-500 uppercase tracking-wider">Overall Coverage</div>
        </div>
      </div>

      <div className="grid grid-cols-4 gap-3 mb-4 text-center">
        <div className="p-2.5 rounded-lg bg-slate-950 border border-slate-800">
          <div className="text-base font-bold text-slate-100 font-mono">{coverage.total_files}</div>
          <div className="text-[10px] text-slate-400 uppercase mt-0.5">Total Files</div>
        </div>
        <div className="p-2.5 rounded-lg bg-slate-950 border border-slate-800">
          <div className="text-base font-bold text-emerald-400 font-mono">{coverage.analyzed_files}</div>
          <div className="text-[10px] text-slate-400 uppercase mt-0.5">Analyzed</div>
        </div>
        <div className="p-2.5 rounded-lg bg-slate-950 border border-slate-800">
          <div className="text-base font-bold text-amber-400 font-mono">{coverage.skipped_files}</div>
          <div className="text-[10px] text-slate-400 uppercase mt-0.5">Skipped / Large</div>
        </div>
        <div className="p-2.5 rounded-lg bg-slate-950 border border-slate-800">
          <div className="text-base font-bold text-slate-400 font-mono">{coverage.excluded_files}</div>
          <div className="text-[10px] text-slate-400 uppercase mt-0.5">Excluded Dirs</div>
        </div>
      </div>

      <button
        type="button"
        onClick={() => setExpanded(!expanded)}
        className="w-full py-1.5 px-3 rounded-lg bg-slate-800/60 hover:bg-slate-800 text-xs text-slate-300 font-medium flex items-center justify-between transition-colors"
      >
        <span>Analyzer Health Breakdown ({Object.keys(coverage.analyzers || {}).length} Analyzers)</span>
        <span className="text-slate-500">{expanded ? '▲ Collapse' : '▼ View Details'}</span>
      </button>

      {expanded && coverage.analyzers && (
        <div className="mt-3 pt-3 border-t border-slate-800 space-y-2 animate-in fade-in">
          {Object.entries(coverage.analyzers).map(([name, info]) => (
            <div
              key={name}
              className="p-2.5 rounded-lg bg-slate-950/80 border border-slate-800 flex items-center justify-between text-xs"
            >
              <div>
                <div className="font-semibold text-slate-200 capitalize">
                  {name.replace('_', ' ')}
                </div>
                <div className="text-[10px] text-slate-500">
                  {info.findings_count} findings · {info.duration_ms} ms
                  {info.error_message && (
                    <span className="text-red-400 ml-2">Error: {info.error_message}</span>
                  )}
                </div>
              </div>
              <div>{getStatusBadge(info.status)}</div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
