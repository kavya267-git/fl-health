import { useMemo, useState } from 'react'
import { MapLegend } from '../components/surveillance/MapLegend'
import { RegionMap } from '../components/surveillance/RegionMap'
import { RegionPanel } from '../components/surveillance/RegionPanel'
import { buildScale } from '../components/surveillance/scale'
import { HotspotStatusBadge, SimulatedTag } from '../components/ui/Badge'
import { Card, CardBody, CardHeader } from '../components/ui/Card'
import { Field, Note, PageHeader, Select, Td, Th } from '../components/ui/Misc'
import { AsyncView, EmptyState } from '../components/ui/StateViews'
import { useApi } from '../hooks/useApi'
import { api } from '../services/endpoints'
import { HOTSPOT_ORDER } from '../utils/constants'
import { DASH, formatNumber } from '../utils/format'

function SurveillanceResult({ data, selectedId, onSelect }) {
  const hasRates = data.regions.some((r) => r.case_rate !== null)
  const valueKey = hasRates ? 'case_rate' : 'case_count'
  const scale = useMemo(() => buildScale(data.regions.map((r) => r[valueKey])), [data, valueKey])
  const selected = data.regions.find((r) => r.region_id === selectedId) || null
  const ordered = useMemo(
    () =>
      [...data.regions].sort(
        (a, b) =>
          HOTSPOT_ORDER.indexOf(a.status) - HOTSPOT_ORDER.indexOf(b.status) ||
          (b.anomaly_score ?? -Infinity) - (a.anomaly_score ?? -Infinity),
      ),
    [data],
  )
  const dataKey = `${data.disease.id}:${data.time_period.week_start}`

  return (
    <div className="space-y-6">
      <Note tone="info" title="How to read a potential hotspot">
        {data.disclaimer}
      </Note>

      <div className="grid gap-6 xl:grid-cols-[1.7fr_1fr]">
        <Card>
          <CardHeader
            title={`${data.disease.label}, week ${data.time_period.label}`}
            description={`${data.time_period.week_start} to ${data.time_period.week_end}`}
            action={data.data_status.simulated ? <SimulatedTag compact /> : null}
          />
          <CardBody className="space-y-4">
            <RegionMap
              geojson={data.geojson}
              dataKey={dataKey}
              scale={scale}
              valueKey={valueKey}
              selectedId={selectedId}
              onSelect={onSelect}
              showTiles={!data.data_status.geometry_simulated}
              // Real boundaries with simulated counts could be mistaken for real cases, so the map says so.
              watermark={data.data_status.geometry_simulated ? null : data.data_status.watermark}
            />
            <MapLegend
              scale={scale}
              valueLabel={hasRates ? 'cases per 100,000 residents' : 'reported cases'}
              digits={hasRates ? 1 : 0}
              summary={data.summary}
            />
            {data.data_status.geometry_simulated ? (
              <p className="text-xs text-muted">
                The regions are fictional and drawn without a base map. They do not correspond to any real place.
              </p>
            ) : (
              <>
                {data.data_status.geometry_notes ? <p className="text-xs text-muted">{data.data_status.geometry_notes}</p> : null}
                {data.data_status.geometry_attribution ? (
                  <p className="text-xs text-muted">{data.data_status.geometry_attribution}</p>
                ) : null}
              </>
            )}
          </CardBody>
        </Card>

        <Card>
          <CardHeader title="Selected region" />
          <RegionPanel region={selected} disease={data.disease} period={data.time_period} dataStatus={data.data_status} />
        </Card>
      </div>

      <Card>
        <CardHeader
          title="All regions"
          description={`Method: ${data.method.method}. Baseline of ${data.method.baseline_weeks} weeks ending ${data.method.guard_weeks} week before; potential hotspot at z ≥ ${data.method.candidate_threshold_z}, elevated at z ≥ ${data.method.elevated_threshold_z}.`}
        />
        <div className="overflow-x-auto">
          <table className="w-full border-collapse">
            <thead>
              <tr>
                <Th>Region</Th>
                <Th>Status</Th>
                <Th align="right">Cases</Th>
                <Th align="right">Rate per 100,000</Th>
                <Th align="right">Anomaly score</Th>
                <Th align="right">Baseline mean</Th>
              </tr>
            </thead>
            <tbody>
              {ordered.map((region) => (
                <tr key={region.region_id} className={region.region_id === selectedId ? 'bg-brand-50' : 'hover:bg-canvas'}>
                  <Td>
                    <button
                      type="button"
                      onClick={() => onSelect(region.region_id)}
                      aria-pressed={region.region_id === selectedId}
                      className="text-left font-medium text-brand-700 hover:underline"
                    >
                      {region.region_name}
                    </button>
                  </Td>
                  <Td>
                    <HotspotStatusBadge status={region.status} />
                  </Td>
                  <Td align="right">{region.case_count === null ? DASH : formatNumber(region.case_count)}</Td>
                  <Td align="right">{region.case_rate === null ? DASH : formatNumber(region.case_rate, 1)}</Td>
                  <Td align="right">{region.anomaly_score === null ? DASH : region.anomaly_score.toFixed(2)}</Td>
                  <Td align="right">{region.baseline_mean === null ? DASH : formatNumber(region.baseline_mean, 1)}</Td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  )
}

export default function Surveillance() {
  const options = useApi(() => api.analyticsOptions(), [], {
    isEmpty: (data) => !data.diseases?.length || !data.periods?.length,
  })
  const [disease, setDisease] = useState(null)
  const [period, setPeriod] = useState(null)
  const [selectedId, setSelectedId] = useState(null)

  const activeDisease = disease ?? options.data?.diseases[0]?.id
  const activePeriod = period ?? options.data?.latest_period?.week_start
  const result = useApi(() => api.hotspots(activeDisease, activePeriod), [activeDisease, activePeriod], {
    enabled: options.status === 'success',
  })

  return (
    <>
      <PageHeader
        title="Disease Surveillance"
        description="Weekly case counts per region, built from totals the hospitals report. No patient-level locations are used. Regions whose count is unusually high for them are marked for a closer look."
      />
      <AsyncView
        state={options}
        what="surveillance data"
        empty={
          <EmptyState
            title="No surveillance data yet"
            description="Weekly counts appear here once hospitals report their aggregated totals."
            illustration
          />
        }
      >
        {(data) => (
          <>
            <Card className="mb-6">
              <CardBody className="grid gap-4 sm:grid-cols-2 lg:max-w-2xl">
                <Field label="Disease" htmlFor="surveillance-disease">
                  <Select
                    id="surveillance-disease"
                    value={activeDisease}
                    onChange={setDisease}
                    options={data.diseases.map((d) => ({ value: d.id, label: d.label }))}
                  />
                </Field>
                <Field label="Time period (week)" htmlFor="surveillance-period">
                  <Select
                    id="surveillance-period"
                    value={activePeriod}
                    onChange={setPeriod}
                    options={data.periods.map((p) => ({ value: p.week_start, label: `${p.label} (from ${p.week_start})` }))}
                  />
                </Field>
              </CardBody>
            </Card>
            <AsyncView state={result} what="surveillance data">
              {(hotspots) => <SurveillanceResult data={hotspots} selectedId={selectedId} onSelect={setSelectedId} />}
            </AsyncView>
          </>
        )}
      </AsyncView>
    </>
  )
}
