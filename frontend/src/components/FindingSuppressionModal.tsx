import { useState } from 'react'
import { suppressFinding } from '../api/projectsApi'
import type { ProjectFindingItem } from '../types/projectReview'

interface FindingSuppressionModalProps {
  isOpen: boolean
  finding: ProjectFindingItem | null
  projectId: number
  onClose: () => void
  onSuppressed: (updated: ProjectFindingItem) => void
}

export function FindingSuppressionModal({
  isOpen,
  finding,
  projectId,
  onClose,
  onSuppressed,
}: FindingSuppressionModalProps) {
  const [reason, setReason] = useState('')
  const [suppressionType, setSuppressionType] = useState<'false_positive' | 'wont_fix' | 'accepted_risk'>('false_positive')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  if (!isOpen || !finding) return null

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (reason.trim().length < 5) {
      setError('Please provide a meaningful justification (at least 5 characters).')
      return
    }

    setSubmitting(true)
    setError(null)
    try {
      const updated = await suppressFinding(projectId, finding.id, reason.trim(), suppressionType)
      onSuppressed(updated)
      onClose()
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to suppress finding.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-950/80 backdrop-blur-sm animate-in fade-in">
      <div className="relative w-full max-w-lg rounded-2xl bg-slate-900 border border-slate-700 shadow-2xl p-6 text-slate-100">
        <div className="flex items-center justify-between border-b border-slate-800 pb-3 mb-4">
          <div>
            <h3 className="text-base font-bold text-white">Suppress Finding / Mark False Positive</h3>
            <p className="text-xs text-slate-400 mt-0.5">Maintain audit trail and rationale for this resolution</p>
          </div>
          <button type="button" onClick={onClose} className="text-slate-400 hover:text-white p-1">
            ✕
          </button>
        </div>

        {error && (
          <div className="mb-4 p-2.5 rounded-lg bg-red-950/60 border border-red-800 text-xs text-red-200">
            {error}
          </div>
        )}

        <div className="mb-4 p-3 rounded-lg bg-slate-950 border border-slate-800 text-xs">
          <div className="font-semibold text-slate-200">{finding.title || finding.category}</div>
          <div className="text-slate-400 mt-1 font-mono text-[11px] truncate">
            {finding.file ? `${finding.file}:${finding.line || 1}` : finding.component || 'Global'}
          </div>
          <div className="text-slate-500 mt-1 text-[11px] line-clamp-2">{finding.evidence}</div>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-xs font-medium text-slate-300 mb-1">Suppression Classification</label>
            <select
              value={suppressionType}
              onChange={e => setSuppressionType(e.target.value as any)}
              className="w-full px-3 py-2 text-xs bg-slate-950 border border-slate-700 rounded-lg text-slate-100 focus:outline-none focus:border-indigo-500"
            >
              <option value="false_positive">False Positive (Analyzer misidentification)</option>
              <option value="accepted_risk">Accepted Business / Technical Risk</option>
              <option value="wont_fix">Won't Fix (Compensating controls present)</option>
            </select>
          </div>

          <div>
            <label className="block text-xs font-medium text-slate-300 mb-1">
              Engineering Justification <span className="text-red-400">*</span>
            </label>
            <textarea
              rows={3}
              placeholder="Explain why this finding is safe or not applicable in this context…"
              value={reason}
              onChange={e => setReason(e.target.value)}
              className="w-full px-3 py-2 text-xs bg-slate-950 border border-slate-700 rounded-lg text-slate-100 placeholder-slate-500 focus:outline-none focus:border-indigo-500"
            />
          </div>

          <div className="flex justify-end gap-2 pt-2 border-t border-slate-800">
            <button
              type="button"
              onClick={onClose}
              className="px-3 py-1.5 text-xs text-slate-400 hover:text-white"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={submitting}
              className="px-4 py-2 bg-amber-600 hover:bg-amber-500 disabled:opacity-50 text-white text-xs font-semibold rounded-lg shadow"
            >
              {submitting ? 'Saving…' : 'Confirm Suppression'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

