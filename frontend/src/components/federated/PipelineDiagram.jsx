import { ArrowDown, ArrowRight, Check, Sigma, X } from 'lucide-react'
import { MODALITIES, PARTICIPANT_LABELS } from '../../utils/constants'
import { classNames, formatNumber, formatPercent } from '../../utils/format'

/** Where a hospital is within the round, as an index into LANE_STAGES. */
const LANE_STAGES = ['Joined', 'Local training', 'Update sent', 'Evaluated']
const STAGE_REACHED = { INVITED: 0, JOINED: 1, TRAINING: 1, UPDATE_SUBMITTED: 3, EVALUATED: 4, EVALUATION_FAILED: 3 }
const PROBLEM = ['UPDATE_REJECTED', 'FAILED', 'DROPPED', 'EVALUATION_FAILED']

function Connector() {
  return (
    <div className="flex items-center justify-center py-1 text-line-strong xl:px-1 xl:py-0" aria-hidden="true">
      <ArrowDown className="h-5 w-5 xl:hidden" />
      <ArrowRight className="hidden h-5 w-5 xl:block" />
    </div>
  )
}

function ModelBlock({ title, version, caption, tone = 'neutral', pending = false }) {
  return (
    <div
      className={classNames(
        'flex min-h-28 flex-col justify-center rounded-lg border px-4 py-3 text-center xl:w-40',
        tone === 'result' && !pending ? 'border-brand-600 bg-brand-50' : 'border-line bg-surface',
        pending ? 'border-dashed' : '',
      )}
    >
      <p className="text-xs text-muted">{title}</p>
      <p className={classNames('mt-1 text-2xl font-semibold', pending ? 'text-faint' : 'text-ink')}>{version}</p>
      <p className="mt-1 text-xs leading-snug text-muted">{caption}</p>
    </div>
  )
}

function Lane({ participant, coefficient, roundActive }) {
  const reached = STAGE_REACHED[participant.status] ?? 0
  const problem = PROBLEM.includes(participant.status)
  const training = participant.status === 'TRAINING' && roundActive
  return (
    <li className="rounded-md border border-line bg-surface px-3.5 py-2.5">
      <div className="flex items-baseline justify-between gap-3">
        <p className="truncate text-sm font-medium text-ink">{participant.hospital_name || participant.hospital_id}</p>
        <p className={classNames('shrink-0 text-xs', problem ? 'font-medium text-alert' : 'text-muted')}>
          {PARTICIPANT_LABELS[participant.status] || participant.status}
        </p>
      </div>
      <ol className="mt-2 grid grid-cols-4 gap-1.5" aria-label={`Progress of ${participant.hospital_name || participant.hospital_id}`}>
        {LANE_STAGES.map((stage, index) => {
          const done = reached > index
          const current = training && index === 1
          return (
            <li key={stage} className="min-w-0">
              <div
                className={classNames(
                  'h-1.5 rounded-full',
                  done ? 'bg-brand-600' : current ? 'lane-active bg-brand-100' : problem && index === reached ? 'bg-alert' : 'bg-line',
                )}
              />
              <p className={classNames('mt-1 truncate text-[11px]', done || current ? 'text-ink' : 'text-faint')}>{stage}</p>
            </li>
          )
        })}
      </ol>
      <p className="mt-1.5 text-xs text-muted">
        {participant.num_samples
          ? `${formatNumber(participant.num_samples)} training records`
          : 'Training records reported with the update'}
        {coefficient !== undefined ? `, FedAvg weight ${formatPercent(coefficient)}` : ''}
      </p>
      {participant.error ? <p className="mt-1 text-xs leading-snug text-alert">{participant.error}</p> : null}
    </li>
  )
}

/**
 * The round as a picture: global model -> hospitals train locally -> updates
 * -> FedAvg -> new global model. Flows left to right on wide screens and top
 * to bottom on narrow ones.
 */
export function PipelineDiagram({ round, hospitals }) {
  const modality = MODALITIES[round?.modality]
  const coefficients = round?.config?.aggregation?.coefficients || {}
  const active = round && !['COMPLETED', 'FAILED'].includes(round.status)
  const aggregated = round && ['EVALUATING', 'COMPLETED'].includes(round.status)
  const completed = round?.status === 'COMPLETED'
  const lanes = round
    ? round.participants
    : hospitals.map((h) => ({ hospital_id: h.id, hospital_name: h.name, status: 'INVITED', num_samples: null }))

  return (
    <div className="flex flex-col xl:flex-row xl:items-center">
      <ModelBlock
        title="Global model"
        version={round ? `v${round.base_model_version}` : '—'}
        caption={round ? `${round.config.model.architecture}, sent to each hospital` : 'Sent to each hospital at the start of a round'}
      />
      <Connector />
      <div className="min-w-0 flex-1">
        <p className="mb-2 text-xs text-muted">
          Hospitals train on their own {modality ? modality.label : ''} data and return model updates only
        </p>
        <ul className="grid gap-2">
          {lanes.map((participant) => (
            <Lane
              key={participant.hospital_id}
              participant={participant}
              coefficient={coefficients[participant.hospital_id]}
              roundActive={active}
            />
          ))}
        </ul>
      </div>
      <Connector />
      <div
        className={classNames(
          'flex min-h-28 flex-col items-center justify-center rounded-lg border px-4 py-3 text-center xl:w-36',
          aggregated ? 'border-brand-600 bg-brand-50' : round?.status === 'AGGREGATING' ? 'border-brand-600' : 'border-line bg-surface',
        )}
      >
        <Sigma className={classNames('h-5 w-5', aggregated ? 'text-brand-700' : 'text-faint')} aria-hidden="true" />
        <p className="mt-1 text-sm font-semibold text-ink">FedAvg</p>
        <p className="mt-0.5 text-xs leading-snug text-muted">
          {aggregated
            ? `${round.updates_received} updates averaged by sample count`
            : round?.status === 'FAILED'
              ? 'Not run'
              : 'Weighted average of the updates'}
        </p>
      </div>
      <Connector />
      <div className="relative">
        <ModelBlock
          title="New global model"
          tone="result"
          pending={!completed}
          version={completed ? `v${round.result_model_version}` : round ? `v${round.base_model_version + 1}` : '—'}
          caption={
            completed
              ? 'Registered and ready for the next round'
              : round?.status === 'FAILED'
                ? 'Not created: the round failed'
                : round?.status === 'EVALUATING'
                  ? 'Being evaluated at the hospitals'
                  : 'Created when the round completes'
          }
        />
        {completed ? (
          <span className="absolute -right-2 -top-2 flex h-6 w-6 items-center justify-center rounded-full bg-ok text-white">
            <Check className="h-3.5 w-3.5" aria-hidden="true" />
          </span>
        ) : round?.status === 'FAILED' ? (
          <span className="absolute -right-2 -top-2 flex h-6 w-6 items-center justify-center rounded-full bg-alert text-white">
            <X className="h-3.5 w-3.5" aria-hidden="true" />
          </span>
        ) : null}
      </div>
    </div>
  )
}
