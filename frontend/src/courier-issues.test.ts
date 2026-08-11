import { describe, expect, it } from 'vitest'
import type { CourierIssue } from './services/courierIssues'
import { ageTone, localToday, sortCourierIssues } from './utils/courierIssues'
import pageSource from './components/CourierIssuesPage.tsx?raw'
import appSource from './App.tsx?raw'

const issue = (id: number, age: number, awb = `AWB-${id}`) => ({ id, age, awb, courier: 'Delhivery' } as CourierIssue)

describe('courier issues register', () => {
  it('sorts oldest open issues first and supports alternate sorting', () => {
    expect(sortCourierIssues([issue(1, 3), issue(2, 18), issue(3, 9)], 'age_desc').map(value => value.id)).toEqual([2, 3, 1])
    expect(sortCourierIssues([issue(1, 3, 'Z'), issue(2, 18, 'A')], 'awb').map(value => value.awb)).toEqual(['A', 'Z'])
  })
  it('applies restrained seven and fifteen day age thresholds', () => {
    expect(ageTone(7)).toBe('neutral'); expect(ageTone(8)).toBe('warning'); expect(ageTone(16)).toBe('critical')
  })
  it('uses an IST calendar date for the required default date picker', () => {
    expect(localToday()).toMatch(/^\d{4}-\d{2}-\d{2}$/)
    expect(pageSource).toContain('type="date"')
    expect(pageSource).toContain("date_raised: localToday()")
  })
  it('exposes Open/Closed, filters, editing, closure and filtered Excel export', () => {
    for (const value of ['Open', 'Closed', 'Search AWB', 'All couriers', 'All issue types', 'All team members', 'Export Excel', '+ Add Issue', 'Edit', 'Reopen']) expect(pageSource).toContain(value)
    expect(pageSource).toContain('exportCourierIssues(currentFilters)')
    expect(pageSource).toContain("closure_date: next === 'closed' ? localToday() : null")
  })
  it('links only reliably mapped AWBs and does not trigger providers', () => {
    expect(pageSource).toContain('issue.order_id && issue.order_number')
    expect(pageSource).not.toMatch(/checkShiprocket|checkDelhivery|refreshShipment|Shadowfax/)
    expect(appSource).toContain("setSearch(orderNumber)")
    expect(appSource).toContain("loads.reconciliation && reconciliationSection === 'reconciliation'")
  })
})
