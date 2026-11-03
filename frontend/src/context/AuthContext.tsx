import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { getCurrentUser, loginUser, registerUser, type AuthResponse } from '../api/authApi'
import { getAuthToken, setAuthToken } from '../api/client'
import type { UserProfile } from '../types/projectReview'

interface AuthContextValue {
  user: UserProfile | null
  token: string | null
  loading: boolean
  authError: string | null
  login: (emailOrUsername: string, password: string) => Promise<AuthResponse>
  register: (payload: { email: string; username: string; password: string; full_name?: string }) => Promise<AuthResponse>
  logout: () => void
  refreshUser: () => Promise<void>
}

const AuthContext = createContext<AuthContextValue | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<UserProfile | null>(null)
  const [token, setTokenState] = useState<string | null>(getAuthToken)
  const [loading, setLoading] = useState(true)
  const [authError, setAuthError] = useState<string | null>(null)

  useEffect(() => {
    const existingToken = getAuthToken()
    if (!existingToken) {
      setLoading(false)
      return
    }
    getCurrentUser()
      .then(fetchedUser => {
        setUser(fetchedUser)
        setTokenState(existingToken)
      })
      .catch(() => {
        setAuthToken(null)
        setTokenState(null)
        setUser(null)
      })
      .finally(() => {
        setLoading(false)
      })

    const handleUnauthorized = () => {
      setAuthToken(null)
      setTokenState(null)
      setUser(null)
    }
    window.addEventListener('apex:unauthorized', handleUnauthorized)
    return () => window.removeEventListener('apex:unauthorized', handleUnauthorized)
  }, [])

  const login = async (emailOrUsername: string, password: string) => {
    setAuthError(null)
    try {
      const resp = await loginUser(emailOrUsername, password)
      setTokenState(resp.token)
      setUser(resp.user)
      return resp
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Login failed'
      setAuthError(msg)
      throw err
    }
  }

  const register = async (payload: { email: string; username: string; password: string; full_name?: string }) => {
    setAuthError(null)
    try {
      const resp = await registerUser(payload)
      setTokenState(resp.token)
      setUser(resp.user)
      return resp
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Registration failed'
      setAuthError(msg)
      throw err
    }
  }

  const logout = () => {
    setAuthToken(null)
    setTokenState(null)
    setUser(null)
    localStorage.removeItem('mistiq.project.context')
    localStorage.removeItem('apex.selected.projectId')
  }

  const refreshUser = async () => {
    try {
      const u = await getCurrentUser()
      setUser(u)
    } catch {
      // Ignore
    }
  }

  const value = useMemo<AuthContextValue>(
    () => ({
      user,
      token,
      loading,
      authError,
      login,
      register,
      logout,
      refreshUser,
    }),
    [user, token, loading, authError]
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

const defaultAuthContext: AuthContextValue = {
  user: null,
  token: null,
  loading: false,
  authError: null,
  login: async () => ({ token: '', token_type: 'bearer', expires_in: 0, user: { id: 0, email: '', username: '', role: 'user', created_at: '' } }),
  register: async () => ({ token: '', token_type: 'bearer', expires_in: 0, user: { id: 0, email: '', username: '', role: 'user', created_at: '' } }),
  logout: () => {},
  refreshUser: async () => {},
}

export function useAuth() {
  const context = useContext(AuthContext)
  return context || defaultAuthContext
}
