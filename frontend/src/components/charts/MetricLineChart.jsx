import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { AXIS_TICK, GRID_STROKE, TOOLTIP_STYLE } from './theme'

/**
 * Lines over an ordered x-axis (model versions or rounds).
 *
 * `series` is [{ key, label, color, dashed? }]. Values are plotted as given;
 * `percent` formats a 0-1 scale as percentages.
 */
export function MetricLineChart({ data, xKey, xLabel, series, percent = false, height = 260, yDomain }) {
  const format = (value) =>
    value === null || value === undefined ? '—' : percent ? `${(value * 100).toFixed(1)}%` : Number(value).toFixed(3)
  return (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart data={data} margin={{ top: 8, right: 16, bottom: 18, left: 4 }}>
        <CartesianGrid stroke={GRID_STROKE} vertical={false} />
        <XAxis
          dataKey={xKey}
          tick={AXIS_TICK}
          tickLine={false}
          axisLine={{ stroke: GRID_STROKE }}
          label={xLabel ? { value: xLabel, position: 'insideBottom', offset: -10, fill: '#4e5b75', fontSize: 12 } : undefined}
        />
        <YAxis
          tick={AXIS_TICK}
          tickLine={false}
          axisLine={false}
          width={52}
          domain={yDomain || (percent ? [0, 1] : ['auto', 'auto'])}
          tickFormatter={(value) => (percent ? `${Math.round(value * 100)}%` : Number(value).toFixed(2))}
        />
        <Tooltip {...TOOLTIP_STYLE} formatter={(value, name) => [format(value), name]} />
        <Legend verticalAlign="top" height={30} iconType="plainline" wrapperStyle={{ fontSize: 13 }} />
        {series.map((item) => (
          <Line
            key={item.key}
            type="monotone"
            dataKey={item.key}
            name={item.label}
            stroke={item.color}
            strokeWidth={2}
            strokeDasharray={item.dashed ? '5 4' : undefined}
            dot={{ r: 3, strokeWidth: 0, fill: item.color }}
            activeDot={{ r: 5 }}
            connectNulls
            isAnimationActive={false}
          />
        ))}
      </LineChart>
    </ResponsiveContainer>
  )
}
