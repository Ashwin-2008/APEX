import { useState } from 'react'
import { changePassword, updateUserProfile } from '../api/authApi'
import { useAuth } from '../context/AuthContext'
import { useTheme } from '../context/ThemeContext'

export function SettingsPage() {
  const { user, refreshUser } = useAuth()
  const { preference, setPreference } = useTheme()

  const [fullName, setFullName] = useState(user?.full_name || '')
  const [profileSaving, setProfileSaving] = useState(false)
  const [profileMsg, setProfileMsg] = useState<string | null>(null)

  const [currentPw, setCurrentPw] = useState('')
  const [newPw, setNewPw] = useState('')
  const [confirmPw, setConfirmPw] = useState('')
  const [pwSaving, setPwSaving] = useState(false)
  const [pwMsg, setPwMsg] = useState<{ text: string; error?: boolean } | null>(null)

  const handleSaveProfile = async (e: React.FormEvent) => {
    e.preventDefault()
    setProfileSaving(true)
    setProfileMsg(null)
    try {
      await updateUserProfile({ full_name: fullName.trim() })
      await refreshUser()
      setProfileMsg('Profile updated successfully.')
    } catch (err: unknown) {
      setProfileMsg(err instanceof Error ? err.message : 'Update failed.')
    } finally {
      setProfileSaving(false)
    }
  }

  const handleChangePassword = async (e: React.FormEvent) => {
    e.preventDefault()
    if (newPw !== confirmPw) {
      setPwMsg({ text: 'New passwords do not match.', error: true })
      return
    }
    if (newPw.length < 8) {
      setPwMsg({ text: 'New password must be at least 8 characters long.', error: true })
      return
    }
    setPwSaving(true)
    setPwMsg(null)
    try {
      await changePassword(currentPw, newPw)
      setPwMsg({ text: 'Password changed successfully.' })
      setCurrentPw('')
      setNewPw('')
      setConfirmPw('')
    } catch (err: unknown) {
      setPwMsg({ text: err instanceof Error ? err.message : 'Password change failed.', error: true })
    } finally {
      setPwSaving(false)
    }
  }

  return (
    <div className="p-6 max-w-4xl mx-auto space-y-8">
      <div className="border-b border-slate-800 pb-4">
        <h1 className="text-2xl font-black text-white">Account & Platform Settings</h1>
        <p className="text-xs text-slate-400 mt-1">
          Manage your personal workspace profile, security credentials, and platform appearance.
        </p>
      </div>

      {/* APPEARANCE */}
      <div className="p-6 rounded-2xl border border-slate-800 bg-slate-900/60 shadow-sm space-y-4">
        <h2 className="text-sm font-bold text-white uppercase tracking-wider">Appearance & Theme</h2>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          {[
            { id: 'system', label: 'System Default', desc: 'Adapts to OS' },
            { id: 'dark', label: 'Dark Mode', desc: 'Deep slate tones' },
            { id: 'light', label: 'Light Mode', desc: 'High contrast clean' },
            { id: 'purple_glass', label: 'Purple Glass', desc: 'Luminous neon' },
          ].map(t => (
            <button
              key={t.id}
              type="button"
              onClick={() => setPreference(t.id as any)}
              className={`p-3 rounded-xl border text-left transition-all ${
                preference === t.id
                  ? 'border-indigo-500 bg-indigo-950/40 text-white ring-1 ring-indigo-500'
                  : 'border-slate-800 bg-slate-950 hover:bg-slate-800/40 text-slate-400'
              }`}
            >
              <div className="font-semibold text-xs text-slate-200">{t.label}</div>
              <div className="text-[10px] text-slate-500 mt-0.5">{t.desc}</div>
            </button>
          ))}
        </div>
      </div>

      {/* PROFILE */}
      <form onSubmit={handleSaveProfile} className="p-6 rounded-2xl border border-slate-800 bg-slate-900/60 shadow-sm space-y-4">
        <h2 className="text-sm font-bold text-white uppercase tracking-wider">Workspace Profile</h2>
        {profileMsg && <div className="p-2.5 rounded-lg bg-indigo-950/50 border border-indigo-800 text-xs text-indigo-300">{profileMsg}</div>}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div>
            <label className="block text-xs font-medium text-slate-300 mb-1">Username</label>
            <input
              type="text"
              disabled
              value={user?.username || ''}
              className="w-full px-3 py-2 text-xs bg-slate-950/50 border border-slate-800 rounded-lg text-slate-400 cursor-not-allowed"
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-slate-300 mb-1">Email Address</label>
            <input
              type="email"
              disabled
              value={user?.email || ''}
              className="w-full px-3 py-2 text-xs bg-slate-950/50 border border-slate-800 rounded-lg text-slate-400 cursor-not-allowed"
            />
          </div>
        </div>
        <div>
          <label className="block text-xs font-medium text-slate-300 mb-1">Full Name</label>
          <input
            type="text"
            value={fullName}
            onChange={e => setFullName(e.target.value)}
            className="w-full px-3 py-2 text-xs bg-slate-950 border border-slate-700 rounded-lg text-slate-100 focus:outline-none focus:border-indigo-500"
          />
        </div>
        <div className="flex justify-end">
          <button
            type="submit"
            disabled={profileSaving}
            className="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-semibold rounded-lg shadow"
          >
            {profileSaving ? 'Saving…' : 'Save Changes'}
          </button>
        </div>
      </form>

      {/* SECURITY / PASSWORD */}
      <form onSubmit={handleChangePassword} className="p-6 rounded-2xl border border-slate-800 bg-slate-900/60 shadow-sm space-y-4">
        <h2 className="text-sm font-bold text-white uppercase tracking-wider">Security & Password</h2>
        {pwMsg && (
          <div className={`p-2.5 rounded-lg border text-xs ${pwMsg.error ? 'bg-red-950/50 border-red-800 text-red-300' : 'bg-emerald-950/50 border-emerald-800 text-emerald-300'}`}>
            {pwMsg.text}
          </div>
        )}
        <div className="space-y-3">
          <div>
            <label className="block text-xs font-medium text-slate-300 mb-1">Current Password</label>
            <input
              type="password"
              required
              value={currentPw}
              onChange={e => setCurrentPw(e.target.value)}
              className="w-full px-3 py-2 text-xs bg-slate-950 border border-slate-700 rounded-lg text-slate-100 focus:outline-none focus:border-indigo-500"
            />
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <label className="block text-xs font-medium text-slate-300 mb-1">New Password (min 8 chars)</label>
              <input
                type="password"
                required
                value={newPw}
                onChange={e => setNewPw(e.target.value)}
                className="w-full px-3 py-2 text-xs bg-slate-950 border border-slate-700 rounded-lg text-slate-100 focus:outline-none focus:border-indigo-500"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-slate-300 mb-1">Confirm New Password</label>
              <input
                type="password"
                required
                value={confirmPw}
                onChange={e => setConfirmPw(e.target.value)}
                className="w-full px-3 py-2 text-xs bg-slate-950 border border-slate-700 rounded-lg text-slate-100 focus:outline-none focus:border-indigo-500"
              />
            </div>
          </div>
        </div>
        <div className="flex justify-end">
          <button
            type="submit"
            disabled={pwSaving}
            className="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-semibold rounded-lg shadow"
          >
            {pwSaving ? 'Updating Password…' : 'Update Password'}
          </button>
        </div>
      </form>
    </div>
  )
}

