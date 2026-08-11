import { apiBase, apiFetch } from './orders'

export type CourierIssueStatus = 'open' | 'closed'
export type CourierIssue = {
  id: number; awb: string; date_raised: string; raised_by: string; courier: string; issue_type: string;
  notes: string | null; status: CourierIssueStatus; closure_date: string | null; age: number;
  order_id: string | null; order_number: string | null; created_at: string; updated_at: string
}
export type CourierIssuePayload = Pick<CourierIssue, 'awb' | 'date_raised' | 'raised_by' | 'courier' | 'issue_type' | 'notes' | 'status' | 'closure_date'>
export type CourierIssueFilters = { status: CourierIssueStatus; search: string; courier: string; issue_type: string; raised_by: string }
export type CourierIssueOptions = { raised_by: string[]; couriers: string[]; issue_types: string[] }
export type CourierIssueKpis = { open: number; open_over_7: number; open_over_15: number; closed_this_month: number }

const query = (filters: CourierIssueFilters) => new URLSearchParams({ status_value: filters.status, search: filters.search, courier: filters.courier, issue_type: filters.issue_type, raised_by: filters.raised_by }).toString()
const error = async (response: Response) => new Error((await response.json().catch(() => null))?.detail || 'Courier issue request failed.')

export async function getCourierIssueOptions(): Promise<CourierIssueOptions> {
  const response = await apiFetch(`${apiBase}/api/v1/courier-issues/options`)
  if (!response.ok) throw await error(response)
  return response.json()
}
export async function getCourierIssues(filters: CourierIssueFilters): Promise<{ items: CourierIssue[]; kpis: CourierIssueKpis }> {
  const response = await apiFetch(`${apiBase}/api/v1/courier-issues?${query(filters)}`)
  if (!response.ok) throw await error(response)
  return response.json()
}
export async function saveCourierIssue(payload: CourierIssuePayload, id?: number): Promise<CourierIssue> {
  const response = await apiFetch(`${apiBase}/api/v1/courier-issues${id ? `/${id}` : ''}`, { method: id ? 'PUT' : 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) })
  if (!response.ok) throw await error(response)
  return response.json()
}
export async function exportCourierIssues(filters: CourierIssueFilters): Promise<void> {
  const response = await apiFetch(`${apiBase}/api/v1/courier-issues/export.xlsx?${query(filters)}`)
  if (!response.ok) throw await error(response)
  const blob = await response.blob(); const url = URL.createObjectURL(blob); const anchor = document.createElement('a')
  anchor.href = url; anchor.download = response.headers.get('Content-Disposition')?.match(/filename="([^"]+)"/)?.[1] || 'courier-issues.xlsx'; anchor.click(); URL.revokeObjectURL(url)
}
