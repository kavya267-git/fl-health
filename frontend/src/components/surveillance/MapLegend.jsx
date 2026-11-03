import { HOTSPOT_ORDER, HOTSPOT_STATUS } from '../../utils/constants'
import { formatNumber } from '../../utils/format'
import { NO_VALUE_COLOR } from './scale'

export function MapLegend({ scale, valueLabel, digits, summary }) {
  return (
    <div className="grid gap-5 sm:grid-cols-2">
      <div>
        <p className="text-xs font-semibold text-ink">Fill: {valueLabel}</p>
        {scale.min === null ? (
          <p className="mt-1.5 text-xs text-muted">No region has a complete count for this week.</p>
        ) : (
          <>
            <div className="mt-1.5 flex h-3 overflow-hidden rounded-sm">
              {scale.breaks.map((item) => (
                <span key={item.fill} className="flex-1" style={{ background: item.fill }} />
              ))}
            </div>
            <div className="mt-1 flex justify-between text-xs text-muted">
              <span>{formatNumber(scale.min, digits)}</span>
              <span>{formatNumber(scale.max, digits)}</span>
            </div>
          </>
        )}
        <p className="mt-2 flex items-center gap-2 text-xs text-muted">
          <span className="h-3 w-5 rounded-sm border border-line-strong" style={{ background: NO_VALUE_COLOR }} />
          No complete count (suppressed or missing)
        </p>
      </div>
      <div>
        <p className="text-xs font-semibold text-ink">Outline: status this week</p>
        <ul className="mt-1.5 space-y-1">
          {HOTSPOT_ORDER.map((status) => {
            const meta = HOTSPOT_STATUS[status]
            const flagged = status === 'CANDIDATE_HOTSPOT' || status === 'ELEVATED'
            return (
              <li key={status} className="flex items-center gap-2 text-xs text-muted">
                <span
                  className="h-3 w-5 rounded-sm bg-surface"
                  style={{
                    border: flagged
                      ? `${status === 'CANDIDATE_HOTSPOT' ? 3 : 2}px ${status === 'ELEVATED' ? 'dashed' : 'solid'} ${meta.color}`
                      : '1px solid #bccae0',
                  }}
                />
                <span className="text-ink">{meta.label}</span>
                <span>{summary?.[status] ?? 0} regions</span>
              </li>
            )
          })}
        </ul>
      </div>
    </div>
  )
}
