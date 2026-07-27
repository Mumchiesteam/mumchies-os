import { apiBase, apiFetch } from './orders'

export type UserRole = 'owner' | 'admin' | 'operator'
export type ManagedUser = { id: number; username: string; display_name: string; role: UserRole; is_active: boolean; created_at: string; updated_at: string; last_login_at: string | null }

async function apiError(response: Response, fallback: string): Promise<Error> {
  const body = await response.json().catch(() => null)
  const detail = body?.detail
  if (typeof detail === 'string') return new Error(detail)
  if (Array.isArray(detail) && typeof detail[0]?.msg === 'string') return new Error(detail[0].msg.replace(/^Value error, /, ''))
  return new Error(fallback)
}

export async function getUsers(): Promise<ManagedUser[]> {
  const response = await apiFetch(`${apiBase}/api/v1/users`)
  if (!response.ok) throw new Error('Could not load users.')
  return response.json()
}

export async function updateUser(id: number, update: { role?: UserRole; is_active?: boolean }): Promise<ManagedUser> {
  const response = await apiFetch(`${apiBase}/api/v1/users/${id}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(update) })
  if (!response.ok) throw await apiError(response, 'Could not update user.')
  return response.json()
}

export async function resetUserPassword(id: number, password: string, confirmation: string): Promise<void> {
  const response = await apiFetch(`${apiBase}/api/v1/users/${id}/reset-password`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ password, password_confirmation: confirmation }) })
  if (!response.ok) throw await apiError(response, 'Could not reset password.')
}

export async function createUser(payload: { username: string; display_name: string; role: Exclude<UserRole, 'owner'>; password: string; password_confirmation: string }): Promise<ManagedUser> {
  const response = await apiFetch(`${apiBase}/api/v1/users`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) })
  if (!response.ok) throw await apiError(response, 'Could not create user.')
  return response.json()
}
