import { apiBase, apiFetch } from './orders'

export type UserRole = 'owner' | 'admin' | 'operator'
export type ManagedUser = { id: number; username: string; display_name: string; role: UserRole; is_active: boolean; created_at: string; updated_at: string; last_login_at: string | null }

export async function getUsers(): Promise<ManagedUser[]> {
  const response = await apiFetch(`${apiBase}/api/v1/users`)
  if (!response.ok) throw new Error('Could not load users.')
  return response.json()
}

export async function updateUser(id: number, update: { role?: UserRole; is_active?: boolean }): Promise<ManagedUser> {
  const response = await apiFetch(`${apiBase}/api/v1/users/${id}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(update) })
  if (!response.ok) throw new Error((await response.json().catch(() => null))?.detail || 'Could not update user.')
  return response.json()
}

export async function resetUserPassword(id: number, password: string, confirmation: string): Promise<void> {
  const response = await apiFetch(`${apiBase}/api/v1/users/${id}/reset-password`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ password, password_confirmation: confirmation }) })
  if (!response.ok) throw new Error((await response.json().catch(() => null))?.detail || 'Could not reset password.')
}
