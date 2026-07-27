import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import { ComingSoonPage } from './components/ComingSoonPage'
import { ReconciliationUnavailable } from './components/ReconciliationUnavailable'
import { UsersPage } from './components/UsersPage'

describe('authentication sprint polish', () => {
  it('shows owner user-management columns and Add User action', () => {
    const html = renderToStaticMarkup(<UsersPage />)
    for (const label of ['Add User', 'Username', 'Display Name', 'Role', 'Status', 'Last Login', 'Actions']) expect(html).toContain(label)
  })

  it('renders a clear NDR coming-soon page', () => {
    const html = renderToStaticMarkup(<ComingSoonPage title="NDR Dashboard" message="NDR Dashboard will be enabled in Sprint 2 after the backend sync engine is complete." />)
    expect(html).toContain('Coming Soon')
    expect(html).toContain('Sprint 2')
  })

  it('uses a non-broken reconciliation placeholder and disabled refresh', () => {
    const html = renderToStaticMarkup(<section><button disabled>Refresh reconciliation</button><ReconciliationUnavailable /></section>)
    expect(html).toContain('This feature will be enabled after the reconciliation engine is implemented.')
    expect(html).toMatch(/<button disabled=""[^>]*>Refresh reconciliation<\/button>/)
    expect(html).not.toContain('Reconciliation data is unavailable')
  })
})
