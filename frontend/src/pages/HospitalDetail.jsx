import { ArrowLeft } from 'lucide-react'
import { useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { MetricLineChart } from '../components/charts/MetricLineChart'
import { Badge, ModalityTag, ParticipantStatusBadge, RoundStatusBadge, SimulatedTag } from '../components/ui/Badge'
import { Card, CardBody, CardHeader } from '../components/ui/Card'
import { PageHeader, Tabs, Td, Th } from '../components/ui/Misc'
import { AsyncView, EmptyState } from '../components/ui/StateViews'
import { useApi } from '../hooks/useApi'
import { api } from '../services/endpoints'
import { MODALITIES, MODALITY_ORDER, availabilityLabel } from '../utils/constants'
import { formatDateTime, formatNumber, timeAgo } from '../utils/format'

export function DataSummary({ hospital }) {
  const rows = MODALITY_ORDER.filter((m) => hospital.data_summary[m])
  if (rows.length === 0) {
    return <EmptyState title="No local data reported" description="The node reports its record counts when it joins a round." />
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse">
        <thead>
          <tr>
            <Th>Modality</Th>
            <Th>Source</Th>
            <Th align="right">Training records</Th>
            <Th align="right">Held-out records</Th>
          </tr>
        </thead>
        <tbody>
          {rows.map((modality) => {
            const summary = hospital.data_summary[modality]
            return (
              <tr key={modality}>
                <Td>
                  <span className="flex items-center gap-2">
                    <ModalityTag modality={modality} />
                    {MODALITIES[modality].name}
                  </span>
                </Td>
                <Td>
                  <span className="flex items-center gap-2">
                    {summary.source}
                    {summary.simulated ? <SimulatedTag compact /> : null}
                  </span>
                </Td>
                <Td align="right">{formatNumber(summary.train_samples)}</Td>
                <Td align="right">{formatNumber(summary.val_samples)}</Td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

export function LocalMetrics({ metrics }) {
  const available = MODALITY_ORDER.filter((m) => metrics.local_validation.some((row) => row.modality === m))
  const [modality, setModality] = useState(available[0] || 'ehr')
  const active = available.includes(modality) ? modality : available[0]

  const data = useMemo(() => {
    const byRound = new Map()
    const put = (row, key) => {
      if (row.modality !== active) return
      const entry = byRound.get(row.round_number) || { round: row.round_number }
      entry[key] = row.metrics.f1
      byRound.set(row.round_number, entry)
    }
    metrics.local_validation.forEach((row) => put(row, 'local'))
    metrics.global_model_on_local_data.forEach((row) => put(row, 'global'))
    return [...byRound.values()].sort((a, b) => a.round - b.round)
  }, [metrics, active])

  if (available.length === 0) {
    return (
      <EmptyState title="No training results yet" description="Results appear after this hospital has taken part in a completed round." />
    )
  }
  return (
    <>
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <Tabs
          label="Modality"
          value={active}
          onChange={setModality}
          options={available.map((m) => ({ value: m, label: MODALITIES[m].label }))}
        />
        <p className="text-xs text-muted">F1 on this hospital&rsquo;s own held-out records, by round.</p>
      </div>
      <MetricLineChart
        data={data}
        xKey="round"
        xLabel="Round"
        percent
        series={[
          { key: 'local', label: 'Locally trained model (before averaging)', color: '#b0661a', dashed: true },
          { key: 'global', label: 'Global model (after FedAvg)', color: MODALITIES[active].color },
        ]}
      />
    </>
  )
}

export default function HospitalDetail() {
  const { hospitalId } = useParams()
  const state = useApi(async () => {
    const [hospital, metrics] = await Promise.all([api.hospital(hospitalId), api.hospitalMetrics(hospitalId)])
    return { hospital, metrics }
  }, [hospitalId])

  return (
    <>
      <Link to="/hospitals" className="mb-4 inline-flex items-center gap-1.5 text-sm font-medium text-brand-700 hover:underline">
        <ArrowLeft className="h-4 w-4" aria-hidden="true" />
        All hospitals
      </Link>
      <AsyncView state={state} what="this hospital">
        {({ hospital, metrics }) => (
          <>
            <PageHeader
              title={hospital.name}
              description={`${hospital.kind || 'Hospital'}. Node id ${hospital.id}. Last activity: ${timeAgo(hospital.last_activity_at).toLowerCase()}.`}
              actions={
                <>
                  <Badge tone={hospital.online ? 'ok' : 'nodata'}>{availabilityLabel(hospital)}</Badge>
                  {hospital.is_simulated ? <SimulatedTag compact /> : null}
                </>
              }
            />
            <div className="space-y-6">
              <Card>
                <CardHeader
                  title="Local data"
                  description="Record counts reported by the hospital node. The records themselves stay on the node."
                />
                <DataSummary hospital={hospital} />
              </Card>

              <Card>
                <CardHeader title="Model quality on this hospital's data" />
                <CardBody>
                  <LocalMetrics metrics={metrics} />
                </CardBody>
              </Card>

              <Card>
                <CardHeader title="Round participation" />
                {metrics.participation.length === 0 ? (
                  <EmptyState title="This hospital has not taken part in a round yet" />
                ) : (
                  <div className="overflow-x-auto">
                    <table className="w-full border-collapse">
                      <thead>
                        <tr>
                          <Th>Round</Th>
                          <Th>Modality</Th>
                          <Th>Hospital status</Th>
                          <Th>Round status</Th>
                          <Th align="right">Training records</Th>
                          <Th>Update received</Th>
                        </tr>
                      </thead>
                      <tbody>
                        {metrics.participation.map((row) => (
                          <tr key={row.round_id}>
                            <Td className="font-mono text-[13px]">{row.round_id}</Td>
                            <Td>
                              <ModalityTag modality={row.modality} />
                            </Td>
                            <Td>
                              <ParticipantStatusBadge status={row.status} />
                              {row.error ? <p className="mt-1 max-w-xs text-xs text-alert">{row.error}</p> : null}
                            </Td>
                            <Td>
                              <RoundStatusBadge status={row.round_status} />
                            </Td>
                            <Td align="right">{formatNumber(row.num_samples)}</Td>
                            <Td>{formatDateTime(row.update_received_at)}</Td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </Card>
            </div>
          </>
        )}
      </AsyncView>
    </>
  )
}
