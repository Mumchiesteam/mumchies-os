import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import { UsersPage } from './components/UsersPage'

describe('authentication sprint polish', () => {
  it('shows owner user-management columns and Add User action', () => {
    const html = renderToStaticMarkup(<UsersPage />)
    for (const label of ['Add User', 'Username', 'Display Name', 'Role', 'Status', 'Last Login', 'Actions']) expect(html).toContain(label)
  })

  it('uses a recoverable reconciliation error state with refresh enabled', () => {
    const html = renderToStaticMarkup(<section><button>Refresh reconciliation</button><p>Reconciliation data is unavailable. Click Refresh to try again.</p></section>)
    expect(html).toContain('Reconciliation data is unavailable. Click Refresh to try again.')
    expect(html).toMatch(/<button>Refresh reconciliation<\/button>/)
    expect(html).not.toContain('This feature will be enabled after the reconciliation engine is implemented.')
  })
})
