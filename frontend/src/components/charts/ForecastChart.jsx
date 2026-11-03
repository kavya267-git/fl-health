import { Area, CartesianGrid, ComposedChart, Legend, Line, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { AXIS_TICK, GRID_STROKE, TOOLTIP_STYLE } from './theme'

const OBSERVED = '#24489a'
const FORECAST = '#6a4c9c'

/**
 * Observed weekly cases followed by the forecast.
 *
 * - solid blue: observed counts (gaps where a week was suppressed or missing)
 * - dashed grey: the selected model's one-week-ahead prediction for each held-out week
 * - violet: the forecast, with 80% and 95% uncertainty bands
 */
export function ForecastChart({ history, forecast, visibleWeeks = 52 }) {
  const recent = history.slice(-visibleWeeks)
  const lastObserved = [...recent].reverse().find((point) => point.case_count !== null)
  const data = [
    ...recent.map((point) => ({
      label: point.label,
      observed: point.case_count,
      holdout: point.holdout_prediction,
      // Join the forecast line to the last observed point.
      predicted: point === lastObserved ? point.case_count : null,
    })),
    ...forecast.map((point) => ({
      label: point.label,
      predicted: point.predicted,
      band95: [point.lower_95, point.upper_95],
      band80: [point.lower_80, point.upper_80],
    })),
  ]
  const boundary = recent.length ? recent[recent.length - 1].label : undefined
  const number = (value) => (value === null || value === undefined ? '—' : Math.round(value).toLocaleString('en-GB'))

  return (
    <ResponsiveContainer width="100%" height={340}>
      <ComposedChart data={data} margin={{ top: 8, right: 16, bottom: 4, left: 4 }}>
        <CartesianGrid stroke={GRID_STROKE} vertical={false} />
        <XAxis dataKey="label" tick={AXIS_TICK} tickLine={false} axisLine={{ stroke: GRID_STROKE }} minTickGap={36} />
        <YAxis tick={AXIS_TICK} tickLine={false} axisLine={false} width={48} allowDecimals={false} />
        <Tooltip
          {...TOOLTIP_STYLE}
          formatter={(value, name) => [Array.isArray(value) ? `${number(value[0])} to ${number(value[1])}` : number(value), name]}
        />
        <Legend verticalAlign="top" height={32} wrapperStyle={{ fontSize: 13 }} />
        <Area
          dataKey="band95"
          name="95% interval"
          stroke="none"
          fill={FORECAST}
          fillOpacity={0.14}
          isAnimationActive={false}
          connectNulls={false}
        />
        <Area
          dataKey="band80"
          name="80% interval"
          stroke="none"
          fill={FORECAST}
          fillOpacity={0.24}
          isAnimationActive={false}
          connectNulls={false}
        />
        {boundary ? (
          <ReferenceLine
            x={boundary}
            stroke="#636f88"
            strokeDasharray="3 3"
            label={{ value: 'Forecast starts', position: 'insideTopRight', fill: '#4e5b75', fontSize: 12 }}
          />
        ) : null}
        <Line dataKey="observed" name="Observed cases" stroke={OBSERVED} strokeWidth={2} dot={false} isAnimationActive={false} />
        <Line
          dataKey="holdout"
          name="One-week-ahead prediction on held-out weeks"
          stroke="#636f88"
          strokeWidth={1.5}
          strokeDasharray="4 3"
          dot={false}
          isAnimationActive={false}
        />
        <Line
          dataKey="predicted"
          name="Forecast (prediction)"
          stroke={FORECAST}
          strokeWidth={2.5}
          dot={{ r: 3, fill: FORECAST, strokeWidth: 0 }}
          isAnimationActive={false}
        />
      </ComposedChart>
    </ResponsiveContainer>
  )
}
