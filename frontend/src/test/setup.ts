import { cleanup } from '@testing-library/react'
import { afterEach } from 'vitest'

function createMatchMediaStub(): (query: string) => MediaQueryList {
  return (query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => false,
  } as MediaQueryList)
}

if (typeof window.matchMedia !== 'function') {
  Object.defineProperty(window, 'matchMedia', { writable: true, configurable: true, value: createMatchMediaStub() })
}

afterEach(() => {
  cleanup()
  localStorage.clear()
  document.documentElement.removeAttribute('data-theme')
})
