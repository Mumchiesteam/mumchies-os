import { afterEach, describe, expect, it, vi } from 'vitest'

import { getUsers, resetUserPassword, updateUser } from './users'

afterEach(() => vi.restoreAllMocks())

describe('owner user-management client', () => {
  it('loads the user list without credentials in query parameters', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('[]', { status: 200, headers: { 'Content-Type': 'application/json' } }))
    await getUsers()
    expect(String(fetchMock.mock.calls[0][0])).toContain('/api/v1/users')
    expect(String(fetchMock.mock.calls[0][0])).not.toContain('password')
  })

  it('sends only role and activation changes', async () => {
    const user = { id: 2, username: 'ajit', display_name: 'Ajit', role: 'operator', is_active: false, created_at: '', updated_at: '', last_login_at: null }
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify(user), { status: 200, headers: { 'Content-Type': 'application/json' } }))
    await updateUser(2, { role: 'operator', is_active: false })
    expect(JSON.parse(String((fetchMock.mock.calls[0][1] as RequestInit).body))).toEqual({ role: 'operator', is_active: false })
  })

  it('uses the dedicated password-reset endpoint', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('{}', { status: 200 }))
    await resetUserPassword(2, 'replacement-pass-123', 'replacement-pass-123')
    expect(String(fetchMock.mock.calls[0][0])).toContain('/api/v1/users/2/reset-password')
    expect((fetchMock.mock.calls[0][1] as RequestInit).method).toBe('POST')
  })
})
