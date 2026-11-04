import { ChevronRight } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Badge, ModalityTag, SimulatedTag } from '../components/ui/Badge'
import { Button } from '../components/ui/Button'
import { Card } from '../components/ui/Card'
import { Note, PageHeader } from '../components/ui/Misc'
import { AsyncView, EmptyState } from '../components/ui/StateViews'
import { useAuth } from '../context/AuthContext'
import { useApi } from '../hooks/useApi'
import { usePolling } from '../hooks/usePolling'
import { toApiError } from '../services/api'
import { api } from '../services/endpoints'
import {
  MODALITY_ORDER,
  PARTICIPANT_LABELS,
  availabilityLabel,
  canManageRounds,
  canOpenHospitalDetails,
  isHospitalOperator,
} from '../utils/constants'
import { DASH, formatDateTime, formatNumber, secondsAgo, timeAgo } from '../utils/format'

const PARTICIPATION = {
  PARTICIPATING: { label: 'In a round now', tone: 'brand' },
  IDLE: { label: 'Ready', tone: 'ok' },
  UNAVAILABLE: { label: 'Not available', tone: 'nodata' },
  OPTED_OUT: { label: 'Opted out of rounds', tone: 'warn' },
}

function NodeFacts({ hospital }) {
  const node = hospital.node
  if (!node) {
    return (
      <div className="col-span-2">
        <dt className="text-xs text-muted">Hospital node</dt>
        <dd className="mt-1 text-muted">Has not connected yet. Start it on the hospital's machine.</dd>
      </div>
    )
  }
  return (
    <>
      <div>
        <dt className="text-xs text-muted">Machine</dt>
        <dd className="mt-1 truncate font-mono text-[13px] text-ink" title={node.hostname}>
          {node.hostname || DASH}
        </dd>
      </div>
      <div>
        <dt className="text-xs text-muted">Last heartbeat</dt>
        <dd className="mt-1 text-ink">{secondsAgo(node.last_seen_at)}</dd>
      </div>
      <div>
        <dt className="text-xs text-muted">Device</dt>
        <dd className="mt-1 text-ink">
          {node.device ? node.device.toUpperCase() : DASH}
          <span className="text-muted"> · {node.ml_backend || DASH}</span>
        </dd>
      </div>
      <div>
        <dt className="text-xs text-muted">Node software</dt>
        <dd className="mt-1 text-ink">{node.software_version ? `v${node.software_version}` : DASH}</dd>
      </div>
    </>
  )
}

function HospitalCard({ hospital, canManage, canOpen, onToggle, busy }) {
  const participation = PARTICIPATION[hospital.fl_participation] || PARTICIPATION.IDLE
  const external = hospital.node_mode === 'external'
  return (
    <Card as="article" className="flex flex-col">
      <div className="flex items-start justify-between gap-3 border-b border-line px-5 py-4">
        <div className="min-w-0">
          <p className="font-mono text-xs text-muted">{hospital.id}</p>
          <h2 className="mt-0.5 truncate text-base font-semibold text-ink">{hospital.name}</h2>
          {hospital.kind ? <p className="text-sm text-muted">{hospital.kind}</p> : null}
        </div>
        <div className="flex shrink-0 flex-col items-end gap-1.5">
          <Badge tone={hospital.online ? 'ok' : 'nodata'}>
            <span className={`h-1.5 w-1.5 rounded-full ${hospital.online ? 'bg-ok' : 'bg-nodata'}`} aria-hidden="true" />
            {availabilityLabel(hospital)}
          </Badge>
          {hospital.is_simulated ? <SimulatedTag compact /> : null}
        </div>
      </div>

      <dl className="grid flex-1 grid-cols-2 gap-x-5 gap-y-4 px-5 py-4 text-sm">
        <div>
          <dt className="text-xs text-muted">FL participation</dt>
          <dd className="mt-1">
            <Badge tone={participation.tone}>{participation.label}</Badge>
          </dd>
        </div>
        <div>
          <dt className="text-xs text-muted">Rounds completed</dt>
          <dd className="mt-1 font-medium text-ink">{hospital.rounds_completed}</dd>
        </div>
        <div className="col-span-2">
          <dt className="text-xs text-muted">Supported modalities and local records</dt>
          <dd className="mt-1.5 flex flex-wrap gap-x-4 gap-y-1.5">
            {MODALITY_ORDER.filter((m) => hospital.modalities.includes(m)).map((modality) => {
              const summary = hospital.data_summary[modality]
              return (
                <span key={modality} className="inline-flex items-center gap-1.5 text-sm text-ink">
                  <ModalityTag modality={modality} />
                  {summary ? formatNumber(summary.train_samples + summary.val_samples) : DASH}
                </span>
              )
            })}
            {hospital.modalities.length === 0 ? <span className="text-muted">No local data reported</span> : null}
          </dd>
        </div>
        <div>
          <dt className="text-xs text-muted">Current round</dt>
          <dd className="mt-1 text-ink">
            {hospital.current_round ? (
              <>
                <span className="font-mono text-[13px]">{hospital.current_round.id}</span>
                <span className="block text-xs text-muted">
                  {PARTICIPANT_LABELS[hospital.current_round.participant_status] || hospital.current_round.participant_status}
                </span>
              </>
            ) : (
              'None'
            )}
          </dd>
        </div>
        <div>
          <dt className="text-xs text-muted">Latest model update</dt>
          <dd className="mt-1 text-ink">
            {hospital.latest_update ? (
              <>
                <span className="font-mono text-[13px]">{hospital.latest_update.round_id}</span>
                <span className="block text-xs text-muted">{formatDateTime(hospital.latest_update.received_at)}</span>
              </>
            ) : (
              'None sent yet'
            )}
          </dd>
        </div>
        <div className="col-span-2">
          <dt className="text-xs text-muted">Last round activity</dt>
          <dd className="mt-1 text-ink">{timeAgo(hospital.last_activity_at)}</dd>
        </div>
        {external ? <NodeFacts hospital={hospital} /> : null}
      </dl>

      <div className="flex items-center justify-between gap-3 border-t border-line px-5 py-3">
        {canManage && !external ? (
          <Button size="sm" loading={busy} onClick={() => onToggle(hospital)}>
            {hospital.online ? 'Take offline' : 'Bring online'}
          </Button>
        ) : (
          <span />
        )}
        {canOpen ? (
          <Link
            to={`/hospitals/${hospital.id}`}
            className="inline-flex items-center gap-1 text-sm font-medium text-brand-700 hover:underline"
          >
            View details
            <ChevronRight className="h-4 w-4" aria-hidden="true" />
          </Link>
        ) : null}
      </div>
    </Card>
  )
}

export default function Hospitals() {
  const { user } = useAuth()
  const state = useApi(() => api.hospitals(), [], { isEmpty: (data) => data.length === 0 })
  const [busyId, setBusyId] = useState(null)
  const [actionError, setActionError] = useState(null)
  const loaded = state.status === 'success'
  const external = loaded && state.data.some((h) => h.node_mode === 'external')
  const anyInRound = loaded && state.data.some((h) => h.current_round)
  // External nodes connect and disconnect on their own, so keep their status live.
  usePolling(() => state.reload({ silent: true }), 3000, anyInRound || external)

  async function toggle(hospital) {
    setBusyId(hospital.id)
    setActionError(null)
    try {
      await api.setHospitalAvailability(hospital.id, !hospital.online)
      await state.reload({ silent: true })
    } catch (error) {
      setActionError(toApiError(error).message)
    } finally {
      setBusyId(null)
    }
  }

  return (
    <>
      <PageHeader
        title="Hospitals"
        description="The hospitals in the federation. The coordinator knows each hospital's availability and how many records it holds per modality. It never holds the records themselves."
      />
      {external ? (
        <Note title="Hospitals run on their own machines" className="mb-4">
          Each hospital is a separate node process, usually on its own computer. It sends a heartbeat every 10 seconds and
          shows as connected while those keep arriving (disconnected after 30 seconds without one). Only connected
          hospitals are invited to a new round.
        </Note>
      ) : null}
      {actionError ? (
        <Note tone="alert" title="The change was not applied" className="mb-4">
          {actionError}
        </Note>
      ) : null}
      <AsyncView
        state={state}
        what="hospitals"
        empty={
          <EmptyState
            title="No hospitals connected"
            description="A hospital appears here once its node registers with the coordinator."
            illustration
          />
        }
      >
        {(hospitals) => (
          <div className="grid gap-5 md:grid-cols-2">
            {hospitals.map((hospital) => (
              <HospitalCard
                key={hospital.id}
                hospital={hospital}
                canManage={canManageRounds(user)}
                canOpen={canOpenHospitalDetails(user) && (!isHospitalOperator(user) || user.hospital_id === hospital.id)}
                onToggle={toggle}
                busy={busyId === hospital.id}
              />
            ))}
          </div>
        )}
      </AsyncView>
    </>
  )
}
