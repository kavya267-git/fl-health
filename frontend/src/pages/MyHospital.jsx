import { Check, Circle, Loader2, X } from 'lucide-react'
import { useState } from 'react'
import { Badge, ModalityTag, ParticipantStatusBadge, RoundStatusBadge, SimulatedTag } from '../components/ui/Badge'
import { Card, CardBody, CardHeader } from '../components/ui/Card'
import { DefinitionList, Note, PageHeader, Td, Th } from '../components/ui/Misc'
import { AsyncView, EmptyState } from '../components/ui/StateViews'
import { useAuth } from '../context/AuthContext'
import { useApi } from '../hooks/useApi'
import { usePolling } from '../hooks/usePolling'
import { toApiError } from '../services/api'
import { api } from '../services/endpoints'
import { F1_KIND, MODALITIES, availabilityLabel, canChangeParticipation } from '../utils/constants'
import { DASH, classNames, formatBytes, formatDateTime, formatNumber, formatPercent, secondsAgo } from '../utils/format'
import { ConnectHospital } from '../components/hospital/ConnectHospital'
import { DataSummary, LocalMetrics } from './HospitalDetail'

const FAILED = ['FAILED', 'DROPPED', 'UPDATE_REJECTED', 'EVALUATION_FAILED']
const ROUND_OVER = ['COMPLETED', 'FAILED']

/** Where this hospital is in a round: 0 invited, 1 training, 2 update sent, 3 evaluated. */
function progressOf(round) {
  switch (round.status) {
    case 'INVITED':
      return { reached: 0, failedAt: null }
    case 'JOINED':
    case 'TRAINING':
      return { reached: 1, failedAt: null }
    case 'UPDATE_SUBMITTED':
      return { reached: 2, failedAt: null }
    case 'EVALUATED':
      return { reached: 3, failedAt: null }
    case 'EVALUATION_FAILED':
      return { reached: 2, failedAt: 3 }
    case 'UPDATE_REJECTED':
      return { reached: 1, failedAt: 2 }
    default: // FAILED or DROPPED: before an update was accepted
      return { reached: round.joined_at ? 1 : 0, failedAt: round.joined_at ? 2 : 1 }
  }
}

function Step({ label, detail, state }) {
  const icon = {
    done: <Check className="h-4 w-4" aria-hidden="true" />,
    active: <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />,
    failed: <X className="h-4 w-4" aria-hidden="true" />,
    todo: <Circle className="h-3 w-3" aria-hidden="true" />,
  }[state]
  return (
    <li className="flex min-w-0 flex-1 items-start gap-3">
      <span
        className={classNames(
          'mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full border',
          state === 'done' && 'border-ok bg-ok text-white',
          state === 'active' && 'border-brand-600 bg-brand-50 text-brand-700',
          state === 'failed' && 'border-alert bg-alert text-white',
          state === 'todo' && 'border-line-strong text-faint',
        )}
      >
        {icon}
      </span>
      <div className="min-w-0">
        <p className={classNames('text-sm font-medium', state === 'todo' ? 'text-faint' : 'text-ink')}>{label}</p>
        {detail ? <p className="mt-0.5 text-xs text-muted">{detail}</p> : null}
      </div>
    </li>
  )
}

function RoundFromHere({ round }) {
  if (!round) {
    return <EmptyState
        title="No round yet"
        description="When a coordinator starts a round that invites this hospital, it appears here live."
        illustration
      />
  }
  const { reached, failedAt } = progressOf(round)
  const over = ROUND_OVER.includes(round.round_status)
  const size = round.update_bytes ? formatBytes(round.update_bytes) : null
  const global = round.global_model_on_local_data
  const steps = [
    { label: 'Invited', detail: formatDateTime(round.started_at) },
    { label: 'Training locally', detail: round.joined_at ? `joined ${formatDateTime(round.joined_at)}` : null },
    {
      label: 'Update sent',
      detail: round.update_received_at
        ? [size, round.num_samples ? `${formatNumber(round.num_samples)} records` : null].filter(Boolean).join(' · ')
        : null,
    },
    { label: 'Evaluated', detail: global ? `F1 ${formatPercent(global.f1)} on this hospital's held-out data` : null },
  ]
  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center gap-2.5">
        <span className="font-mono text-sm">{round.round_id}</span>
        <ModalityTag modality={round.modality} />
        <span className="text-sm text-muted">round {round.round_number}</span>
        <RoundStatusBadge status={round.round_status} />
        <ParticipantStatusBadge status={round.status} />
      </div>
      <ol className="flex flex-col gap-4 sm:flex-row" aria-label="This hospital's progress in the round">
        {steps.map((step, index) => {
          let state = 'todo'
          if (failedAt === index) state = 'failed'
          else if (index <= reached) state = 'done'
          else if (index === reached + 1 && failedAt === null && !over) state = 'active'
          return <Step key={step.label} label={step.label} detail={step.detail} state={state} />
        })}
      </ol>
      {round.error ? (
        <Note tone={FAILED.includes(round.status) ? 'alert' : 'warn'} title="This hospital's part of the round did not finish">
          {round.error}
        </Note>
      ) : null}
      {round.status === 'UPDATE_SUBMITTED' && !over ? (
        <p className="text-sm text-muted">Update received by the coordinator. Waiting for the other hospitals and for aggregation.</p>
      ) : null}
      {round.local_model || global ? (
        <DefinitionList
          columns={2}
          items={[
            {
              term: `Model trained here, before averaging (F1${F1_KIND[round.modality] ? `, ${F1_KIND[round.modality].short}` : ''}, on local held-out data)`,
              value: round.local_model ? formatPercent(round.local_model.f1) : DASH,
            },
            {
              term: `New global model on local held-out data (F1${F1_KIND[round.modality] ? `, ${F1_KIND[round.modality].short}` : ''})`,
              value: global ? formatPercent(global.f1) : DASH,
            },
          ]}
        />
      ) : null}
    </div>
  )
}

function NodeStatus({ hospital }) {
  const node = hospital.node
  if (hospital.node_mode !== 'external') {
    return <p className="text-sm text-muted">This server runs its hospitals in-process (simulated), so there is no separate node.</p>
  }
  if (!node) {
    return (
      <Note tone="warn" title="This hospital's node has not connected yet">
        Start it on this hospital&rsquo;s laptop: <code className="font-mono text-[13px]">python scripts/setup_hospital.py {hospital.id}</code>
      </Note>
    )
  }
  return (
    <DefinitionList
      columns={3}
      items={[
        {
          term: 'Node',
          value: (
            <Badge tone={hospital.online ? 'ok' : 'nodata'}>
              <span className={`h-1.5 w-1.5 rounded-full ${hospital.online ? 'bg-ok' : 'bg-nodata'}`} aria-hidden="true" />
              {availabilityLabel(hospital)}
            </Badge>
          ),
        },
        { term: 'Last heartbeat', value: secondsAgo(node.last_seen_at) },
        { term: 'Machine', value: <span className="font-mono text-[13px]">{node.hostname || DASH}</span> },
        { term: 'Device', value: node.device ? (node.device === 'cuda' ? 'GPU (CUDA)' : 'CPU') : DASH },
        { term: 'ML backend', value: node.ml_backend || DASH },
        { term: 'Node software', value: node.software_version ? `v${node.software_version}` : DASH },
      ]}
    />
  )
}

function ParticipationSwitch({ hospital, onChanged }) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const on = hospital.participating

  async function toggle() {
    setBusy(true)
    setError(null)
    try {
      await api.setHospitalParticipation(hospital.id, !on)
      await onChanged()
    } catch (failure) {
      setError(toApiError(failure).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between gap-4">
        <div>
          <p id="participation-label" className="text-sm font-medium text-ink">
            Take part in future rounds
          </p>
          <p className="mt-0.5 text-sm text-muted">
            {on
              ? 'On: the coordinator may invite this hospital, and its node trains when invited.'
              : 'Off: the coordinator does not invite this hospital, and its node declines any round it was already invited to.'}
          </p>
        </div>
        <button
          type="button"
          role="switch"
          aria-checked={on}
          aria-labelledby="participation-label"
          disabled={busy}
          onClick={toggle}
          className={classNames(
            'relative inline-flex h-7 w-12 shrink-0 items-center rounded-full transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-600 disabled:opacity-60',
            on ? 'bg-ok' : 'bg-line-strong',
          )}
        >
          <span
            className={classNames(
              'inline-block h-5 w-5 rounded-full bg-white shadow transition-transform',
              on ? 'translate-x-6' : 'translate-x-1',
            )}
          />
        </button>
      </div>
      <p className="text-xs text-muted">Every change is recorded in the audit log.</p>
      {error ? <Note tone="alert">{error}</Note> : null}
    </div>
  )
}

export default function MyHospital() {
  const { user } = useAuth()
  const state = useApi(() => api.myHospital(), [])
  const data = state.status === 'success' ? state.data : null
  const active = Boolean(data?.latest_round) && !ROUND_OVER.includes(data.latest_round.round_status)
  // Live: quick while a round runs, and often enough otherwise for the heartbeat to stay current.
  usePolling(() => state.reload({ silent: true }), active ? 1500 : 5000, state.status === 'success')

  return (
    <AsyncView state={state} what="your hospital">
      {({ hospital, metrics, latest_round: round, connection }) => (
        <>
          <PageHeader
            title={hospital.name}
            description={`My hospital (${hospital.id}). Only this hospital's own details are shown here; its records never leave its node.`}
            actions={
              <>
                <Badge tone={hospital.online ? 'ok' : 'nodata'}>{availabilityLabel(hospital)}</Badge>
                {hospital.is_simulated ? <SimulatedTag compact /> : null}
              </>
            }
          />
          <div className="space-y-6">
            {connection?.registered ? <ConnectHospital connection={connection} onChanged={() => state.reload({ silent: true })} /> : null}
            <div className="grid gap-6 lg:grid-cols-[3fr_2fr]">
              <Card>
                <CardHeader title="Hospital node" description="From the heartbeat the node sends every 10 seconds." />
                <CardBody>
                  <NodeStatus hospital={hospital} />
                </CardBody>
              </Card>
              <Card>
                <CardHeader title="Participation" />
                <CardBody>
                  {canChangeParticipation(user) ? (
                    <ParticipationSwitch hospital={hospital} onChanged={() => state.reload({ silent: true })} />
                  ) : (
                    <p className="text-sm text-muted">
                      {hospital.participating ? 'Taking part in future rounds.' : 'Not taking part in future rounds.'} Only the
                      hospital&rsquo;s operator can change this.
                    </p>
                  )}
                </CardBody>
              </Card>
            </div>

            <Card>
              <CardHeader
                title={round && !ROUND_OVER.includes(round.round_status) ? 'Current round' : 'Latest round'}
                description="This hospital's side of the round: what its node has done so far."
              />
              <CardBody>
                <RoundFromHere round={round} />
              </CardBody>
            </Card>

            <Card>
              <CardHeader title="Local data" description="Record counts only. The records themselves stay on this hospital's node." />
              <DataSummary hospital={hospital} />
            </Card>

            <Card>
              <CardHeader
                title="History"
                description="Per round: the model trained here before averaging, and the global model after FedAvg, both scored on this hospital's held-out records."
              />
              <CardBody>
                <LocalMetrics metrics={metrics} />
              </CardBody>
              {metrics.participation.length ? (
                <div className="overflow-x-auto border-t border-line">
                  <table className="w-full border-collapse">
                    <thead>
                      <tr>
                        <Th>Round</Th>
                        <Th>Model</Th>
                        <Th>This hospital</Th>
                        <Th>Round</Th>
                        <Th align="right">Training records</Th>
                        <Th>Update received</Th>
                      </tr>
                    </thead>
                    <tbody>
                      {metrics.participation.map((row) => (
                        <tr key={row.round_id}>
                          <Td className="font-mono text-[13px]">{row.round_id}</Td>
                          <Td>{MODALITIES[row.modality]?.label || row.modality}</Td>
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
              ) : null}
            </Card>
          </div>
        </>
      )}
    </AsyncView>
  )
}
