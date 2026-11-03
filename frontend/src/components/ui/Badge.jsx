import { classNames } from '../../utils/format'
import { HOTSPOT_STATUS, MODALITIES, PARTICIPANT_LABELS, ROUND_STATUS_LABELS } from '../../utils/constants'

const TONES = {
  neutral: 'bg-canvas text-muted border-line',
  brand: 'bg-brand-50 text-brand-700 border-brand-100',
  ok: 'bg-ok-soft text-ok border-ok/20',
  warn: 'bg-warn-soft text-warn-ink border-warn/25',
  alert: 'bg-alert-soft text-alert border-alert/20',
  nodata: 'bg-nodata-soft text-muted border-line',
  forecast: 'bg-forecast-soft text-forecast border-forecast/20',
}

export function Badge({ tone = 'neutral', children, className = '', title }) {
  return (
    <span
      title={title}
      className={classNames(
        'inline-flex items-center gap-1.5 whitespace-nowrap rounded-full border px-2.5 py-0.5 text-xs font-medium',
        TONES[tone] || TONES.neutral,
        className,
      )}
    >
      {children}
    </span>
  )
}

const ROUND_TONES = { COMPLETED: 'ok', FAILED: 'alert' }

export function RoundStatusBadge({ status }) {
  const active = !['COMPLETED', 'FAILED'].includes(status)
  return (
    <Badge tone={ROUND_TONES[status] || 'brand'}>
      {active ? <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-brand-600" aria-hidden="true" /> : null}
      {ROUND_STATUS_LABELS[status] || status}
    </Badge>
  )
}

const PARTICIPANT_TONES = {
  EVALUATED: 'ok',
  UPDATE_SUBMITTED: 'brand',
  TRAINING: 'brand',
  JOINED: 'brand',
  UPDATE_REJECTED: 'alert',
  EVALUATION_FAILED: 'alert',
  FAILED: 'alert',
  DROPPED: 'warn',
}

export function ParticipantStatusBadge({ status }) {
  return <Badge tone={PARTICIPANT_TONES[status] || 'neutral'}>{PARTICIPANT_LABELS[status] || status}</Badge>
}

export function HotspotStatusBadge({ status }) {
  const meta = HOTSPOT_STATUS[status] || HOTSPOT_STATUS.INSUFFICIENT_DATA
  return <Badge tone={meta.tone}>{meta.label}</Badge>
}

export function ModalityTag({ modality, className = '' }) {
  const meta = MODALITIES[modality]
  if (!meta) return null
  return (
    <span className={classNames('inline-flex items-center rounded px-2 py-0.5 text-xs font-semibold', meta.soft, className)}>
      {meta.label}
    </span>
  )
}

/** Marks anything derived from simulated data. Text comes from the server so it stays consistent. */
export function SimulatedTag({ label = 'SIMULATED / DEMONSTRATION DATA', compact = false }) {
  return (
    <span
      className="inline-flex items-center rounded border border-warn/30 bg-warn-soft px-2 py-0.5 text-[11px] font-semibold tracking-wide text-warn-ink"
      title="These values come from simulated data and are for demonstration only."
    >
      {compact ? 'SIMULATED' : label}
    </span>
  )
}
