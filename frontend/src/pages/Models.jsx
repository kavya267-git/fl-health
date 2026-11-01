import { ChevronRight } from 'lucide-react'
import { Link } from 'react-router-dom'
import { Badge, ModalityTag, SimulatedTag } from '../components/ui/Badge'
import { Card } from '../components/ui/Card'
import { Note, PageHeader } from '../components/ui/Misc'
import { AsyncView } from '../components/ui/StateViews'
import { useApi } from '../hooks/useApi'
import { api } from '../services/endpoints'
import { METRIC_LABELS, MODALITIES } from '../utils/constants'
import { DASH, formatDateTime, formatMetric, formatNumber } from '../utils/format'

function ModelCard({ model }) {
  const meta = MODALITIES[model.modality]
  const trained = model.training_status === 'TRAINED'
  const metrics = model.latest_metrics
  return (
    <Card as="article" className="flex flex-col">
      <div
        className="border-b border-line px-5 py-4"
        style={{ borderTop: `3px solid ${meta.color}`, borderTopLeftRadius: 8, borderTopRightRadius: 8 }}
      >
        <div className="flex items-center justify-between gap-2">
          <ModalityTag modality={model.modality} />
          {model.is_simulated ? <SimulatedTag compact /> : null}
        </div>
        <h2 className="mt-3 text-lg font-semibold text-ink">{model.target_architecture}</h2>
        <p className="text-sm text-muted">{model.task.name}</p>
      </div>

      <div className="flex-1 space-y-4 px-5 py-4">
        {!model.is_target_architecture ? (
          <Note tone="warn" title={`Running: ${model.architecture}`}>
            A NumPy stand-in is training in place of {model.target_architecture}, because PyTorch is not installed on the server or the
            reference backend was selected. The numbers below belong to the stand-in.
          </Note>
        ) : null}

        <dl className="grid grid-cols-2 gap-x-4 gap-y-3 text-sm">
          <div>
            <dt className="text-xs text-muted">Model version</dt>
            <dd className="mt-0.5 font-medium text-ink">v{model.current_version}</dd>
          </div>
          <div>
            <dt className="text-xs text-muted">Training status</dt>
            <dd className="mt-0.5">
              <Badge tone={trained ? 'ok' : 'neutral'}>{trained ? 'Trained' : 'Not trained yet'}</Badge>
            </dd>
          </div>
          <div>
            <dt className="text-xs text-muted">Latest round</dt>
            <dd className="mt-0.5 font-mono text-[13px] text-ink">{model.latest_round_id || DASH}</dd>
          </div>
          <div>
            <dt className="text-xs text-muted">Last updated</dt>
            <dd className="mt-0.5 text-ink">{formatDateTime(model.last_updated)}</dd>
          </div>
          <div>
            <dt className="text-xs text-muted">Parameters</dt>
            <dd className="mt-0.5 text-ink">{formatNumber(model.num_parameters)}</dd>
          </div>
          <div>
            <dt className="text-xs text-muted">Backend</dt>
            <dd className="mt-0.5 text-ink">{model.backend}</dd>
          </div>
        </dl>

        <div>
          <p className="text-xs text-muted">Evaluation metrics</p>
          {metrics ? (
            <dl className="mt-1.5 grid grid-cols-5 gap-2">
              {['accuracy', 'precision', 'recall', 'f1', 'loss'].map((key) => (
                <div key={key} className="rounded border border-line px-2 py-1.5 text-center">
                  <dt className="text-[11px] text-muted">{METRIC_LABELS[key]}</dt>
                  <dd className="text-sm font-semibold text-ink">{formatMetric(key, metrics[key])}</dd>
                </div>
              ))}
            </dl>
          ) : (
            <p className="mt-1.5 text-sm text-muted">None yet. Metrics appear after the first completed round.</p>
          )}
        </div>
      </div>

      <div className="flex items-center justify-between border-t border-line px-5 py-3">
        <span className="text-xs text-muted">
          {model.trained_versions} trained version{model.trained_versions === 1 ? '' : 's'}
        </span>
        <Link to={`/models/${model.id}`} className="inline-flex items-center gap-1 text-sm font-medium text-brand-700 hover:underline">
          Performance and history
          <ChevronRight className="h-4 w-4" aria-hidden="true" />
        </Link>
      </div>
    </Card>
  )
}

export default function Models() {
  const state = useApi(() => api.models(), [], { isEmpty: (data) => data.length === 0 })
  return (
    <>
      <PageHeader
        title="Models"
        description="One global model per modality, each with its own versions. A new version is registered every time a federated round completes."
      />
      <AsyncView state={state} what="models">
        {(models) => (
          <div className="grid gap-5 lg:grid-cols-3">
            {models.map((model) => (
              <ModelCard key={model.id} model={model} />
            ))}
          </div>
        )}
      </AsyncView>
    </>
  )
}
