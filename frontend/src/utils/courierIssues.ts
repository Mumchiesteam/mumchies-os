import type { CourierIssue } from '../services/courierIssues'

export type CourierIssueSort = 'age_desc' | 'age_asc' | 'awb' | 'courier'
export const sortCourierIssues = (items: CourierIssue[], sort: CourierIssueSort) => [...items].sort((a, b) => {
  if (sort === 'age_asc') return a.age - b.age || a.id - b.id
  if (sort === 'awb') return a.awb.localeCompare(b.awb)
  if (sort === 'courier') return a.courier.localeCompare(b.courier) || b.age - a.age
  return b.age - a.age || a.id - b.id
})
export const ageTone = (age: number) => age > 15 ? 'critical' : age > 7 ? 'warning' : 'neutral'
export const localToday = () => {
  const parts = new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Kolkata', year: 'numeric', month: '2-digit', day: '2-digit' }).formatToParts(new Date())
  const value = Object.fromEntries(parts.map(part => [part.type, part.value]))
  return `${value.year}-${value.month}-${value.day}`
}
