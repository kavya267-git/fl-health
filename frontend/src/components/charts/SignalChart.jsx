import { Area, CartesianGrid, ComposedChart, Legend, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { AXIS_TICK, GRID_STROKE, TOOLTIP_STYLE } from './theme'

/** An ECG beat with, underneath it, how much each part mattered to the prediction. */
export function SignalChart({ signal, importance, sampleRateHz }) {
  const data = signal.map((value, index) => ({
    ms: Math.round((index / sampleRateHz) * 1000),
    signal: value,
    importance: Math.max(0, importance[index]),
  }))
  return (
    <ResponsiveContainer width="100%" height={300}>
      <ComposedChart data={data} margin={{ top: 8, right: 16, bottom: 18, left: 4 }}>
        <CartesianGrid stroke={GRID_STROKE} vertical={false} />
        <XAxis
          dataKey="ms"
          type="number"
          domain={[0, 'dataMax']}
          tick={AXIS_TICK}
          tickLine={false}
          axisLine={{ stroke: GRID_STROKE }}
          label={{ value: 'Time (ms)', position: 'insideBottom', offset: -10, fill: '#586964', fontSize: 12 }}
        />
        <YAxis yAxisId="signal" tick={AXIS_TICK} tickLine={false} axisLine={false} width={44} tickFormatter={(v) => v.toFixed(1)} />
        <YAxis yAxisId="importance" orientation="right" hide domain={[0, (max) => Math.max(max * 3, 0.01)]} />
        <Tooltip
          {...TOOLTIP_STYLE}
          labelFormatter={(ms) => `${ms} ms`}
          formatter={(value, name) => [name === 'ECG signal' ? value.toFixed(3) : `${value.toFixed(2)} log-odds`, name]}
        />
        <Legend verticalAlign="top" height={30} wrapperStyle={{ fontSize: 13 }} />
        <Area
          yAxisId="importance"
          dataKey="importance"
          name="Importance (drop in confidence when hidden)"
          stroke="none"
          fill="#b03a60"
          fillOpacity={0.35}
          isAnimationActive={false}
        />
        <Line
          yAxisId="signal"
          dataKey="signal"
          name="ECG signal"
          stroke="#13211e"
          strokeWidth={1.75}
          dot={false}
          isAnimationActive={false}
        />
      </ComposedChart>
    </ResponsiveContainer>
  )
}
