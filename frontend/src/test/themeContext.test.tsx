import { act, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ThemeProvider, useTheme } from '../context/ThemeContext'

type Listener = (event: { matches: boolean }) => void

function stubMatchMedia(initialDark: boolean) {
  let dark = initialDark
  const listeners = new Set<Listener>()
  const api = (query: string) => ({
    get matches() { return query.includes('prefers-color-scheme: dark') ? dark : false },
    media: query,
    onchange: null,
    addEventListener: (_type: string, listener: Listener) => { listeners.add(listener) },
    removeEventListener: (_type: string, listener: Listener) => { listeners.delete(listener) },
    addListener: (listener: Listener) => { listeners.add(listener) },
    removeListener: (listener: Listener) => { listeners.delete(listener) },
    dispatchEvent: () => false,
  })
  vi.stubGlobal('matchMedia', api)
  return {
    setDark(value: boolean) {
      dark = value
      listeners.forEach(listener => listener({ matches: value }))
    },
  }
}

function Probe() {
  const { preference, setPreference } = useTheme()
  return (
    <div>
      <span data-testid="preference">{preference}</span>
      <button onClick={() => setPreference('light')}>Use light</button>
      <button onClick={() => setPreference('dark')}>Use dark</button>
      <button onClick={() => setPreference('system')}>Use system</button>
    </div>
  )
}

function renderTheme() {
  return render(<ThemeProvider><Probe /></ThemeProvider>)
}

describe('theme context', () => {
  afterEach(() => { vi.unstubAllGlobals(); localStorage.clear(); document.documentElement.removeAttribute('data-theme') })

  it('defaults to the system preference and applies the resolved theme', () => {
    stubMatchMedia(false)
    renderTheme()
    expect(screen.getByTestId('preference').textContent).toBe('system')
    expect(document.documentElement.dataset.theme).toBe('light')
    expect(localStorage.getItem('mistiq.theme')).toBe('system')
  })

  it('applies the light theme and stores it', () => {
    stubMatchMedia(false)
    renderTheme()
    fireEvent.click(screen.getByRole('button', { name: 'Use light' }))
    expect(screen.getByTestId('preference').textContent).toBe('light')
    expect(document.documentElement.dataset.theme).toBe('light')
    expect(localStorage.getItem('mistiq.theme')).toBe('light')
  })

  it('applies the dark theme and stores it', () => {
    stubMatchMedia(false)
    renderTheme()
    fireEvent.click(screen.getByRole('button', { name: 'Use dark' }))
    expect(screen.getByTestId('preference').textContent).toBe('dark')
    expect(document.documentElement.dataset.theme).toBe('dark')
    expect(localStorage.getItem('mistiq.theme')).toBe('dark')
  })

  it('follows the system preference in system mode and reacts to changes', () => {
    const media = stubMatchMedia(true)
    renderTheme()
    expect(screen.getByTestId('preference').textContent).toBe('system')
    expect(document.documentElement.dataset.theme).toBe('dark')

    act(() => { media.setDark(false) })
    expect(document.documentElement.dataset.theme).toBe('light')

    act(() => { media.setDark(true) })
    expect(document.documentElement.dataset.theme).toBe('dark')
  })

  it('restores the stored preference after a reload', () => {
    stubMatchMedia(false)
    localStorage.setItem('mistiq.theme', 'dark')
    renderTheme()
    expect(screen.getByTestId('preference').textContent).toBe('dark')
    expect(document.documentElement.dataset.theme).toBe('dark')
  })

  it('rejects theme usage outside of the provider', () => {
    const spy = vi.spyOn(console, 'error').mockImplementation(() => {})
    expect(() => render(<Probe />)).toThrow('useTheme must be used inside ThemeProvider')
    spy.mockRestore()
  })
})
