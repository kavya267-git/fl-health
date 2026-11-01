/** Formatting helpers. Missing values render as an em dash, never as 0. */

export const DASH = '—'

export function formatPercent(value, digits = 1) {
  if (value === null || value === undefined || Number.isNaN(value)) return DASH
  return `${(value * 100).toFixed(digits)}%`
}

export function formatNumber(value, digits = 0) {
  if (value === null || value === undefined || Number.isNaN(value)) return DASH
  return Number(value).toLocaleString('en-GB', { minimumFractionDigits: digits, maximumFractionDigits: digits })
}

export function formatMetric(name, value) {
  if (value === null || value === undefined) return DASH
  return name === 'loss' ? Number(value).toFixed(3) : formatPercent(value)
}

export function formatDateTime(value) {
  if (!value) return DASH
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return DASH
  return date.toLocaleString('en-GB', { day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' })
}

export function formatTime(value) {
  if (!value) return DASH
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return DASH
  return date.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

export function formatDate(value) {
  if (!value) return DASH
  const date = new Date(value.length === 10 ? `${value}T00:00:00` : value)
  if (Number.isNaN(date.getTime())) return DASH
  return date.toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' })
}

export function timeAgo(value, now = Date.now()) {
  if (!value) return 'No activity yet'
  const seconds = Math.max(0, Math.round((now - new Date(value).getTime()) / 1000))
  if (seconds < 45) return 'Just now'
  if (seconds < 3600) return `${Math.round(seconds / 60)} min ago`
  if (seconds < 86400) return `${Math.round(seconds / 3600)} h ago`
  return `${Math.round(seconds / 86400)} d ago`
}

/** Like timeAgo, but to the second: for heartbeats that arrive every few seconds. */
export function secondsAgo(value, now = Date.now()) {
  if (!value) return 'Never'
  const seconds = Math.max(0, Math.round((now - new Date(value).getTime()) / 1000))
  return seconds < 120 ? `${seconds} s ago` : timeAgo(value, now)
}

export function durationBetween(start, end) {
  if (!start || !end) return DASH
  const seconds = Math.max(0, (new Date(end).getTime() - new Date(start).getTime()) / 1000)
  if (seconds < 60) return `${seconds.toFixed(1)} s`
  return `${Math.floor(seconds / 60)} min ${Math.round(seconds % 60)} s`
}

export const shortHash = (hash) => (hash && hash.length > 16 ? `${hash.slice(0, 10)}…${hash.slice(-6)}` : hash || DASH)

export const classNames = (...parts) => parts.filter(Boolean).join(' ')
