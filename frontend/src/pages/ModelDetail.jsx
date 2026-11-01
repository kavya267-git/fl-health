import { ArrowLeft } from 'lucide-react'
import { useMemo } from 'react'
import { Link, useParams } from 'react-router-dom'
import { MetricLineChart } from '../components/charts/MetricLineChart'
import { HOSPITAL_COLORS } from '../components/charts/theme'
import { Badge, ModalityTag, SimulatedTag } from '../components/ui/Badge'
import { Card, CardBody, CardHeader } from '../components/ui/Card'
import { DefinitionList, Note, PageHeader, Td, Th } from '../components/ui/Misc'
import { AsyncView, EmptyState } from '../components/ui/StateViews'
import { useApi } from '../hooks/useApi'
import { api } from '../services/endpoints'
import { METRIC_LABELS, MODALITIES } from '../utils/constants'
import { DASH, formatDateTime, formatMetric, formatNumber, formatPercent, shortHash } from '../utils/format'

function ConfusionMatrix({ matrix, classNames: names }) {
  const max = Math.max(1, ...matrix.flat())
  return (
    <div className="overflow-x-auto">
      <table className="border-collapse text-sm">
        <caption className="mb-2 text-left text-xs text-muted">Rows: true class. Columns: predicted class.</caption>
        <thead>
          <tr>
            <th />
            {names.map((name) => (
              <th key={name} scope="col" className="max-w-28 px-2 pb-1 text-xs font-medium text-muted">
                {name}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {matrix.map((row, i) => (
            <tr key={names[i]}>
              <th scope="row" className="max-w-40 pr-3 text-right text-xs font-medium text-muted">
                {names[i]}
              </th>
              {row.map((count, j) => (
                <td
                  key={names[j]}
                  className="h-11 w-20 border border-surface text-center font-medium"
                  style={{
                    background: `rgba(18, 113, 104, ${0.06 + 0.7 * (count / max)})`,
                    color: count / max > 0.55 ? '#ffffff' : '#13211e',
                  }}
                >
                  {formatNumber(count)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function Performance({ metrics }) {
  const color = MODALITIES[metrics.model_id].color
  const localLoss = useMemo(() => {
    const byRound = new Map()
    metrics.local_training
      .filter((row) => row.split === 'train')
      .forEach((row) => {
        const entry = byRound.get(row.round_number) || { round: row.round_number }
        entry[row.hospital_id] = row.loss
        byRound.set(row.round_number, entry)
      })
    return [...byRound.values()].sort((a, b) => a.round - b.round)
  }, [metrics])
  const hospitalIds = useMemo(() => [...new Set(metrics.local_training.map((row) => row.hospital_id))].sort(), [metrics])

  if (metrics.series.length === 0) {
    return (
      <EmptyState title="No evaluation results yet" description="Charts appear after the first completed federated round for this model." />
    )
  }
  return (
    <div className="grid gap-6 xl:grid-cols-2">
      <div>
        <h3 className="text-sm font-semibold text-ink">Validation performance by model version</h3>
        <p className="mb-2 mt-0.5 text-xs text-muted">Global model, pooled over the hospitals&rsquo; held-out records.</p>
        <MetricLineChart
          data={metrics.series}
          xKey="version"
          xLabel="Model version"
          percent
          series={[
            { key: 'accuracy', label: 'Accuracy', color: '#586964' },
            { key: 'precision', label: 'Precision', color: '#b0661a', dashed: true },
            { key: 'recall', label: 'Recall', color: '#6a4c9c', dashed: true },
            { key: 'f1', label: 'F1', color },
          ]}
        />
      </div>
      <div>
        <h3 className="text-sm font-semibold text-ink">Validation loss by model version</h3>
        <p className="mb-2 mt-0.5 text-xs text-muted">Mean cross-entropy of the global model. Lower is better.</p>
        <MetricLineChart data={metrics.series} xKey="version" xLabel="Model version" series={[{ key: 'loss', label: 'Loss', color }]} />
      </div>
      <div className="xl:col-span-2">
        <h3 className="text-sm font-semibold text-ink">Training progress at each hospital</h3>
        <p className="mb-2 mt-0.5 text-xs text-muted">
          Training loss in the last local epoch of each round, per hospital. This is measured on training data, so it is not comparable with
          the validation loss above.
        </p>
        <MetricLineChart
          data={localLoss}
          xKey="round"
          xLabel="Round"
          series={hospitalIds.map((id, index) => ({ key: id, label: id, color: HOSPITAL_COLORS[index % HOSPITAL_COLORS.length] }))}
        />
      </div>
    </div>
  )
}

export default function ModelDetail() {
  const { modelId } = useParams()
  const state = useApi(async () => {
    const [model, metrics] = await Promise.all([api.model(modelId), api.modelMetrics(modelId)])
    return { model, metrics }
  }, [modelId])

  return (
    <>
      <Link to="/models" className="mb-4 inline-flex items-center gap-1.5 text-sm font-medium text-brand-700 hover:underline">
        <ArrowLeft className="h-4 w-4" aria-hidden="true" />
        All models
      </Link>
      <AsyncView state={state} what="this model">
        {({ model, metrics }) => (
          <>
            <PageHeader
              title={`${MODALITIES[model.modality].label} model: ${model.target_architecture}`}
              description={model.task.description}
              actions={
                <>
                  <ModalityTag modality={model.modality} />
                  <Badge tone="brand">Version v{model.current_version}</Badge>
                  {model.is_simulated ? <SimulatedTag compact /> : null}
                </>
              }
            />
            <div className="space-y-6">
              {!model.is_target_architecture ? (
                <Note tone="warn" title={`These results are from ${model.architecture}, not ${model.target_architecture}`}>
                  {model.summary}
                </Note>
              ) : null}

              <Card>
                <CardHeader title="What is being measured" />
                <CardBody className="space-y-5">
                  <DefinitionList
                    columns={3}
                    items={[
                      { term: 'Model version shown', value: `v${model.current_version}` },
                      { term: 'Architecture in use', value: `${model.architecture} (${model.backend})` },
                      { term: 'Task', value: model.task.name },
                      {
                        term: 'Dataset',
                        value: metrics.dataset
                          ? `${metrics.dataset.sources.join(', ')}${metrics.dataset.simulated ? ' (simulated)' : ''}`
                          : DASH,
                      },
                      {
                        term: 'Training records',
                        value: metrics.dataset ? formatNumber(metrics.dataset.train_samples) : DASH,
                      },
                      {
                        term: 'Evaluation records',
                        value: metrics.dataset ? formatNumber(metrics.dataset.evaluation_samples) : DASH,
                      },
                    ]}
                  />
                  <div>
                    <p className="text-xs text-muted">Evaluation split</p>
                    <p className="mt-0.5 text-sm text-ink">{metrics.dataset?.evaluation_split || 'Not evaluated yet.'}</p>
                  </div>
                  <div>
                    <p className="text-xs text-muted">Metric definitions</p>
                    <dl className="mt-1.5 grid gap-x-6 gap-y-2 sm:grid-cols-2">
                      {Object.entries(model.task.metric_definitions).map(([key, definition]) => (
                        <div key={key} className="text-sm">
                          <dt className="inline font-semibold text-ink">{METRIC_LABELS[key] || key}: </dt>
                          <dd className="inline text-muted">{definition}</dd>
                        </div>
                      ))}
                    </dl>
                  </div>
                </CardBody>
              </Card>

              <Card>
                <CardHeader
                  title="Performance"
                  description="Metrics for one model and one task. Do not compare them with another modality's model."
                />
                <CardBody>
                  <Performance metrics={metrics} />
                </CardBody>
              </Card>

              {metrics.latest?.per_class ? (
                <Card>
                  <CardHeader title={`Results by class, version v${metrics.latest.version}`} />
                  <CardBody className="grid gap-8 xl:grid-cols-2">
                    <div className="overflow-x-auto">
                      <table className="w-full border-collapse">
                        <thead>
                          <tr>
                            <Th>Class</Th>
                            <Th align="right">Records</Th>
                            <Th align="right">Precision</Th>
                            <Th align="right">Recall</Th>
                            <Th align="right">F1</Th>
                          </tr>
                        </thead>
                        <tbody>
                          {metrics.latest.per_class.map((row) => (
                            <tr key={row.class_name}>
                              <Td>{row.class_name}</Td>
                              <Td align="right">{formatNumber(row.support)}</Td>
                              <Td align="right">{formatPercent(row.precision)}</Td>
                              <Td align="right">{formatPercent(row.recall)}</Td>
                              <Td align="right">{formatPercent(row.f1)}</Td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                    <ConfusionMatrix matrix={metrics.latest.confusion} classNames={model.task.class_names} />
                  </CardBody>
                </Card>
              ) : null}

              <Card>
                <CardHeader
                  title="Model history"
                  description="Weights are kept for the newest versions; older versions keep their record and metrics."
                />
                <div className="overflow-x-auto">
                  <table className="w-full border-collapse">
                    <thead>
                      <tr>
                        <Th>Version</Th>
                        <Th>Status</Th>
                        <Th>Round</Th>
                        <Th>Created</Th>
                        <Th align="right">Accuracy</Th>
                        <Th align="right">F1</Th>
                        <Th align="right">Loss</Th>
                        <Th>Weights hash (SHA-256)</Th>
                      </tr>
                    </thead>
                    <tbody>
                      {model.versions.map((version) => (
                        <tr key={version.version}>
                          <Td className="font-medium">v{version.version}</Td>
                          <Td>
                            <Badge tone={version.status === 'ACTIVE' ? 'ok' : 'neutral'}>
                              {version.status === 'ACTIVE' ? 'Current' : version.round_id ? 'Archived' : 'Untrained'}
                            </Badge>
                          </Td>
                          <Td className="font-mono text-[13px]">{version.round_id || DASH}</Td>
                          <Td>{formatDateTime(version.created_at)}</Td>
                          <Td align="right">{formatMetric('accuracy', version.metrics?.accuracy)}</Td>
                          <Td align="right">{formatMetric('f1', version.metrics?.f1)}</Td>
                          <Td align="right">{formatMetric('loss', version.metrics?.loss)}</Td>
                          <Td className="font-mono text-[13px] text-muted" title={version.weights_sha256}>
                            {shortHash(version.weights_sha256)}
                            {version.weights_available ? '' : ' (weights pruned)'}
                          </Td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </Card>
            </div>
          </>
        )}
      </AsyncView>
    </>
  )
}
