import { useState } from 'react'
import { LOWERS, RAISES, ShapBarChart } from '../components/charts/ShapBarChart'
import { SignalChart } from '../components/charts/SignalChart'
import { HeatmapCanvas } from '../components/explainability/HeatmapCanvas'
import { Badge, SimulatedTag } from '../components/ui/Badge'
import { Card, CardBody, CardHeader } from '../components/ui/Card'
import { DefinitionList, Field, Note, PageHeader, Select, Tabs } from '../components/ui/Misc'
import { AsyncView, UnavailableState } from '../components/ui/StateViews'
import { useApi } from '../hooks/useApi'
import { api } from '../services/endpoints'
import { MODALITIES, MODALITY_ORDER } from '../utils/constants'
import { formatDateTime, formatNumber, formatPercent } from '../utils/format'

const METADATA_LABELS = {
  n_background: 'Comparison records',
  n_permutations: 'Feature orderings sampled',
  window_samples: 'Window hidden at a time (samples)',
  stride_samples: 'Step between windows (samples)',
  patch: 'Patch hidden at a time (pixels)',
  stride: 'Step between patches (pixels)',
  evaluations: 'Model runs',
  hospitals_contributing: 'Hospitals contributing',
  records_explained: 'Records explained',
  target_layer: 'Layer explained',
}

const SCOPES = [
  { value: 'individual', label: 'One prediction' },
  { value: 'global', label: 'Model overall' },
]

function Prediction({ prediction, trueClass }) {
  return (
    <div className="rounded-md border border-line bg-canvas px-4 py-3">
      <p className="text-xs text-muted">Model prediction</p>
      <p className="mt-0.5 text-lg font-semibold text-ink">
        {prediction.class_name}{' '}
        <span className="text-base font-medium text-muted">({formatPercent(prediction.probability)} probability)</span>
      </p>
      <ul className="mt-2 flex flex-wrap gap-x-5 gap-y-1 text-xs text-muted">
        {prediction.probabilities.map((item) => (
          <li key={item.class_name}>
            {item.class_name}: <span className="font-medium text-ink">{formatPercent(item.probability)}</span>
          </li>
        ))}
      </ul>
      {trueClass ? (
        <p className="mt-2 text-xs text-muted">
          Label of this synthetic reference case: <span className="font-medium text-ink">{trueClass}</span>
        </p>
      ) : null}
    </div>
  )
}

function Metadata({ explanation }) {
  const items = [
    { term: 'Method', value: explanation.method },
    { term: 'Model version', value: `v${explanation.model_version}` },
    { term: 'Generated', value: formatDateTime(explanation.generated_at) },
  ]
  Object.entries(explanation.metadata || {}).forEach(([key, value]) => {
    if (value === null || value === undefined) return
    const label = METADATA_LABELS[key] || key.replaceAll('_', ' ')
    items.push({ term: label.charAt(0).toUpperCase() + label.slice(1), value: String(value) })
  })
  return (
    <div>
      <p className="mb-2 text-xs font-semibold text-ink">Explanation details</p>
      <DefinitionList items={items} columns={3} />
    </div>
  )
}

function EhrIndividual({ explanation }) {
  const top = explanation.contributions.slice(0, 10)
  const rows = top.map((item) => ({
    name: `${item.label}: ${formatNumber(item.value, Number.isInteger(item.value) ? 0 : 1)} ${item.unit === '0/1' ? '' : item.unit}`.trim(),
    value: item.shap_value,
    color: item.shap_value >= 0 ? RAISES : LOWERS,
  }))
  const raising = explanation.contributions.filter((c) => c.shap_value > 0).slice(0, 3)
  const lowering = explanation.contributions.filter((c) => c.shap_value < 0).slice(0, 3)
  const target = explanation.explained_output.replace('Predicted probability of ', '')
  return (
    <div className="space-y-5">
      <Prediction prediction={explanation.prediction} trueClass={explanation.true_class} />
      <div className="rounded-md border border-line px-4 py-3 text-sm leading-relaxed text-ink">
        <p>
          Across the comparison group the model&rsquo;s average estimate for {target} is{' '}
          <strong>{formatPercent(explanation.base_value)}</strong>. For this case it is{' '}
          <strong>{formatPercent(explanation.additivity.model_output)}</strong>.
        </p>
        {raising.length ? (
          <p className="mt-1.5">
            Pushing the estimate{' '}
            <span className="font-semibold" style={{ color: RAISES }}>
              up
            </span>
            : {raising.map((c) => c.label.toLowerCase()).join(', ')}.
          </p>
        ) : null}
        {lowering.length ? (
          <p className="mt-1.5">
            Pushing it{' '}
            <span className="font-semibold" style={{ color: LOWERS }}>
              down
            </span>
            : {lowering.map((c) => c.label.toLowerCase()).join(', ')}.
          </p>
        ) : null}
      </div>
      <div>
        <h3 className="text-sm font-semibold text-ink">Contribution of each feature (SHAP values)</h3>
        <p className="mb-1 mt-0.5 text-xs text-muted">
          The ten largest contributions. Bars to the right raise this case&rsquo;s predicted probability; bars to the left lower it.
          Together with the average, all 14 contributions add up to the prediction.
        </p>
        <ShapBarChart rows={rows} signed valueLabel="Change in predicted probability (percentage points)" />
      </div>
      <Metadata explanation={explanation} />
    </div>
  )
}

function EhrGlobal({ explanation }) {
  const rows = explanation.features.map((feature) => ({
    name: feature.label,
    value: feature.mean_abs_shap,
    color: feature.direction > 0.15 ? RAISES : feature.direction < -0.15 ? LOWERS : '#84918d',
  }))
  return (
    <div className="space-y-5">
      <p className="text-sm leading-relaxed text-ink">
        Which features the model relies on most, averaged over {explanation.metadata.records_explained} held-out records at{' '}
        {explanation.metadata.hospitals_contributing} hospitals. Each hospital computed its own averages and shared only those.
      </p>
      <div>
        <h3 className="text-sm font-semibold text-ink">Overall feature importance (mean |SHAP|)</h3>
        <ul className="mb-1 mt-1 flex flex-wrap gap-x-5 gap-y-1 text-xs text-muted">
          <li className="flex items-center gap-1.5">
            <span className="h-2.5 w-2.5 rounded-sm" style={{ background: RAISES }} />
            Higher values raise predicted risk
          </li>
          <li className="flex items-center gap-1.5">
            <span className="h-2.5 w-2.5 rounded-sm" style={{ background: LOWERS }} />
            Higher values lower predicted risk
          </li>
          <li className="flex items-center gap-1.5">
            <span className="h-2.5 w-2.5 rounded-sm bg-nodata" />
            No consistent direction
          </li>
        </ul>
        <ShapBarChart rows={rows} signed={false} valueLabel="Average effect on predicted probability (percentage points)" />
      </div>
      <Metadata explanation={explanation} />
    </div>
  )
}

function EcgIndividual({ explanation }) {
  const segment = explanation.most_influential_segment
  return (
    <div className="space-y-5">
      <Prediction prediction={explanation.prediction} trueClass={explanation.true_class} />
      {explanation.importance_has_signal ? (
        <p className="text-sm leading-relaxed text-ink">
          The shaded area shows which part of the beat the prediction depends on. Hiding the stretch from{' '}
          <strong>{segment.start_ms} ms</strong> to <strong>{segment.end_ms} ms</strong> lowers the model&rsquo;s confidence the most.
        </p>
      ) : (
        <Note tone="warn">Hiding any single stretch of this beat left the prediction unchanged, so no part stands out.</Note>
      )}
      <SignalChart signal={explanation.signal} importance={explanation.importance} sampleRateHz={explanation.sample_rate_hz} />
      <Metadata explanation={explanation} />
    </div>
  )
}

function XrayIndividual({ explanation }) {
  const [overlay, setOverlay] = useState(true)
  return (
    <div className="space-y-5">
      <Prediction prediction={explanation.prediction} trueClass={explanation.true_class} />
      <div className="grid gap-6 md:grid-cols-[auto_1fr]">
        <div>
          <HeatmapCanvas imageBase64={explanation.image_png_base64} heatmap={explanation.heatmap} showOverlay={overlay} />
          <label className="mt-2 flex items-center gap-2 text-sm text-ink">
            <input type="checkbox" className="h-4 w-4 accent-[#24489a]" checked={overlay} onChange={(e) => setOverlay(e.target.checked)} />
            Show heat map
          </label>
        </div>
        <div className="space-y-3 text-sm leading-relaxed text-ink">
          <p>
            Warmer, more opaque areas are the parts of the image the prediction depends on most. A heat map shows where the model looked. It
            does not show that the model is right.
          </p>
          {!explanation.heatmap_has_signal ? (
            <Note tone="warn">
              {explanation.method?.startsWith('Grad-CAM')
                ? 'No region of the image raised the score for this prediction, so the heat map is empty. This usually means the model gives the same answer whatever the image shows.'
                : 'No part of the image changed the prediction when hidden, so the heat map is empty.'}
            </Note>
          ) : null}
          <p className="text-xs text-muted">The image is a synthetic geometric phantom used for demonstration. It is not a radiograph.</p>
        </div>
      </div>
      <Metadata explanation={explanation} />
    </div>
  )
}

function ExplanationBody({ data }) {
  const { explanation, modality, scope } = data
  if (modality === 'ehr') return scope === 'global' ? <EhrGlobal explanation={explanation} /> : <EhrIndividual explanation={explanation} />
  if (modality === 'ecg') return <EcgIndividual explanation={explanation} />
  return <XrayIndividual explanation={explanation} />
}

export default function Explainability() {
  const [modality, setModality] = useState('ehr')
  const [scope, setScope] = useState('individual')
  const [caseId, setCaseId] = useState(null)
  const state = useApi(
    () => api.explainability(modality, scope, scope === 'individual' ? (caseId ?? undefined) : undefined),
    [modality, scope, caseId],
  )

  return (
    <>
      <PageHeader
        title="Explainability"
        description="Why a model predicts what it does. Look at one prediction at a time, or at what the model relies on overall."
      />

      <div className="mb-5 flex flex-wrap items-center gap-4">
        <Tabs
          label="Model"
          value={modality}
          onChange={(value) => {
            setModality(value)
            setCaseId(null)
          }}
          options={MODALITY_ORDER.map((m) => ({ value: m, label: MODALITIES[m].label }))}
        />
        <Tabs label="Explanation scope" value={scope} onChange={setScope} options={SCOPES} />
      </div>

      <AsyncView state={state} what="the explanation">
        {(data) => (
          <Card>
            <CardHeader
              title={
                <span className="flex flex-wrap items-center gap-2.5">
                  {MODALITIES[data.modality].label} model
                  <Badge tone="brand">{data.scope === 'global' ? 'Global explanation' : 'Individual prediction'}</Badge>
                  {data.model?.is_simulated ? <SimulatedTag compact /> : null}
                </span>
              }
              description={
                data.model
                  ? `${data.model.architecture} (${data.model.backend}), version v${data.model.version}. Task: ${data.task.name}.`
                  : undefined
              }
              action={
                data.scope === 'individual' && data.cases.length ? (
                  <div className="w-72 max-w-full">
                    <Field label="Reference case" htmlFor="explain-case">
                      <Select
                        id="explain-case"
                        value={caseId ?? data.explanation?.case_id ?? data.cases[0].case_id}
                        onChange={setCaseId}
                        options={data.cases.map((c) => ({ value: c.case_id, label: `${c.title} (${c.true_class})` }))}
                      />
                    </Field>
                  </div>
                ) : null
              }
            />
            <CardBody className="space-y-5">
              {data.available ? (
                <>
                  <ExplanationBody data={data} />
                  {data.scope === 'individual' ? <p className="text-xs leading-relaxed text-muted">{data.reference_note}</p> : null}
                </>
              ) : (
                <UnavailableState title="No explanation available" reason={data.reason} />
              )}
            </CardBody>
          </Card>
        )}
      </AsyncView>
    </>
  )
}
