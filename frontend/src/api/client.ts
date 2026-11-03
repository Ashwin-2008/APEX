const configuredBase = import.meta.env.VITE_API_URL?.trim() || '/api'
export const API_BASE = configuredBase.replace(/\/$/, '')

export const AUTH_TOKEN_KEY = 'apex.auth.token'

export function getAuthToken(): string | null {
  try {
    return localStorage.getItem(AUTH_TOKEN_KEY)
  } catch {
    return null
  }
}

export function setAuthToken(token: string | null): void {
  try {
    if (token) {
      localStorage.setItem(AUTH_TOKEN_KEY, token)
    } else {
      localStorage.removeItem(AUTH_TOKEN_KEY)
    }
  } catch {
    // Ignore storage restrictions
  }
}

export class ApiError extends Error {
  status: number
  code?: string
  constructor(message: string, status: number, code?: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
  }
}

export async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(init?.headers as Record<string, string> | undefined),
  }

  const token = getAuthToken()
  if (token && !headers['Authorization']) {
    headers['Authorization'] = `Bearer ${token}`
  }

  let response: Response
  try {
    response = await fetch(`${API_BASE}${path}`, {
      ...init,
      headers,
    })
  } catch {
    throw new ApiError('APEX could not reach the backend service. Check that the server is running on http://127.0.0.1:8000.', 0)
  }

  if (!response.ok) {
    let message = 'The request could not be completed. Please try again.'
    let code: string | undefined
    try {
      const body = await response.json() as { detail?: string; error?: string; message?: string }
      message = body.detail || body.message || message
      code = body.error
      if (response.status === 401) {
        // Broadcast token expiry / unauthorized so UI can transition gracefully
        window.dispatchEvent(new CustomEvent('apex:unauthorized'))
      }
    } catch {
      // Keep fallback
    }
    throw new ApiError(message, response.status, code)
  }
  return response.json() as Promise<T>
}
