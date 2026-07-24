import { apiBase } from './orders'
import { setCsrfToken } from './auth-state'

export async function logout(): Promise<void> {
  await fetch(`${apiBase}/api/v1/auth/logout`, {
    method: 'POST',
    credentials: 'include',
  })
  setCsrfToken('')
  window.dispatchEvent(new Event('mumchies:unauthorised'))
}
