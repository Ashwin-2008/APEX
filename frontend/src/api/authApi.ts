import { request, setAuthToken } from './client'
import type { UserProfile } from '../types/projectReview'

export interface AuthResponse {
  token: string
  token_type: string
  user: UserProfile
}

export async function loginUser(emailOrUsername: string, password: string): Promise<AuthResponse> {
  const data = await request<AuthResponse>('/auth/login', {
    method: 'POST',
    body: JSON.stringify({ email_or_username: emailOrUsername, password }),
  })
  setAuthToken(data.token)
  return data
}

export async function registerUser(payload: {
  email: string
  username: string
  password: string
  full_name?: string
  preferences?: Record<string, unknown>
}): Promise<AuthResponse> {
  const data = await request<AuthResponse>('/auth/register', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
  setAuthToken(data.token)
  return data
}

export async function getCurrentUser(): Promise<UserProfile> {
  const data = await request<{ user: UserProfile }>('/auth/me')
  return data.user
}

export async function updateUserProfile(patch: {
  full_name?: string
  email?: string
  preferences?: Record<string, unknown>
}): Promise<UserProfile> {
  const data = await request<{ user: UserProfile }>('/auth/profile', {
    method: 'PATCH',
    body: JSON.stringify(patch),
  })
  return data.user
}

export async function changePassword(currentPassword: string, newPassword: string): Promise<void> {
  await request<{ status: string }>('/auth/change-password', {
    method: 'POST',
    body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
  })
}

