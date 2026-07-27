import { useEffect, useState, type FormEvent, type ReactNode } from 'react'

import { createUser, getUsers, resetUserPassword, updateUser, type ManagedUser, type UserRole } from '../services/users'

const inputClass = 'mt-1 w-full rounded-md border border-slate-200 px-3 py-2 outline-none focus:border-orange-300 focus:ring-2 focus:ring-orange-100'

export function UsersPage() {
  const [users, setUsers] = useState<ManagedUser[]>([])
  const [showCreate, setShowCreate] = useState(false)
  const [resetId, setResetId] = useState<number | null>(null)
  const [notice, setNotice] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const refresh = () => void getUsers().then(setUsers).catch(loadError => setError(loadError.message))
  useEffect(refresh, [])
  const replace = (user: ManagedUser) => setUsers(current => current.map(value => value.id === user.id ? user : value))
  const succeed = (message: string) => { setError(''); setNotice(message) }
  const fail = (actionError: unknown) => { setNotice(''); setError(actionError instanceof Error ? actionError.message : 'Something went wrong.') }

  const submitCreate = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const form = event.currentTarget
    const values = new FormData(form)
    setBusy(true); setError('')
    try {
      await createUser({
        username: String(values.get('username') || ''),
        display_name: String(values.get('display_name') || ''),
        role: String(values.get('role') || 'operator') as 'admin' | 'operator',
        password: String(values.get('password') || ''),
        password_confirmation: String(values.get('password_confirmation') || ''),
      })
      form.reset()
      setShowCreate(false)
      succeed('User created successfully.')
      refresh()
    } catch (actionError) { fail(actionError) } finally { setBusy(false) }
  }

  const submitReset = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (resetId === null) return
    const form = event.currentTarget
    const values = new FormData(form)
    setBusy(true); setError('')
    try {
      await resetUserPassword(resetId, String(values.get('password') || ''), String(values.get('password_confirmation') || ''))
      form.reset()
      setResetId(null)
      succeed('Password reset successfully.')
      refresh()
    } catch (actionError) { fail(actionError) } finally { setBusy(false) }
  }

  return <div>
    <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
      <div><p className="text-sm font-medium text-[#ff6b35]">Settings</p><h2 className="mt-1 text-2xl font-bold tracking-tight">Users</h2><p className="mt-1 text-sm text-slate-500">Manage access, roles, and password resets.</p></div>
      <button onClick={() => { setShowCreate(true); setError(''); setNotice('') }} className="rounded-lg bg-slate-900 px-4 py-2.5 text-sm font-semibold text-white">Add User</button>
    </div>
    {notice && <p role="status" className="mb-4 rounded-lg bg-emerald-50 px-3 py-2 text-sm text-emerald-700">{notice}</p>}
    {error && <p role="alert" className="mb-4 rounded-lg bg-rose-50 px-3 py-2 text-sm text-rose-700">{error}</p>}
    <section className="overflow-x-auto rounded-xl border border-slate-200 bg-white shadow-sm"><table className="w-full text-left text-sm"><thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500"><tr><th className="px-4 py-3">Username</th><th className="px-4 py-3">Display Name</th><th className="px-4 py-3">Role</th><th className="px-4 py-3">Status</th><th className="px-4 py-3">Last Login</th><th className="px-4 py-3">Actions</th></tr></thead><tbody className="divide-y divide-slate-100">{users.map(user => <tr key={user.id}><td className="px-4 py-3 font-mono text-xs text-slate-600">{user.username}</td><td className="px-4 py-3 font-semibold text-slate-800">{user.display_name}</td><td className="px-4 py-3"><select aria-label={`Role for ${user.username}`} disabled={user.role === 'owner'} value={user.role} onChange={event => void updateUser(user.id, { role: event.target.value as UserRole }).then(updated => { replace(updated); succeed('Role updated.') }).catch(fail)} className="rounded-md border border-slate-200 px-2 py-1.5 disabled:bg-slate-50 disabled:text-slate-500"><option value="owner" disabled>Owner</option><option value="admin">Admin</option><option value="operator">Operator</option></select></td><td className="px-4 py-3"><span className={`rounded-full px-2 py-1 text-xs font-semibold ${user.is_active ? 'bg-emerald-50 text-emerald-700' : 'bg-slate-100 text-slate-500'}`}>{user.is_active ? 'Active' : 'Inactive'}</span></td><td className="px-4 py-3 text-xs text-slate-500">{user.last_login_at ? new Date(user.last_login_at).toLocaleString('en-IN') : 'Never'}</td><td className="px-4 py-3"><div className="flex gap-2"><button disabled={user.role === 'owner'} onClick={() => void updateUser(user.id, { is_active: !user.is_active }).then(updated => { replace(updated); succeed(updated.is_active ? 'User activated.' : 'User deactivated.') }).catch(fail)} className="rounded-md border border-slate-200 px-2 py-1.5 text-xs font-semibold disabled:opacity-40">{user.is_active ? 'Deactivate' : 'Activate'}</button><button onClick={() => { setResetId(user.id); setError(''); setNotice('') }} className="rounded-md border border-slate-200 px-2 py-1.5 text-xs font-semibold">Reset Password</button></div></td></tr>)}</tbody></table></section>

    {showCreate && <Modal title="Create User" onClose={() => setShowCreate(false)}><form onSubmit={submitCreate}><label className="block text-sm">Username<input name="username" autoComplete="off" required maxLength={64} className={inputClass} /></label><label className="mt-3 block text-sm">Display Name<input name="display_name" autoComplete="name" required maxLength={120} className={inputClass} /></label><label className="mt-3 block text-sm">Role<select name="role" defaultValue="operator" className={inputClass}><option value="admin">Admin</option><option value="operator">Operator</option></select></label><label className="mt-3 block text-sm">Password<input name="password" autoComplete="new-password" type="password" minLength={12} required className={inputClass} /></label><label className="mt-3 block text-sm">Confirm Password<input name="password_confirmation" autoComplete="new-password" type="password" minLength={12} required className={inputClass} /></label><Actions busy={busy} onCancel={() => setShowCreate(false)} submitLabel="Create User" /></form></Modal>}
    {resetId !== null && <Modal title="Reset Password" onClose={() => setResetId(null)}><form onSubmit={submitReset}><label className="block text-sm">New Password<input name="password" autoComplete="new-password" type="password" minLength={12} required className={inputClass} /></label><label className="mt-3 block text-sm">Confirm Password<input name="password_confirmation" autoComplete="new-password" type="password" minLength={12} required className={inputClass} /></label><Actions busy={busy} onCancel={() => setResetId(null)} submitLabel="Reset Password" /></form></Modal>}
  </div>
}

function Modal({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  return <div className="fixed inset-0 z-50 grid place-items-center bg-slate-950/40 p-4" role="dialog" aria-modal="true" aria-label={title}><section className="w-full max-w-md rounded-xl bg-white p-5 shadow-xl"><div className="mb-4 flex items-center justify-between"><h3 className="text-lg font-bold">{title}</h3><button type="button" onClick={onClose} aria-label="Close" className="text-xl text-slate-400">×</button></div>{children}</section></div>
}

function Actions({ busy, onCancel, submitLabel }: { busy: boolean; onCancel: () => void; submitLabel: string }) {
  return <div className="mt-5 flex justify-end gap-2"><button type="button" onClick={onCancel} className="px-3 py-2 text-sm">Cancel</button><button disabled={busy} className="rounded-md bg-slate-900 px-3 py-2 text-sm font-semibold text-white disabled:opacity-60">{busy ? 'Saving…' : submitLabel}</button></div>
}
