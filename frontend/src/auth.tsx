import { type FormEvent, type ReactNode, useEffect, useState } from 'react'

import { apiBase } from './services/orders'
import { setCsrfToken } from './services/auth-state'

type AuthState = 'loading' | 'authenticated' | 'unauthenticated'

export default function AuthGate({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AuthState>('loading')
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)

  useEffect(() => {
    const unauthorised = () => setState('unauthenticated')
    window.addEventListener('mumchies:unauthorised', unauthorised)
    void fetch(`${apiBase}/api/v1/auth/session`, { credentials: 'include' })
      .then(async response => {
        if (!response.ok) return setState('unauthenticated')
        const session = await response.json()
        setCsrfToken(session.csrf_token)
        setState('authenticated')
      })
      .catch(() => {
        setError('Could not reach Mumchies OS. Check the server and try again.')
        setState('unauthenticated')
      })
    return () => window.removeEventListener('mumchies:unauthorised', unauthorised)
  }, [])

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setSubmitting(true)
    setError('')
    const form = new FormData(event.currentTarget)
    try {
      const response = await fetch(`${apiBase}/api/v1/auth/login`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          username: String(form.get('username') || ''),
          password: String(form.get('password') || ''),
        }),
      })
      if (!response.ok) {
        const body = await response.json().catch(() => null)
        setError(body?.detail || 'Invalid username or password.')
        return
      }
      const session = await response.json()
      setCsrfToken(session.csrf_token)
      setState('authenticated')
    } catch {
      setError('Could not reach Mumchies OS. Check the server and try again.')
    } finally {
      setSubmitting(false)
    }
  }

  if (state === 'loading') {
    return <main className="grid min-h-screen place-items-center bg-slate-50 text-sm text-slate-500">Checking session…</main>
  }
  if (state === 'authenticated') return children

  return (
    <main className="grid min-h-screen place-items-center bg-slate-50 px-4">
      <section className="w-full max-w-sm rounded-2xl border border-slate-200 bg-white p-7 shadow-sm">
        <div className="mb-6 flex items-center gap-3">
          <div className="grid h-11 w-11 place-items-center rounded-xl bg-[#ff6b35] text-xl font-black text-white">m</div>
          <div>
            <p className="text-xs font-bold uppercase tracking-[.14em] text-slate-400">Mumchies OS</p>
            <h1 className="text-xl font-bold text-slate-900">Sign in</h1>
          </div>
        </div>
        <form className="space-y-4" onSubmit={submit}>
          <label className="block text-sm font-medium text-slate-700">
            Username
            <input name="username" autoComplete="username" required autoFocus className="mt-1.5 w-full rounded-lg border border-slate-200 px-3 py-2.5 outline-none focus:border-orange-300 focus:ring-2 focus:ring-orange-100" />
          </label>
          <label className="block text-sm font-medium text-slate-700">
            Password
            <input name="password" type="password" autoComplete="current-password" required className="mt-1.5 w-full rounded-lg border border-slate-200 px-3 py-2.5 outline-none focus:border-orange-300 focus:ring-2 focus:ring-orange-100" />
          </label>
          {error && <p role="alert" className="rounded-lg bg-rose-50 px-3 py-2 text-sm text-rose-700">{error}</p>}
          <button disabled={submitting} className="w-full rounded-lg bg-slate-900 px-4 py-2.5 text-sm font-semibold text-white disabled:opacity-60">
            {submitting ? 'Signing in…' : 'Sign in'}
          </button>
        </form>
      </section>
    </main>
  )
}
