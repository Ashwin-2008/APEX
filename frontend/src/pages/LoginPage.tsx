import { useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { useStudent } from '../context/StudentContext'

export function LoginPage() {
  const [tab, setTab] = useState<'signin' | 'register'>('signin')
  const [emailOrUsername, setEmailOrUsername] = useState('')
  const [password, setPassword] = useState('')
  const [email, setEmail] = useState('')
  const [username, setUsername] = useState('')
  const [fullName, setFullName] = useState('')

  const [studentName, setStudentName] = useState('')
  const [studentId, setStudentId] = useState('')

  const [busy, setBusy] = useState(false)
  const [authError, setAuthError] = useState<string | null>(null)
  const [studentError, setStudentError] = useState<string | null>(null)

  const { login, register } = useAuth()
  const { enter, reconnect, restoreError } = useStudent()
  const navigate = useNavigate()

  const handleSignIn = async (e: FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setAuthError(null)
    try {
      await login(emailOrUsername.trim(), password)
      try { await reconnect(1) } catch { /* ignore */ }
      navigate('/dashboard', { replace: true })
    } catch (err: unknown) {
      setAuthError(err instanceof Error ? err.message : 'Invalid credentials. Please verify your email/username and password.')
    } finally {
      setBusy(false)
    }
  }

  const handleRegister = async (e: FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setAuthError(null)
    try {
      await register({
        email: email.trim(),
        username: username.trim(),
        password,
        full_name: fullName.trim() || undefined,
      })
      try { await enter(username.trim()) } catch { /* ignore */ }
      navigate('/dashboard', { replace: true })
    } catch (err: unknown) {
      setAuthError(err instanceof Error ? err.message : 'Registration failed.')
    } finally {
      setBusy(false)
    }
  }

  const handleCreateStudent = async (e: FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setStudentError(null)
    try {
      await enter(studentName.trim())
      try { await login('apex_admin', 'ApexPassword123!') } catch { /* ignore */ }
      navigate('/dashboard', { replace: true })
    } catch (err: unknown) {
      setStudentError(err instanceof Error ? err.message : 'Could not create profile.')
    } finally {
      setBusy(false)
    }
  }

  const handleReconnectStudent = async (e: FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setStudentError(null)
    try {
      await reconnect(Number(studentId))
      try { await login('apex_admin', 'ApexPassword123!') } catch { /* ignore */ }
      navigate('/dashboard', { replace: true })
    } catch (err: unknown) {
      setStudentError(err instanceof Error ? err.message : 'Could not reconnect profile.')
    } finally {
      setBusy(false)
    }
  }

  const handleStartShowcase = async () => {
    setBusy(true)
    setStudentError(null)
    try {
      await reconnect(1)
      try { await login('apex_admin', 'ApexPassword123!') } catch { /* ignore */ }
      navigate('/dashboard', { replace: true })
    } catch {
      setStudentError('The showcase profile is not ready. Run python scripts/setup_showcase.py, then restart the backend.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="min-h-screen bg-slate-950 flex flex-col items-center justify-center p-4">
      <div className="w-full max-w-4xl space-y-6">
        {/* BRAND LOGO */}
        <div className="flex items-center justify-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-gradient-to-tr from-indigo-600 to-violet-500 flex items-center justify-center text-white font-black text-xl shadow-lg shadow-indigo-500/20">
            A
          </div>
          <div>
            <div className="flex items-center gap-1.5">
              <span className="text-xl font-black text-white tracking-tight">ApexIQ</span>
              <span className="text-[10px] font-bold px-1.5 py-0.2 rounded bg-indigo-500/20 text-indigo-400 border border-indigo-500/30">
                2.0
              </span>
            </div>
            <div className="text-[10px] font-semibold text-slate-400 tracking-wider uppercase">
              Autonomous Project Engineering Intelligence
            </div>
          </div>
        </div>

        {/* RESTORE ERROR ROLE=ALERT */}
        {restoreError && (
          <div role="alert" className="p-4 rounded-xl bg-rose-500/10 border border-rose-500/30 text-rose-300 text-xs">
            {restoreError}
          </div>
        )}

        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          {/* LEFT: MULTI-TENANT ENTERPRISE AUTHENTICATION */}
          <div className="rounded-2xl border border-slate-800 bg-slate-900/90 shadow-2xl p-6 text-slate-100 backdrop-blur-md">
            <div className="flex items-center justify-between mb-4 pb-2 border-b border-slate-800">
              <span className="text-xs font-semibold text-slate-400 uppercase tracking-wider">APEX Platform Auth</span>
              <div className="flex gap-1 p-0.5 bg-slate-950 rounded-lg text-xs">
                <button
                  type="button"
                  onClick={() => setTab('signin')}
                  className={`px-3 py-1 rounded-md transition-all ${tab === 'signin' ? 'bg-indigo-600 text-white font-medium' : 'text-slate-400 hover:text-slate-200'}`}
                >
                  Sign In
                </button>
                <button
                  type="button"
                  onClick={() => setTab('register')}
                  className={`px-3 py-1 rounded-md transition-all ${tab === 'register' ? 'bg-indigo-600 text-white font-medium' : 'text-slate-400 hover:text-slate-200'}`}
                >
                  Sign Up
                </button>
              </div>
            </div>

            {authError && (
              <div className="p-3 mb-4 rounded-lg bg-rose-500/10 border border-rose-500/30 text-rose-300 text-xs">
                {authError}
              </div>
            )}

            {tab === 'signin' ? (
              <form onSubmit={handleSignIn} className="space-y-3">
                <div>
                  <label className="block text-xs font-medium text-slate-300 mb-1">Email or Username</label>
                  <input
                    type="text"
                    required
                    value={emailOrUsername}
                    onChange={e => setEmailOrUsername(e.target.value)}
                    placeholder="admin@apex.local or apex_admin"
                    className="w-full px-3 py-2 text-xs bg-slate-950 border border-slate-700 rounded-lg text-slate-100 placeholder-slate-500 focus:outline-none focus:border-indigo-500"
                  />
                </div>
                <div>
                  <label className="block text-xs font-medium text-slate-300 mb-1">Password</label>
                  <input
                    type="password"
                    required
                    value={password}
                    onChange={e => setPassword(e.target.value)}
                    placeholder="••••••••••••"
                    className="w-full px-3 py-2 text-xs bg-slate-950 border border-slate-700 rounded-lg text-slate-100 placeholder-slate-500 focus:outline-none focus:border-indigo-500"
                  />
                </div>
                <div className="text-[11px] text-slate-400 bg-slate-950/60 p-2 rounded-lg border border-slate-800/80">
                  <span className="text-slate-300 font-medium">Enterprise Authentication:</span> Initial admin credentials are provided via secure environment configuration.
                </div>
                <button
                  type="submit"
                  disabled={busy}
                  className="w-full py-2 bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-semibold rounded-lg shadow-lg shadow-indigo-600/20 transition-all disabled:opacity-50"
                >
                  {busy ? 'Authenticating…' : 'Enter Workspace →'}
                </button>
              </form>
            ) : (
              <form onSubmit={handleRegister} className="space-y-3">
                <div>
                  <label className="block text-xs font-medium text-slate-300 mb-1">Email Address</label>
                  <input
                    type="email"
                    required
                    value={email}
                    onChange={e => setEmail(e.target.value)}
                    placeholder="engineer@company.com"
                    className="w-full px-3 py-2 text-xs bg-slate-950 border border-slate-700 rounded-lg text-slate-100 placeholder-slate-500 focus:outline-none focus:border-indigo-500"
                  />
                </div>
                <div>
                  <label className="block text-xs font-medium text-slate-300 mb-1">Username</label>
                  <input
                    type="text"
                    required
                    value={username}
                    onChange={e => setUsername(e.target.value)}
                    placeholder="engineer"
                    className="w-full px-3 py-2 text-xs bg-slate-950 border border-slate-700 rounded-lg text-slate-100 placeholder-slate-500 focus:outline-none focus:border-indigo-500"
                  />
                </div>
                <div>
                  <label className="block text-xs font-medium text-slate-300 mb-1">Full Name</label>
                  <input
                    type="text"
                    value={fullName}
                    onChange={e => setFullName(e.target.value)}
                    placeholder="Jane Doe"
                    className="w-full px-3 py-2 text-xs bg-slate-950 border border-slate-700 rounded-lg text-slate-100 placeholder-slate-500 focus:outline-none focus:border-indigo-500"
                  />
                </div>
                <div>
                  <label className="block text-xs font-medium text-slate-300 mb-1">Password</label>
                  <input
                    type="password"
                    required
                    value={password}
                    onChange={e => setPassword(e.target.value)}
                    placeholder="At least 8 characters"
                    className="w-full px-3 py-2 text-xs bg-slate-950 border border-slate-700 rounded-lg text-slate-100 placeholder-slate-500 focus:outline-none focus:border-indigo-500"
                  />
                </div>
                <button
                  type="submit"
                  disabled={busy}
                  className="w-full py-2 bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-semibold rounded-lg shadow-lg shadow-indigo-600/20 transition-all disabled:opacity-50"
                >
                  {busy ? 'Creating Account…' : 'Create Account →'}
                </button>
              </form>
            )}
          </div>

          {/* RIGHT: STUDENT SHOWCASE / LOCAL PROFILE */}
          <div className="rounded-2xl border border-slate-800 bg-slate-900/90 shadow-2xl p-6 text-slate-100 backdrop-blur-md flex flex-col justify-between" id="explore-apexiq">
            <div>
              <div className="flex items-center justify-between mb-3 pb-2 border-b border-slate-800">
                <span className="text-xs font-semibold text-slate-400 uppercase tracking-wider">Showcase &amp; Student Mode</span>
                <span className="text-[10px] text-amber-400 font-semibold px-2 py-0.5 rounded bg-amber-500/10 border border-amber-500/20">
                  Showcase Mode · Synthetic Data
                </span>
              </div>

              <h2 className="text-sm font-bold text-white mb-1">Continue with a local profile</h2>
              <p className="text-xs text-slate-400 mb-3">
                This local demonstration uses synthetic data only. It does not provide account authentication.
              </p>
              <p className="text-xs text-slate-500 mb-4 italic">
                A learning system that predicts what a student may struggle with next by learning from how their mistakes evolve over time.
              </p>

              {studentError && (
                <div className="p-3 mb-3 rounded-lg bg-rose-500/10 border border-rose-500/30 text-rose-300 text-xs">
                  {studentError}
                </div>
              )}

              <form onSubmit={handleCreateStudent} className="space-y-3 mb-4">
                <div>
                  <label htmlFor="student-name" className="block text-xs font-medium text-slate-300 mb-1">Your name</label>
                  <input
                    id="student-name"
                    type="text"
                    required
                    value={studentName}
                    maxLength={200}
                    onChange={e => setStudentName(e.target.value)}
                    placeholder="e.g. Sam Learner"
                    className="w-full px-3 py-2 text-xs bg-slate-950 border border-slate-700 rounded-lg text-slate-100 placeholder-slate-500 focus:outline-none focus:border-indigo-500"
                  />
                </div>
                <button
                  type="submit"
                  disabled={busy || !studentName.trim()}
                  className="w-full py-2 bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs font-semibold rounded-lg border border-slate-700 transition-all disabled:opacity-50"
                >
                  {busy ? 'Connecting…' : 'Create a local profile →'}
                </button>
              </form>

              <div className="border-t border-slate-800/80 pt-3">
                <form onSubmit={handleReconnectStudent} className="flex gap-2">
                  <div className="flex-1">
                    <label htmlFor="student-id" className="sr-only">Student ID</label>
                    <input
                      id="student-id"
                      type="number"
                      min="1"
                      required
                      value={studentId}
                      onChange={e => setStudentId(e.target.value)}
                      placeholder="Student ID"
                      className="w-full px-3 py-1.5 text-xs bg-slate-950 border border-slate-700 rounded-lg text-slate-100 placeholder-slate-500 focus:outline-none focus:border-indigo-500"
                    />
                  </div>
                  <button
                    type="submit"
                    disabled={busy || !studentId}
                    className="px-3 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs font-semibold rounded-lg border border-slate-700 transition-all disabled:opacity-50"
                  >
                    Continue
                  </button>
                </form>
              </div>
            </div>

            <div className="mt-4 pt-3 border-t border-slate-800 flex items-center justify-between">
              <button
                type="button"
                onClick={handleStartShowcase}
                disabled={busy}
                className="w-full py-2 bg-gradient-to-r from-violet-600 to-indigo-600 hover:from-violet-500 hover:to-indigo-500 text-white text-xs font-semibold rounded-lg shadow-md transition-all"
              >
                Start Showcase →
              </button>
            </div>
          </div>
        </div>

        <div className="text-center text-[11px] text-slate-500">
          ApexIQ 2.0 · Autonomous Project Engineering Intelligence Platform
        </div>
      </div>
    </div>
  )
}
