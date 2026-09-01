const istDate = (value: Date) => new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Kolkata' }).format(value)

export const isPreviousPendingToday = (enteredAt: string | null | undefined, now = new Date()) => {
  if (!enteredAt) return false
  const entered = new Date(enteredAt)
  return !Number.isNaN(entered.getTime()) && istDate(entered) === istDate(now)
}
