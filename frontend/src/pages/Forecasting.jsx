import { useState } from 'react'
import { ForecastChart } from '../components/charts/ForecastChart'
import { Badge, SimulatedTag } from '../components/ui/Badge'
import { Card, CardBody, CardHeader } from '../components/ui/Card'
import { Field, Note, PageHeader, Select, Td, Th } from '../components/ui/Misc'
import { AsyncView, UnavailableState } from '../components/ui/StateViews'
import { useApi } from '../hooks/useApi'
import { api } from '../services/endpoints'
import { DASH, formatDate, formatNumber } from '../utils/format'

const HORIZONS = [4, 8, 12]

function ForecastResult({ data }) {
  if (!data.available) {
    return (
      <Card>
        <CardBody>
          <UnavailableState
            title={`No forecast for ${data.disease.label} in ${data.region_name}`}
            reason={`${data.reason} A forecast is not shown rather than produced from too little data.`}
          />
        </CardBody>
      </Card>
    )
  }
  const metrics = data.evaluation_metrics
  return (
    <div className="space-y-6">
      <Card>
        <CardHeader
          title={
            <span className="flex flex-wrap items-center gap-2.5">
              {data.disease.label} in {data.region_name}
              <Badge tone="forecast">Forecast / Prediction</Badge>
              {data.data_status.simulated ? <SimulatedTag compact /> : null}
            </span>
          }
          description={`Observed through the week of ${formatDate(data.data_through)}, then ${data.forecast_horizon} weeks ahead.`}
        />
        <CardBody>
          <ForecastChart history={data.history} forecast={data.forecast} />
          <p className="mt-3 text-xs leading-relaxed text-muted">{data.disclaimer}</p>
        </CardBody>
      </Card>

      <div className="grid gap-6 xl:grid-cols-[1fr_1.3fr]">
        <Card>
          <CardHeader title="Model and validation" />
          <CardBody className="space-y-4">
            <dl className="grid grid-cols-3 gap-3">
              <div className="col-span-3 rounded-md border border-line px-3 py-2.5">
                <dt className="text-xs text-muted">Model used</dt>
                <dd className="mt-0.5 text-sm font-semibold text-ink">{data.model_name}</dd>
              </div>
              <div className="rounded-md border border-line px-3 py-2.5">
                <dt className="text-xs text-muted">MAE</dt>
                <dd className="mt-0.5 text-lg font-semibold text-ink">{formatNumber(metrics.mae, 1)}</dd>
              </div>
              <div className="rounded-md border border-line px-3 py-2.5">
                <dt className="text-xs text-muted">RMSE</dt>
                <dd className="mt-0.5 text-lg font-semibold text-ink">{formatNumber(metrics.rmse, 1)}</dd>
              </div>
              <div className="rounded-md border border-line px-3 py-2.5">
                <dt className="text-xs text-muted">Horizon</dt>
                <dd className="mt-0.5 text-lg font-semibold text-ink">{data.forecast_horizon} weeks</dd>
              </div>
            </dl>
            <p className="text-sm leading-relaxed text-muted">
              MAE and RMSE are in cases per week, measured on weeks the model did not see. {metrics.split}
            </p>
            <p className="text-sm leading-relaxed text-muted">Uncertainty interval: {data.uncertainty_interval.method}</p>
            {data.imputed_points > 0 ? (
              <Note tone="warn">
                {data.imputed_points} week{data.imputed_points === 1 ? ' was' : 's were'} missing or suppressed and filled by straight-line
                interpolation before fitting.
              </Note>
            ) : null}
          </CardBody>
        </Card>

        <Card>
          <CardHeader
            title="Models compared"
            description="Each model was refitted week by week on earlier data only and scored on the same held-out weeks. The one with the lowest RMSE is used."
          />
          <div className="overflow-x-auto">
            <table className="w-full border-collapse">
              <thead>
                <tr>
                  <Th>Model</Th>
                  <Th align="right">MAE</Th>
                  <Th align="right">RMSE</Th>
                  <Th />
                </tr>
              </thead>
              <tbody>
                {data.candidates.map((candidate) => (
                  <tr key={candidate.model_name}>
                    <Td>
                      {candidate.model_name}
                      {candidate.error ? <span className="block text-xs text-alert">Could not be fitted: {candidate.error}</span> : null}
                    </Td>
                    <Td align="right">{candidate.mae === null ? DASH : formatNumber(candidate.mae, 1)}</Td>
                    <Td align="right">{candidate.rmse === null ? DASH : formatNumber(candidate.rmse, 1)}</Td>
                    <Td align="right">{candidate.selected ? <Badge tone="ok">Used</Badge> : null}</Td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      </div>

      <Card>
        <CardHeader title="Forecast values" />
        <div className="overflow-x-auto">
          <table className="w-full border-collapse">
            <thead>
              <tr>
                <Th>Week</Th>
                <Th>Starting</Th>
                <Th align="right">Predicted cases</Th>
                <Th align="right">80% interval</Th>
                <Th align="right">95% interval</Th>
              </tr>
            </thead>
            <tbody>
              {data.forecast.map((point) => (
                <tr key={point.week_start}>
                  <Td>{point.label}</Td>
                  <Td>{formatDate(point.week_start)}</Td>
                  <Td align="right" className="font-semibold text-forecast">
                    {formatNumber(point.predicted)}
                  </Td>
                  <Td align="right">
                    {formatNumber(point.lower_80)} to {formatNumber(point.upper_80)}
                  </Td>
                  <Td align="right">
                    {formatNumber(point.lower_95)} to {formatNumber(point.upper_95)}
                  </Td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  )
}

export default function Forecasting() {
  const options = useApi(() => api.analyticsOptions(), [])
  const [regionId, setRegionId] = useState(null)
  const [disease, setDisease] = useState(null)
  const [horizon, setHorizon] = useState(8)

  const activeDisease = disease ?? options.data?.diseases[0]?.id
  // Until a region is chosen the server picks the one with the most complete history.
  const result = useApi(() => api.forecast(regionId ?? undefined, activeDisease, horizon), [regionId, activeDisease, horizon], {
    enabled: options.status === 'success',
  })
  const shownRegion = regionId ?? result.data?.region_id ?? ''

  return (
    <>
      <PageHeader
        title="Forecasting"
        description="A short-range projection of weekly cases for one region and disease, with the model's measured error and an uncertainty interval. A forecast is a prediction, not a count of cases that will happen."
      />
      <AsyncView state={options} what="forecast options">
        {(data) => (
          <>
            <Card className="mb-6">
              <CardBody className="grid gap-4 sm:grid-cols-3 lg:max-w-3xl">
                <Field label="Region" htmlFor="forecast-region">
                  <Select
                    id="forecast-region"
                    value={shownRegion}
                    onChange={setRegionId}
                    options={data.regions.map((r) => ({ value: r.region_id, label: r.name }))}
                  />
                </Field>
                <Field label="Disease" htmlFor="forecast-disease">
                  <Select
                    id="forecast-disease"
                    value={activeDisease}
                    onChange={setDisease}
                    options={data.diseases.map((d) => ({ value: d.id, label: d.label }))}
                  />
                </Field>
                <Field label="Forecast horizon" htmlFor="forecast-horizon">
                  <Select
                    id="forecast-horizon"
                    value={String(horizon)}
                    onChange={(value) => setHorizon(Number(value))}
                    options={HORIZONS.map((h) => ({ value: String(h), label: `${h} weeks` }))}
                  />
                </Field>
              </CardBody>
            </Card>
            <AsyncView state={result} what="the forecast">
              {(forecast) => <ForecastResult data={forecast} />}
            </AsyncView>
          </>
        )}
      </AsyncView>
    </>
  )
}
