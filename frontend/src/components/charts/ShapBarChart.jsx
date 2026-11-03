import { Bar, BarChart, CartesianGrid, Cell, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { AXIS_TICK, GRID_STROKE, TOOLTIP_STYLE } from './theme'

export const RAISES = '#b3261e'
export const LOWERS = '#2a6f97'

/**
 * Horizontal bars, one per feature.
 *
 * `signed` = true: each bar is a SHAP value for one prediction (right raises
 * the predicted risk, left lowers it). `signed` = false: mean absolute SHAP
 * value across many records (overall importance), coloured by direction.
 */
export function ShapBarChart({ rows, signed, valueLabel }) {
  const height = Math.max(220, rows.length * 30 + 50)
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={rows} layout="vertical" margin={{ top: 4, right: 24, bottom: 20, left: 8 }}>
        <CartesianGrid stroke={GRID_STROKE} horizontal={false} />
        <XAxis
          type="number"
          tick={AXIS_TICK}
          tickLine={false}
          axisLine={{ stroke: GRID_STROKE }}
          tickFormatter={(value) => (signed ? `${value > 0 ? '+' : ''}${(value * 100).toFixed(0)}` : (value * 100).toFixed(1))}
          label={{ value: valueLabel, position: 'insideBottom', offset: -12, fill: '#4e5b75', fontSize: 12 }}
        />
        <YAxis
          type="category"
          dataKey="name"
          width={260}
          tick={{ ...AXIS_TICK, fill: '#111a2e' }}
          tickLine={false}
          axisLine={false}
          interval={0}
        />
        <Tooltip
          {...TOOLTIP_STYLE}
          cursor={{ fill: 'rgba(15, 93, 86, 0.06)' }}
          formatter={(value) => [
            `${value > 0 && signed ? '+' : ''}${(value * 100).toFixed(2)} percentage points`,
            signed ? 'Contribution' : 'Mean |SHAP|',
          ]}
        />
        {signed ? <ReferenceLine x={0} stroke="#4e5b75" /> : null}
        <Bar dataKey="value" isAnimationActive={false} barSize={16} radius={2}>
          {rows.map((row) => (
            <Cell key={row.name} fill={row.color} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  )
}
