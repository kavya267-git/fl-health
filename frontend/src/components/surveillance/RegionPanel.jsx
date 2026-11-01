import { HotspotStatusBadge, SimulatedTag } from '../ui/Badge'
import { DASH, formatNumber } from '../../utils/format'

/** Small bar chart of the recent weekly counts; gaps are weeks without a complete count. */
function RecentWeeks({ labels, counts }) {
  const max = Math.max(1, ...counts.filter((c) => c !== null))
  const width = 100 / counts.length
  return (
    <figure>
      <svg
        viewBox="0 0 100 36"
        preserveAspectRatio="none"
        className="h-16 w-full"
        role="img"
        aria-label="Weekly cases over the most recent weeks"
      >
        {counts.map((count, index) =>
          count === null ? (
            <rect key={labels[index]} x={index * width + 0.6} y={33} width={width - 1.2} height={1} fill="#c3cfcb" />
          ) : (
            <rect
              key={labels[index]}
              x={index * width + 0.6}
              y={34 - (count / max) * 32}
              width={width - 1.2}
              height={(count / max) * 32}
              fill={index === counts.length - 1 ? '#0f5d56' : '#a9d8d0'}
            />
          ),
        )}
      </svg>
      <figcaption className="mt-1 flex justify-between text-[11px] text-muted">
        <span>{labels[0]}</span>
        <span>{labels[labels.length - 1]}</span>
      </figcaption>
    </figure>
  )
}

export function RegionPanel({ region, disease, period, dataStatus }) {
  if (!region) {
    return (
      <div className="flex h-full min-h-48 items-center justify-center px-5 py-8 text-center text-sm text-muted">
        Select a region on the map or in the table to see its figures.
      </div>
    )
  }
  const rows = [
    ['Region', `${region.region_name} (${region.region_id})`],
    ['Disease', disease.label],
    ['Cases', region.case_count === null ? 'Not available' : formatNumber(region.case_count)],
    ['Case rate', region.case_rate === null ? 'Not available' : `${formatNumber(region.case_rate, 1)} per 100,000`],
    ['Anomaly score', region.anomaly_score === null ? 'Not available' : `${region.anomaly_score.toFixed(2)} (z-score)`],
    ['Time period', `${period.label} (${period.week_start} to ${period.week_end})`],
  ]
  return (
    <div className="px-5 py-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-base font-semibold text-ink">{region.region_name}</h3>
        <HotspotStatusBadge status={region.status} />
      </div>
      <dl className="mt-3 divide-y divide-line">
        {rows.map(([term, value]) => (
          <div key={term} className="flex justify-between gap-4 py-2 text-sm">
            <dt className="text-muted">{term}</dt>
            <dd className="text-right font-medium text-ink">{value}</dd>
          </div>
        ))}
        <div className="flex justify-between gap-4 py-2 text-sm">
          <dt className="text-muted">Status</dt>
          <dd className="text-right font-medium text-ink">{region.status_label}</dd>
        </div>
        <div className="flex items-center justify-between gap-4 py-2 text-sm">
          <dt className="text-muted">Data status</dt>
          <dd className="text-right">
            {dataStatus.simulated ? <SimulatedTag compact /> : <span className="font-medium text-ink">{dataStatus.label}</span>}
          </dd>
        </div>
      </dl>

      <p className="mt-3 text-sm leading-relaxed text-ink">{region.reason}</p>
      <ul className="mt-2 space-y-1 text-xs leading-relaxed text-muted">
        <li>
          Recent baseline: {region.baseline_mean === null ? DASH : `${formatNumber(region.baseline_mean, 1)} cases per week`}
          {region.baseline_points ? ` from ${region.baseline_points} weeks` : ''}.
        </li>
        <li>
          {region.reporting_hospitals} hospital{region.reporting_hospitals === 1 ? '' : 's'} reported
          {region.suppressed_cells
            ? `; ${region.suppressed_cells} small count${region.suppressed_cells === 1 ? '' : 's'} suppressed, so the regional total is withheld`
            : ''}
          .
        </li>
        {region.adjacent_flagged_regions?.length ? (
          <li>Neighbouring regions also above baseline: {region.adjacent_flagged_regions.join(', ')}.</li>
        ) : null}
        {region.population ? (
          <li>Population denominator: {formatNumber(region.population)}.</li>
        ) : (
          <li>No population denominator, so no rate is shown.</li>
        )}
      </ul>

      <div className="mt-4">
        <p className="mb-1 text-xs text-muted">Weekly cases, last {region.recent_counts.length} weeks</p>
        <RecentWeeks labels={region.recent_weeks} counts={region.recent_counts} />
      </div>
    </div>
  )
}
