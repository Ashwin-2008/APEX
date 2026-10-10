import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'

export type ThemePreference = 'light' | 'dark' | 'purple' | 'system'

interface ThemeContextValue {
  preference: ThemePreference
  setPreference: (preference: ThemePreference) => void
}

const STORAGE_KEY = 'mistiq.theme'
const ThemeContext = createContext<ThemeContextValue | null>(null)

function readPreference(): ThemePreference {
  const value = localStorage.getItem(STORAGE_KEY)
  return value === 'dark' || value === 'light' || value === 'purple' || value === 'system' ? value : 'system'
}

function systemPrefersDark(): boolean {
  return typeof window.matchMedia === 'function' && window.matchMedia('(prefers-color-scheme: dark)').matches
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [preference, setPreferenceState] = useState<ThemePreference>(readPreference)

  useEffect(() => {
    const root = document.documentElement
    if (preference === 'purple') {
      root.dataset.theme = 'purple'
    } else if (preference === 'dark') {
      root.dataset.theme = 'dark'
    } else if (preference === 'light') {
      root.dataset.theme = 'light'
    } else {
      root.dataset.theme = systemPrefersDark() ? 'dark' : 'light'
    }
    localStorage.setItem(STORAGE_KEY, preference)
  }, [preference])

  useEffect(() => {
    if (preference !== 'system' || typeof window.matchMedia !== 'function') return
    const media = window.matchMedia('(prefers-color-scheme: dark)')
    const update = () => { document.documentElement.dataset.theme = media.matches ? 'dark' : 'light' }
    media.addEventListener?.('change', update)
    return () => media.removeEventListener?.('change', update)
  }, [preference])

  const value = useMemo(() => ({ preference, setPreference: setPreferenceState }), [preference])
  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>
}

export function useTheme() {
  const value = useContext(ThemeContext)
  if (!value) throw new Error('useTheme must be used inside ThemeProvider')
  return value
}
