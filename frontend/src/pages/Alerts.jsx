import { useState } from 'react'
import { Badge, SimulatedTag } from '../components/ui/Badge'
import { Button } from '../components/ui/Button'
import { Card } from '../components/ui/Card'
import { Field, Note, PageHeader, Select, inputClass } from '../components/ui/Misc'
import { AsyncView, EmptyState } from '../components/ui/StateViews'
import { useAuth } from '../context/AuthContext'
import { useApi } from '../hooks/useApi'
import { currentLanguage, translate } from '../i18n'
import { toApiError } from '../services/api'
import { api } from '../services/endpoints'
import { formatDateTime, formatNumber } from '../utils/format'

const STATE_TONES = { OPEN: 'alert', ACKNOWLEDGED: 'warn', CLOSED: 'neutral' }
const OUTCOMES = ['CONFIRMED', 'NOT_CONFIRMED', 'REPORTING_ARTEFACT']
/** Who may act on alerts; the server enforces the same rule (docs/permissions.md, alerts_manage). */
const CAN_MANAGE = ['admin', 'health_officer']

function OutcomeForm({ alert, t, onSaved }) {
  const [outcome, setOutcome] = useState('')
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  async function save(event) {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await api.recordAlertOutcome(alert.id, outcome, note.trim())
      await onSaved()
    } catch (failure) {
      setError(toApiError(failure).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <form className="mt-3 grid gap-3 rounded-md border border-line bg-canvas p-3 sm:grid-cols-[14rem_1fr_auto] sm:items-end" onSubmit={save}>
      <Field label={t('alerts.outcomeLabel')} htmlFor={`outcome-${alert.id}`}>
        <Select
          id={`outcome-${alert.id}`}
          value={outcome}
          onChange={setOutcome}
          options={[{ value: '', label: '…' }, ...OUTCOMES.map((o) => ({ value: o, label: t(`outcome.${o}`) }))]}
        />
      </Field>
      <Field label={t('alerts.noteLabel')} htmlFor={`note-${alert.id}`}>
        <input id={`note-${alert.id}`} className={inputClass} maxLength={1000} value={note} onChange={(e) => setNote(e.target.value)} />
      </Field>
      <Button type="submit" variant="primary" loading={busy} disabled={!outcome || !note.trim()}>
        {t('alerts.save')}
      </Button>
      {error ? <p className="text-sm text-alert sm:col-span-3">{error}</p> : null}
    </form>
  )
}

function AlertItem({ alert, t, canManage, onChanged }) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const values = {
    disease: alert.disease_label,
    region: alert.region_name,
    week: alert.week_label,
    count: formatNumber(alert.case_count),
    usual: formatNumber(alert.usual_level),
  }

  async function acknowledge() {
    setBusy(true)
    setError(null)
    try {
      await api.acknowledgeAlert(alert.id)
      await onChanged()
    } catch (failure) {
      setError(toApiError(failure).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <li className="px-5 py-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="font-medium text-ink">
            {alert.case_count !== null ? t('alerts.raised', values) : t('alerts.raisedNoCount', values)}
          </p>
          {alert.acknowledged_at ? (
            <p className="mt-0.5 text-[13px] text-muted">
              {t('alerts.acknowledgedBy', { who: alert.acknowledged_by, when: formatDateTime(alert.acknowledged_at) })}
            </p>
          ) : null}
          {alert.state === 'CLOSED' ? (
            <p className="mt-0.5 text-[13px] text-ink">
              {t('alerts.closedBy', {
                outcome: t(`outcome.${alert.outcome}`),
                who: alert.outcome_by,
                when: formatDateTime(alert.outcome_at),
                note: alert.outcome_note,
              })}
            </p>
          ) : null}
        </div>
        <div className="flex items-center gap-2">
          {alert.is_simulated ? <SimulatedTag compact /> : null}
          <Badge tone={STATE_TONES[alert.state]}>{t(`alerts.state.${alert.state}`)}</Badge>
          {canManage && alert.state === 'OPEN' ? (
            <Button size="sm" variant="primary" loading={busy} onClick={acknowledge}>
              {t('alerts.acknowledge')}
            </Button>
          ) : null}
        </div>
      </div>
      {error ? <p className="mt-2 text-sm text-alert">{error}</p> : null}
      {canManage && alert.state === 'ACKNOWLEDGED' ? <OutcomeForm alert={alert} t={t} onSaved={onChanged} /> : null}
    </li>
  )
}

export default function Alerts() {
  const { user } = useAuth()
  const language = currentLanguage()
  const t = (key, values) => translate(language, key, values)
  const [filter, setFilter] = useState('OPEN')
  const state = useApi(() => api.alerts(filter === 'ALL' ? null : filter), [filter], { isEmpty: (rows) => rows.length === 0 })
  const canManage = CAN_MANAGE.includes(user?.role)
  const filters = [
    ['OPEN', t('alerts.filterOpen')],
    ['ACKNOWLEDGED', t('alerts.filterAcknowledged')],
    ['CLOSED', t('alerts.filterClosed')],
    ['ALL', t('alerts.filterAll')],
  ]

  return (
    <>
      <PageHeader title={t('alerts.title')} description={t('alerts.description')} />
      <div role="tablist" aria-label={t('alerts.title')} className="mb-4 flex flex-wrap gap-2">
        {filters.map(([value, label]) => (
          <Button key={value} size="sm" role="tab" aria-selected={filter === value} variant={filter === value ? 'primary' : 'secondary'} onClick={() => setFilter(value)}>
            {label}
          </Button>
        ))}
      </div>
      <Note className="mb-4">{t('situation.disclaimer')}</Note>
      <Card>
        <AsyncView state={state} what="alerts" empty={<EmptyState title={t('alerts.empty')} />}>
          {(alerts) => (
            <ul className="divide-y divide-line">
              {alerts.map((alert) => (
                <AlertItem key={alert.id} alert={alert} t={t} canManage={canManage} onChanged={() => state.reload({ silent: true })} />
              ))}
            </ul>
          )}
        </AsyncView>
      </Card>
    </>
  )
}
