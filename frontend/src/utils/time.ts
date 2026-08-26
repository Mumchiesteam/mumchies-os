export const parseOperationalDate = (value: string) => {
  const trimmed = value.trim()
  const hasZone = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(trimmed)
  return new Date(hasZone ? trimmed : `${trimmed}Z`)
}

export const formatDateTime = (value: string) => `${new Intl.DateTimeFormat('en-IN', {
  day: '2-digit',
  month: 'short',
  year: 'numeric',
  hour: '2-digit',
  minute: '2-digit',
  hour12: true,
  timeZone: 'Asia/Kolkata',
}).format(parseOperationalDate(value)).replace(/\b(am|pm)\b/i, marker => marker.toUpperCase())} IST`
