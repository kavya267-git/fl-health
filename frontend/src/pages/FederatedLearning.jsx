import { Play } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { PipelineDiagram } from '../components/federated/PipelineDiagram'
import { RoundStepper } from '../components/federated/RoundStepper'
import { StartRoundDialog } from '../components/federated/StartRoundDialog'
import { ModalityTag, ParticipantStatusBadge, RoundStatusBadge, SimulatedTag } from '../components/ui/Badge'
import { Button } from '../components/ui/Button'
import { Card, CardBody, CardHeader } from '../components/ui/Card'
import { DefinitionList, Note, PageHeader, Tabs, Td, Th } from '../components/ui/Misc'
import { AsyncView, EmptyState, ErrorState, LoadingState } from '../components/ui/StateViews'
import { useAuth } from '../context/AuthContext'
import { useApi } from '../hooks/useApi'
import { usePolling } from '../hooks/usePolling'
import { toApiError } from '../services/api'
import { api } from '../services/endpoints'
import { METRIC_LABELS, MODALITIES, MODALITY_ORDER, PARTICIPANT_LABELS, canManageRounds, isRoundActive } from '../utils/constants'
import { DASH, durationBetween, formatDateTime, formatMetric, formatNumber, formatPercent } from '../utils/format'

function GlobalMetrics({ round }) {
  const metrics = round.global_metrics
  if (!metrics) return null
  return (
    <div>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-5">
        {['accuracy', 'precision', 'recall', 'f1', 'loss'].map((key) => (
          <div key={key} className="rounded-md border border-line px-3 py-2.5">
            <p className="text-xs text-muted">{METRIC_LABELS[key]}</p>
            <p className="mt-0.5 text-lg font-semibold text-ink">{formatMetric(key, metrics[key])}</p>
          </div>
        ))}
      </div>
      <p className="mt-3 text-xs leading-relaxed text-muted">
        Global model v{round.result_model_version}, scored by {metrics.evaluated_hospitals?.length ?? 0} hospitals on their own held-out
        records ({formatNumber(metrics.num_samples)} in total). Precision, recall and F1: {metrics.averaging}.
      </p>
    </div>
  )
}

function ParticipantsTable({ round }) {
  const coefficients = round.config?.aggregation?.coefficients || {}
  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse">
        <thead>
          <tr>
            <Th>Hospital</Th>
            <Th>Status</Th>
            <Th align="right">Training records (n)</Th>
            <Th align="right">FedAvg weight (n / N)</Th>
            <Th align="right">Local training loss</Th>
            <Th align="right">Local model F1</Th>
          </tr>
        </thead>
        <tbody>
          {round.participants.map((participant) => {
            const history = participant.local_metrics?.training_history
            const lastEpoch = history?.length ? history[history.length - 1] : null
            const validation = participant.local_metrics?.local_validation
            return (
              <tr key={participant.hospital_id}>
                <Td className="whitespace-nowrap">{participant.hospital_name || participant.hospital_id}</Td>
                <Td>
                  <ParticipantStatusBadge status={participant.status} />
                </Td>
                <Td align="right">{formatNumber(participant.num_samples)}</Td>
                <Td align="right">
                  {coefficients[participant.hospital_id] !== undefined ? formatPercent(coefficients[participant.hospital_id]) : DASH}
                </Td>
                <Td align="right">{lastEpoch ? lastEpoch.loss.toFixed(3) : DASH}</Td>
                <Td align="right">{validation ? formatPercent(validation.f1) : DASH}</Td>
              </tr>
            )
          })}
        </tbody>
      </table>
      <p className="px-4 py-3 text-xs leading-relaxed text-muted">
        Local model F1 is each hospital&rsquo;s own model after local training, before averaging, on that hospital&rsquo;s held-out records.
      </p>
    </div>
  )
}

const LEFT_OUT = ['DROPPED', 'FAILED', 'UPDATE_REJECTED']

/** Hospitals the round went on without, and why. A late or crashed hospital never holds a round up for good. */
function DroppedHospitals({ round }) {
  const leftOut = round.participants.filter((p) => LEFT_OUT.includes(p.status))
  const noEvaluation = round.participants.filter((p) => p.status === 'EVALUATION_FAILED')
  if (!leftOut.length && !noEvaluation.length) return null
  return (
    <Note tone="warn" title={`${leftOut.length} hospital${leftOut.length === 1 ? '' : 's'} dropped from this round`}>
      <ul className="mt-1 space-y-1">
        {leftOut.map((p) => (
          <li key={p.hospital_id}>
            <span className="font-medium">{p.hospital_name || p.hospital_id}</span> ({PARTICIPANT_LABELS[p.status].toLowerCase()}):{' '}
            {p.error || 'no reason recorded'}
          </li>
        ))}
        {noEvaluation.map((p) => (
          <li key={p.hospital_id}>
            <span className="font-medium">{p.hospital_name || p.hospital_id}</span> (update used, no evaluation):{' '}
            {p.error || 'no reason recorded'}
          </li>
        ))}
      </ul>
      {leftOut.length ? (
        <p className="mt-2">Their records were not part of this round&rsquo;s update; the other hospitals&rsquo; updates were averaged.</p>
      ) : null}
    </Note>
  )
}

function deadlineText(round) {
  const deadline = round.config.deadline
  if (!deadline) return null
  const due = round.status === 'EVALUATING' ? deadline.evaluation_deadline_at : deadline.training_deadline_at
  if (!due) return null
  const left = Math.max(0, Math.round((new Date(due).getTime() - Date.now()) / 1000))
  const stage = round.status === 'EVALUATING' ? 'evaluations' : 'updates'
  const remaining = left >= 60 ? `${Math.floor(left / 60)} min ${left % 60} s` : `${left} s`
  return `Deadline for ${stage}: ${formatDateTime(due)} (${remaining} left). Hospitals that miss it are dropped.`
}

function RoundPanel({ roundId, hospitals, canManage, onChanged }) {
  const state = useApi(() => api.round(roundId), [roundId])
  const round = state.data
  const active = state.status === 'success' && isRoundActive(round)
  usePolling(() => state.reload({ silent: true }), 1500, active)
  const [busy, setBusy] = useState(null)
  const [actionError, setActionError] = useState(null)

  // Tell the parent when the round reaches a final state, so lists refresh once.
  const lastStatus = useRef(null)
  useEffect(() => {
    if (!round) return
    if (lastStatus.current && lastStatus.current !== round.status && !isRoundActive(round)) onChanged()
    lastStatus.current = round.status
  }, [round, onChanged])

  async function act(name, call) {
    setBusy(name)
    setActionError(null)
    try {
      await call()
      await state.reload({ silent: true })
      onChanged()
    } catch (error) {
      setActionError(toApiError(error).message)
    } finally {
      setBusy(null)
    }
  }

  if (state.status === 'loading') return <LoadingState label="Loading the round" />
  if (state.status === 'error') return <ErrorState error={state.error} what="this round" onRetry={state.reload} />

  const config = round.config
  const dp = config.differential_privacy
  const minimum = config.min_participants
  const canAggregate = canManage && ['TRAINING', 'UPDATES_RECEIVING'].includes(round.status) && round.updates_received >= minimum

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader
          title={
            <span className="flex flex-wrap items-center gap-2.5">
              <span className="font-mono text-sm">{round.id}</span>
              <RoundStatusBadge status={round.status} />
              {round.is_simulated ? <SimulatedTag compact /> : null}
            </span>
          }
          description={`Started ${formatDateTime(round.started_at)} by ${round.created_by || 'unknown'}`}
          action={
            canManage && active ? (
              <div className="flex gap-2">
                {canAggregate ? (
                  <Button size="sm" loading={busy === 'aggregate'} onClick={() => act('aggregate', () => api.aggregateRound(round.id))}>
                    Aggregate now
                  </Button>
                ) : null}
                <Button
                  size="sm"
                  variant="danger"
                  loading={busy === 'cancel'}
                  onClick={() => act('cancel', () => api.cancelRound(round.id))}
                >
                  Cancel round
                </Button>
              </div>
            ) : null
          }
        />
        <CardBody className="space-y-5">
          <RoundStepper status={round.status} />
          {round.status === 'FAILED' ? (
            <Note tone="alert" title="This round failed">
              {round.error || 'No reason was recorded.'} The global model was not changed.
            </Note>
          ) : null}
          <DroppedHospitals round={round} />
          {active && deadlineText(round) ? <p className="text-xs text-muted">{deadlineText(round)}</p> : null}
          {actionError ? (
            <Note tone="alert" title="The action was not applied">
              {actionError}
            </Note>
          ) : null}
          <PipelineDiagram round={round} hospitals={hospitals} />
        </CardBody>
      </Card>

      <Card>
        <CardHeader
          title="Hospitals in this round"
          description={`${round.updates_received} of ${round.updates_expected} updates received, ${round.evaluations_received} evaluations reported`}
        />
        <ParticipantsTable round={round} />
      </Card>
      <Card>
        <CardHeader title="Round settings" />
        <CardBody>
          <DefinitionList
            columns={5}
            items={[
              { term: 'Model', value: `${config.model.architecture} (${config.model.backend})` },
              { term: 'Aggregation', value: `FedAvg, ${round.aggregation_status.toLowerCase().replace('_', ' ')}` },
              { term: 'Base model version', value: `v${round.base_model_version}` },
              { term: 'New model version', value: round.result_model_version !== null ? `v${round.result_model_version}` : DASH },
              { term: 'Local epochs', value: config.training.local_epochs },
              { term: 'Learning rate', value: config.training.learning_rate },
              { term: 'Batch size', value: config.training.batch_size },
              { term: 'Minimum hospitals', value: minimum },
              { term: 'Deadline', value: config.deadline ? `${config.deadline.seconds} s per stage` : 'None' },
              {
                term: 'Differential privacy',
                value: dp.enabled ? `On: clip ${dp.clip_norm}, noise ×${dp.noise_multiplier} (prototype)` : 'Off',
              },
              { term: 'Duration', value: durationBetween(round.started_at, round.ended_at) },
            ]}
          />
        </CardBody>
      </Card>

      {round.status === 'COMPLETED' ? (
        <Card>
          <CardHeader title="Global model after this round" />
          <CardBody>
            <GlobalMetrics round={round} />
          </CardBody>
        </Card>
      ) : null}
    </div>
  )
}

function RoundHistory({ rounds, selectedId, onSelect }) {
  return (
    <Card>
      <CardHeader title="Round history" description="Every round for this modality, newest first." />
      <div className="overflow-x-auto">
        <table className="w-full border-collapse">
          <thead>
            <tr>
              <Th>Round</Th>
              <Th>Status</Th>
              <Th>Started</Th>
              <Th align="right">Hospitals</Th>
              <Th align="right">Model version</Th>
              <Th align="right">Accuracy</Th>
              <Th align="right">F1</Th>
              <Th align="right">Loss</Th>
            </tr>
          </thead>
          <tbody>
            {rounds.map((round) => (
              <tr key={round.id} className={round.id === selectedId ? 'bg-brand-50' : 'hover:bg-canvas'}>
                <Td>
                  <button
                    type="button"
                    onClick={() => onSelect(round.id)}
                    className="font-mono text-[13px] font-medium text-brand-700 hover:underline"
                  >
                    {round.id}
                  </button>
                </Td>
                <Td>
                  <RoundStatusBadge status={round.status} />
                </Td>
                <Td>{formatDateTime(round.started_at)}</Td>
                <Td align="right">{round.num_participants}</Td>
                <Td align="right">{round.result_model_version !== null ? `v${round.result_model_version}` : DASH}</Td>
                <Td align="right">{formatMetric('accuracy', round.global_metrics?.accuracy)}</Td>
                <Td align="right">{formatMetric('f1', round.global_metrics?.f1)}</Td>
                <Td align="right">{formatMetric('loss', round.global_metrics?.loss)}</Td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  )
}

export default function FederatedLearning() {
  const { user } = useAuth()
  const canManage = canManageRounds(user)
  const [modality, setModality] = useState('ehr')
  const [selectedId, setSelectedId] = useState(null)
  const [dialogOpen, setDialogOpen] = useState(false)

  const state = useApi(async () => {
    const [rounds, hospitals] = await Promise.all([api.rounds(), api.hospitals()])
    return { rounds, hospitals }
  }, [])

  const rounds = state.data ? state.data.rounds.filter((r) => r.modality === modality) : []
  // A just-started round may not be in the list yet; trust the selection.
  const currentId = selectedId ?? rounds[0]?.id
  const activeRound = rounds.find(isRoundActive)
  // Keep the history table in step with a running round.
  usePolling(() => state.reload({ silent: true }), 2500, Boolean(activeRound))
  // Hospitals connect and disconnect on their own: list them as they are now, not as at page load.
  async function openStartDialog() {
    await state.reload({ silent: true })
    setDialogOpen(true)
  }

  return (
    <>
      <PageHeader
        title="Federated Learning"
        description="Run and follow training rounds. In each round the hospitals train the current global model on their own data, send back model updates, and the coordinator averages them into the next global model."
        actions={
          canManage ? (
            <Button
              variant="primary"
              icon={Play}
              onClick={openStartDialog}
              disabled={state.status !== 'success' || Boolean(activeRound)}
            >
              Start new round
            </Button>
          ) : null
        }
      />

      <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
        <Tabs
          label="Model"
          value={modality}
          onChange={(value) => {
            setModality(value)
            setSelectedId(null)
          }}
          options={MODALITY_ORDER.map((m) => ({ value: m, label: MODALITIES[m].label }))}
        />
        <p className="text-sm text-muted">
          {activeRound
            ? `Round ${activeRound.id} is running. A new ${MODALITIES[modality].label} round can start when it finishes.`
            : canManage
              ? `${MODALITIES[modality].name}: target architecture ${MODALITIES[modality].target}.`
              : 'Your role can follow rounds but not start them.'}
        </p>
      </div>

      <AsyncView state={state} what="federated rounds">
        {({ hospitals }) => (
          <div className="space-y-6">
            {currentId ? (
              <RoundPanel
                key={currentId}
                roundId={currentId}
                hospitals={hospitals}
                canManage={canManage}
                onChanged={() => state.reload({ silent: true })}
              />
            ) : (
              <Card>
                <CardHeader
                  title={
                    <span className="flex items-center gap-2.5">
                      <ModalityTag modality={modality} />
                      No {MODALITIES[modality].label} round has been run yet
                    </span>
                  }
                  description="This is what a round will do."
                />
                <CardBody className="space-y-5">
                  <PipelineDiagram round={null} hospitals={hospitals} />
                  <EmptyState
                    title="No results to show"
                    description={
                      canManage
                        ? 'Start a round to train the first global model for this modality.'
                        : 'Ask an administrator or FL coordinator to start a round.'
                    }
                    action={
                      canManage ? (
                        <Button variant="primary" icon={Play} onClick={openStartDialog}>
                          Start new round
                        </Button>
                      ) : null
                    }
                  />
                </CardBody>
              </Card>
            )}
            {rounds.length > 0 ? <RoundHistory rounds={rounds} selectedId={currentId} onSelect={setSelectedId} /> : null}
          </div>
        )}
      </AsyncView>

      {dialogOpen && state.status === 'success' ? (
        <StartRoundDialog
          modality={modality}
          hospitals={state.data.hospitals}
          onClose={() => setDialogOpen(false)}
          onStarted={(round) => {
            // The server has confirmed the round; show it and start following it.
            setDialogOpen(false)
            setModality(round.modality)
            setSelectedId(round.id)
            state.reload({ silent: true })
          }}
        />
      ) : null}
    </>
  )
}
