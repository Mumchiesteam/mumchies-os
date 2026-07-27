import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import { ReconciliationUnavailable } from './components/ReconciliationUnavailable'
import { UsersPage } from './components/UsersPage'

describe('authentication sprint polish', () => {
  it('shows owner user-management columns and Add User action', () => {
    const html = renderToStaticMarkup(<UsersPage />)
    for (const label of ['Add User', 'Username', 'Display Name', 'Role', 'Status', 'Last Login', 'Actions']) expect(html).toContain(label)
  })

  it('uses a non-broken reconciliation placeholder and disabled refresh', () => {
    const html = renderToStaticMarkup(<section><button disabled>Refresh reconciliation</button><ReconciliationUnavailable /></section>)
    expect(html).toContain('This feature will be enabled after the reconciliation engine is implemented.')
    expect(html).toMatch(/<button disabled=""[^>]*>Refresh reconciliation<\/button>/)
    expect(html).not.toContain('Reconciliation data is unavailable')
  })
})
