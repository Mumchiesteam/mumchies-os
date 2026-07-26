export const formatDateTime = (value: string) => `${new Intl.DateTimeFormat('en-IN', {
  day: '2-digit',
  month: 'short',
  year: 'numeric',
  hour: '2-digit',
  minute: '2-digit',
  hour12: true,
  timeZone: 'Asia/Kolkata',
}).format(new Date(value)).replace(/\b(am|pm)\b/i, marker => marker.toUpperCase())} IST`
