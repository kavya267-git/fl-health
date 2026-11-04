import { Activity, Building2, Layers, Stethoscope } from 'lucide-react'
import { Link } from 'react-router-dom'
import { HotspotStatusBadge, ModalityTag, RoundStatusBadge, SimulatedTag } from '../components/ui/Badge'
import { Card, CardBody, CardHeader } from '../components/ui/Card'
import { PageHeader, Stat } from '../components/ui/Misc'
import { AsyncView, EmptyState, UnavailableState } from '../components/ui/StateViews'
import { useApi } from '../hooks/useApi'
import { usePolling } from '../hooks/usePolling'
import { api } from '../services/endpoints'
import { AUDIT_ACTION_LABELS, LIKELY_RANGE_NOTE, METRIC_LABELS, MODALITIES, availabilityLabel } from '../utils/constants'
import { DASH, formatMetric, formatNumber, formatTime, timeAgo } from '../utils/format'

const linkClass = 'text-sm font-medium text-brand-700 hover:underline'

function ModelPerformance({ models }) {
  return (
    <ul className="mt-2 space-y-1">
      {models.map((model) => {
        const metric = model.primary_metric
        const value = model.available && model.metrics ? model.metrics[metric] : null
        return (
          <li key={model.modality} className="flex items-baseline justify-between gap-3 text-sm">
            <span className="text-muted">
              {MODALITIES[model.modality].label} {METRIC_LABELS[metric] || ''}
            </span>
            <span className="font-semibold text-ink">{value === null ? DASH : formatMetric(metric, value)}</span>
          </li>
        )
      })}
    </ul>
  )
}

function HospitalParticipation({ hospitals }) {
  return (
    <Card>
      <CardHeader
        title="Hospital participation"
        action={
          <Link className={linkClass} to="/hospitals">
            All hospitals
          </Link>
        }
      />
      <ul className="divide-y divide-line">
        {hospitals.map((hospital) => (
          <li key={hospital.id} className="flex items-center justify-between gap-3 px-5 py-3">
            <div className="flex min-w-0 items-center gap-3">
              <span
                className={`h-2.5 w-2.5 shrink-0 rounded-full ${hospital.online ? 'bg-ok' : 'bg-nodata'}`}
                title={availabilityLabel(hospital)}
                aria-hidden="true"
              />
              <div className="min-w-0">
                <Link to={`/hospitals/${hospital.id}`} className="block truncate text-sm font-medium text-ink hover:underline">
                  {hospital.name}
                </Link>
                <p className="text-xs text-muted">
                  {availabilityLabel(hospital)}, {hospital.rounds_completed} round
                  {hospital.rounds_completed === 1 ? '' : 's'} completed
                </p>
              </div>
            </div>
            <p className="shrink-0 text-xs text-muted">
              {hospital.current_round ? `In ${hospital.current_round.id}` : timeAgo(hospital.last_activity_at)}
            </p>
          </li>
        ))}
      </ul>
    </Card>
  )
}

function RoundSummary({ active, recent }) {
  const rounds = active.length ? active : recent.slice(0, 3)
  return (
    <Card>
      <CardHeader
        title={active.length ? 'Current federated round' : 'Latest federated rounds'}
        action={
          <Link className={linkClass} to="/federated">
            Open Federated Learning
          </Link>
        }
      />
      {rounds.length === 0 ? (
        <EmptyState
          title="No rounds have been run"
          description="Start a round on the Federated Learning page to train the first global model."
          illustration
        />
      ) : (
        <ul className="divide-y divide-line">
          {rounds.map((round) => (
            <li key={round.id} className="flex flex-wrap items-center justify-between gap-3 px-5 py-3">
              <div className="flex items-center gap-3">
                <ModalityTag modality={round.modality} />
                <div>
                  <p className="font-mono text-[13px] text-ink">{round.id}</p>
                  <p className="text-xs text-muted">
                    {round.num_participants} hospitals, started {timeAgo(round.started_at).toLowerCase()}
                  </p>
                </div>
              </div>
              <div className="flex items-center gap-3">
                {round.metrics ? (
                  <span className="text-sm text-muted">
                    {METRIC_LABELS[round.primary_metric]}{' '}
                    <span className="font-semibold text-ink">
                      {formatMetric(round.primary_metric, round.metrics[round.primary_metric])}
                    </span>
                  </span>
                ) : null}
                <RoundStatusBadge status={round.status} />
              </div>
            </li>
          ))}
        </ul>
      )}
    </Card>
  )
}

function ModelStatus({ models }) {
  return (
    <Card>
      <CardHeader
        title="Model status"
        action={
          <Link className={linkClass} to="/models">
            Model registry
          </Link>
        }
      />
      <ul className="divide-y divide-line">
        {models.map((model) => (
          <li key={model.modality} className="px-5 py-3">
            {model.available ? (
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div className="flex items-center gap-3">
                  <ModalityTag modality={model.modality} />
                  <div>
                    <p className="text-sm font-medium text-ink">{model.architecture}</p>
                    <p className="text-xs text-muted">
                      {model.training_status === 'TRAINED' ? `Version ${model.current_version}` : 'Not trained yet'}
                      {model.is_target_architecture ? '' : `, stand-in for ${model.target_architecture}`}
                    </p>
                  </div>
                </div>
                <dl className="flex gap-5 text-right">
                  {['accuracy', 'f1'].map((key) => (
                    <div key={key}>
                      <dt className="text-xs text-muted">{METRIC_LABELS[key]}</dt>
                      <dd className="text-sm font-semibold text-ink">{model.metrics ? formatMetric(key, model.metrics[key]) : DASH}</dd>
                    </div>
                  ))}
                </dl>
              </div>
            ) : (
              <div className="flex items-start gap-3">
                <ModalityTag modality={model.modality} />
                <p className="text-sm text-muted">Unavailable: {model.reason}</p>
              </div>
            )}
          </li>
        ))}
      </ul>
    </Card>
  )
}

function SurveillanceSummary({ surveillance }) {
  return (
    <Card>
      <CardHeader
        title="Surveillance summary"
        description={surveillance.available ? `Week ${surveillance.diseases[0]?.time_period.label}` : undefined}
        action={
          <Link className={linkClass} to="/surveillance">
            Open map
          </Link>
        }
      />
      {surveillance.available ? (
        <>
          <ul className="divide-y divide-line">
            {surveillance.diseases.map((entry) => (
              <li key={entry.disease.id} className="px-5 py-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <p className="text-sm font-medium text-ink">{entry.disease.label}</p>
                  <p className="text-xs text-muted">
                    {formatNumber(entry.reported_cases)} reported cases in {entry.regions_with_complete_counts} of {entry.regions_total}{' '}
                    regions
                  </p>
                </div>
                <div className="mt-2 flex flex-wrap gap-2">
                  {entry.flagged_regions.length === 0 ? (
                    <span className="text-xs text-muted">No region above its recent baseline.</span>
                  ) : (
                    entry.flagged_regions.map((region) => (
                      <span key={region.region_id} className="inline-flex items-center gap-1.5 text-xs text-ink">
                        <HotspotStatusBadge status={region.status} />
                        {region.region_name}
                      </span>
                    ))
                  )}
                </div>
              </li>
            ))}
          </ul>
          <p className="border-t border-line px-5 py-3 text-xs leading-relaxed text-muted">{surveillance.disclaimer}</p>
        </>
      ) : (
        <CardBody>
          <UnavailableState title="Surveillance data is not available" reason={surveillance.reason} />
        </CardBody>
      )}
    </Card>
  )
}

function ForecastSummary({ forecast }) {
  return (
    <Card>
      <CardHeader
        title="Forecast summary"
        description={forecast.available ? `${forecast.disease.label} in ${forecast.region_name}` : undefined}
        action={
          <Link className={linkClass} to="/forecasting">
            Open forecasting
          </Link>
        }
      />
      <CardBody>
        {forecast.available ? (
          <>
            <div className="grid grid-cols-3 gap-4">
              <div>
                <p className="text-xs text-muted">Last observed week</p>
                <p className="mt-1 text-xl font-semibold text-ink">{formatNumber(forecast.last_observed)}</p>
              </div>
              <div>
                <p className="text-xs text-muted">Predicted next week</p>
                <p className="mt-1 text-xl font-semibold text-forecast">{formatNumber(forecast.next_week.predicted)}</p>
                <p className="text-xs text-muted">
                  95% likely range {formatNumber(forecast.next_week.lower_95)}&ndash;{formatNumber(forecast.next_week.upper_95)}
                </p>
              </div>
              <div>
                <p className="text-xs text-muted">Predicted in {forecast.horizon} weeks</p>
                <p className="mt-1 text-xl font-semibold text-forecast">{formatNumber(forecast.final_week.predicted)}</p>
                <p className="text-xs text-muted">
                  95% likely range {formatNumber(forecast.final_week.lower_95)}&ndash;{formatNumber(forecast.final_week.upper_95)}
                </p>
              </div>
            </div>
            <p className="mt-4 text-xs leading-relaxed text-muted">
              {LIKELY_RANGE_NOTE}. {forecast.model_name}. Hold-out error: MAE {formatNumber(forecast.evaluation_metrics.mae, 1)}, RMSE{' '}
              {formatNumber(forecast.evaluation_metrics.rmse, 1)} cases per week. Forecast / prediction, not confirmed future cases.
            </p>
          </>
        ) : (
          <UnavailableState title="No forecast available" reason={forecast.reason} />
        )}
      </CardBody>
    </Card>
  )
}

function RecentActivity({ entries }) {
  return (
    <Card>
      <CardHeader
        title="Recent audit activity"
        action={
          <Link className={linkClass} to="/audit">
            Audit log
          </Link>
        }
      />
      {entries.length === 0 ? (
        <EmptyState title="No activity recorded yet" />
      ) : (
        <ul className="divide-y divide-line">
          {entries.map((entry) => (
            <li key={entry.id} className="flex items-center justify-between gap-3 px-5 py-2.5">
              <div className="min-w-0">
                <p className="truncate text-sm text-ink">{AUDIT_ACTION_LABELS[entry.action] || entry.action}</p>
                <p className="truncate text-xs text-muted">
                  {entry.actor}
                  {entry.round_id ? `, ${entry.round_id}` : ''}
                </p>
              </div>
              <div className="shrink-0 text-right">
                <p className="text-xs text-muted">{formatTime(entry.timestamp)}</p>
                {entry.status !== 'SUCCESS' ? <p className="text-xs font-medium text-alert">{entry.status}</p> : null}
              </div>
            </li>
          ))}
        </ul>
      )}
    </Card>
  )
}

export default function Dashboard() {
  const state = useApi(() => api.overview(), [])
  const hasActiveRound = state.status === 'success' && state.data.active_rounds.length > 0
  usePolling(() => state.reload({ silent: true }), 3000, hasActiveRound)

  return (
    <>
      <PageHeader
        title="Dashboard"
        description="The state of the federation: who is taking part, how the shared models are doing, and what the aggregated surveillance data shows."
      />
      <AsyncView state={state} what="the dashboard summary">
        {(data) => {
          const { kpis } = data
          return (
            <div className="space-y-6">
              {data.data_status.simulated ? (
                <div className="flex flex-wrap items-center gap-3 text-sm text-muted">
                  <SimulatedTag label={data.data_status.label} />
                  <span>Everything on this page is computed from simulated hospitals and simulated records.</span>
                </div>
              ) : null}

              <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
                <Stat
                  label="Participating hospitals"
                  value={kpis.participating_hospitals}
                  detail={`${kpis.hospitals_online} online now`}
                  icon={Building2}
                />
                <Stat label="Healthcare modalities" value={kpis.modalities} detail="EHR, ECG and X-ray" icon={Stethoscope} />
                <Stat
                  label="FL rounds"
                  value={kpis.fl_rounds_total === 0 ? DASH : kpis.fl_rounds_completed}
                  detail={
                    kpis.fl_rounds_total === 0
                      ? 'No rounds run yet'
                      : `completed${kpis.fl_rounds_failed ? `, ${kpis.fl_rounds_failed} failed` : ''}`
                  }
                  icon={Activity}
                />
                <div className="rounded-lg border border-line bg-surface px-5 py-4 shadow-card">
                  <div className="flex items-center justify-between gap-3">
                    <p className="text-sm text-muted">Global model performance</p>
                    <Layers className="h-4 w-4 text-faint" aria-hidden="true" />
                  </div>
                  <ModelPerformance models={data.models} />
                  <p className="mt-2 text-xs leading-snug text-muted">
                    {kpis.models_trained === 0
                      ? 'Shown after the first completed round.'
                      : 'Each model has its own task; scores are not comparable across modalities.'}
                  </p>
                </div>
              </div>

              <div className="grid gap-6 xl:grid-cols-2">
                <RoundSummary active={data.active_rounds} recent={data.recent_rounds} />
                <ModelStatus models={data.models} />
                <HospitalParticipation hospitals={data.hospitals} />
                {/* The server sends audit items only to roles that may read the audit log. */}
                {Array.isArray(data.recent_activity) ? <RecentActivity entries={data.recent_activity} /> : null}
                <SurveillanceSummary surveillance={data.surveillance} />
                <ForecastSummary forecast={data.forecast} />
              </div>
            </div>
          )
        }}
      </AsyncView>
    </>
  )
}
