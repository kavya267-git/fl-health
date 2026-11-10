import { useEffect, useState } from 'react'
import { Badge } from '../components/ui/Badge'
import { Button } from '../components/ui/Button'
import { Card, CardBody, CardHeader } from '../components/ui/Card'
import { Field, Note, PageHeader, Select, Td, Th, inputClass } from '../components/ui/Misc'
import { AsyncView, UnavailableState } from '../components/ui/StateViews'
import { useAuth } from '../context/AuthContext'
import { useApi } from '../hooks/useApi'
import { toApiError } from '../services/api'
import { api } from '../services/endpoints'
import { formatDate, formatDateTime, formatNumber } from '../utils/format'

const beds = (value) => formatNumber(Math.round(value))
const percent = (value) => `${formatNumber(value * 100, value < 0.1 ? 1 : 0)}%`
const weeksLabel = (g) => (g.first_week === g.last_week ? `Week ${g.first_week}` : `Weeks ${g.first_week}–${g.last_week}`)
const range = (low, high) => (Math.round(low) === Math.round(high) ? beds(high) : `${beds(low)}–${beds(high)}`)

/** One group of weeks in a plain sentence, e.g. "Weeks 2–3: dengue patients may need 34–51 of your 40 beds." */
export function groupSentence(group, diseaseLabel, totalBeds) {
  const disease = diseaseLabel.toLowerCase()
  const need = `${range(group.total_low, group.total_high)} of your ${beds(totalBeds)} beds`
  return group.over_capacity
    ? `${weeksLabel(group)}: if the rest of the hospital stays as busy as today, with the expected ${disease} patients, you may need ${need}. That could be more than you have.`
    : `${weeksLabel(group)}: if the rest of the hospital stays as busy as today, with the expected ${disease} patients, you may need ${need}.`
}

function CapacityForm({ capacity, onSaved }) {
  const [values, setValues] = useState({
    total_beds: capacity?.total_beds ?? '',
    icu_beds: capacity?.icu_beds ?? '',
    occupancy_percent: capacity?.occupancy_percent ?? '',
  })
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const set = (key) => (event) => setValues((current) => ({ ...current, [key]: event.target.value }))
  const complete = ['total_beds', 'icu_beds', 'occupancy_percent'].every((key) => String(values[key]).trim() !== '')

  async function save(event) {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await api.setCapacity({
        total_beds: Number(values.total_beds),
        icu_beds: Number(values.icu_beds),
        occupancy_percent: Number(values.occupancy_percent),
      })
      await onSaved()
    } catch (failure) {
      setError(toApiError(failure).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <Card>
      <CardHeader
        title="Your hospital's beds"
        description={capacity ? `Last updated ${formatDateTime(capacity.entered_at)} by ${capacity.entered_by}.` : 'Not entered yet.'}
      />
      <CardBody>
        <form className="grid gap-4 sm:grid-cols-3" onSubmit={save}>
          <Field label="Total beds" htmlFor="total-beds">
            <input id="total-beds" type="number" min="1" className={inputClass} value={values.total_beds} onChange={set('total_beds')} />
          </Field>
          <Field label="ICU beds" htmlFor="icu-beds">
            <input id="icu-beds" type="number" min="0" className={inputClass} value={values.icu_beds} onChange={set('icu_beds')} />
          </Field>
          <Field label="Beds in use now (%)" htmlFor="occupancy">
            <input
              id="occupancy"
              type="number"
              min="0"
              max="100"
              step="0.1"
              className={inputClass}
              value={values.occupancy_percent}
              onChange={set('occupancy_percent')}
            />
          </Field>
          <div className="sm:col-span-3 flex items-center gap-3">
            <Button type="submit" variant="primary" loading={busy} disabled={!complete}>
              Save
            </Button>
            {error ? <p className="text-sm text-alert">{error}</p> : null}
          </div>
        </form>
      </CardBody>
    </Card>
  )
}

function AssumptionsCard({ assumptions, editable, onSaved }) {
  const [drafts, setDrafts] = useState({})
  const [error, setError] = useState(null)
  const anyDefault = assumptions.some((a) => a.is_default)

  async function save(disease) {
    setError(null)
    const draft = drafts[disease]
    try {
      await api.setPlanningAssumptions(disease, {
        admission_rate: Number(draft.admission_rate) / 100,
        icu_share: Number(draft.icu_share) / 100,
        length_of_stay_days: Number(draft.length_of_stay_days),
      })
      setDrafts((current) => ({ ...current, [disease]: undefined }))
      await onSaved()
    } catch (failure) {
      setError(toApiError(failure).message)
    }
  }

  return (
    <Card>
      <CardHeader
        title="Assumptions behind the estimate"
        description={editable ? 'Set for every hospital. Replace the defaults with local figures.' : 'Set by an administrator.'}
      />
      <CardBody className="space-y-3">
        {anyDefault ? (
          <p data-testid="assumed-label" className="rounded-md border border-warn/40 bg-warn-soft px-3 py-2 text-sm font-semibold text-warn-ink">
            Assumed values, replace with local figures
          </p>
        ) : null}
        {error ? <Note tone="alert">{error}</Note> : null}
        <div className="overflow-x-auto">
          <table className="w-full border-collapse">
            <thead>
              <tr>
                <Th>Disease</Th>
                <Th align="right">Admitted</Th>
                <Th align="right">Of those, ICU</Th>
                <Th align="right">Stay</Th>
                {editable ? <Th /> : null}
              </tr>
            </thead>
            <tbody>
              {assumptions.map((a) => {
                const draft = drafts[a.disease]
                return (
                  <tr key={a.disease}>
                    <Td>
                      <p className="font-medium">{a.disease_label}</p>
                      <p className="text-xs text-muted">{a.is_default ? 'Assumed value' : `Set by ${a.updated_by}`}</p>
                    </Td>
                    {draft ? (
                      ['admission_rate', 'icu_share', 'length_of_stay_days'].map((key) => (
                        <Td key={key} align="right">
                          <input
                            aria-label={`${a.disease_label} ${key.replaceAll('_', ' ')}`}
                            type="number"
                            step="0.1"
                            className={`${inputClass} w-24 text-right`}
                            value={draft[key]}
                            onChange={(e) => setDrafts((c) => ({ ...c, [a.disease]: { ...c[a.disease], [key]: e.target.value } }))}
                          />
                        </Td>
                      ))
                    ) : (
                      <>
                        <Td align="right">{percent(a.admission_rate)}</Td>
                        <Td align="right">{percent(a.icu_share)}</Td>
                        <Td align="right">{formatNumber(a.length_of_stay_days, 1)} days</Td>
                      </>
                    )}
                    {editable ? (
                      <Td align="right">
                        {draft ? (
                          <Button size="sm" variant="primary" onClick={() => save(a.disease)}>
                            Save
                          </Button>
                        ) : (
                          <Button
                            size="sm"
                            variant="ghost"
                            onClick={() =>
                              setDrafts((c) => ({
                                ...c,
                                [a.disease]: {
                                  admission_rate: a.admission_rate * 100,
                                  icu_share: a.icu_share * 100,
                                  length_of_stay_days: a.length_of_stay_days,
                                },
                              }))
                            }
                          >
                            Edit
                          </Button>
                        )}
                      </Td>
                    ) : null}
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
        {editable ? <p className="text-xs text-muted">Percentages: cases admitted and admitted who need ICU; stay in days.</p> : null}
      </CardBody>
    </Card>
  )
}

function DiseaseProjection({ block, capacity }) {
  if (!block.available) {
    return (
      <Card>
        <CardHeader title={block.disease.label} />
        <CardBody>
          <UnavailableState
            title="No estimate for this disease"
            reason={
              block.missing_regions.length
                ? `No usable forecast for the areas this hospital serves: ${block.missing_regions.map((m) => `${m.region_name} (${m.reason})`).join('; ')}.`
                : 'This hospital has not reported this disease.'
            }
          />
        </CardBody>
      </Card>
    )
  }
  const shares = block.regions.map((r) => `${r.region_name} ${percent(r.share)}`).join(', ')
  return (
    <Card>
      <CardHeader title={block.disease.label} description={`Your share of cases (last 8 weeks): ${shares}.`} />
      <CardBody className="space-y-3">
        {block.groups.map((group) => (
          <p
            key={group.first_week}
            className={group.over_capacity ? 'rounded-md border border-alert/40 bg-alert-soft px-3 py-2 font-semibold text-ink' : 'text-ink'}
          >
            {groupSentence(group, block.disease.label, capacity.total_beds)}
          </p>
        ))}
        <div className="overflow-x-auto">
          <table className="w-full border-collapse">
            <thead>
              <tr>
                <Th>Week</Th>
                <Th align="right">New admissions</Th>
                <Th align="right">{block.disease.label} beds</Th>
                <Th align="right">All beds needed (of {beds(capacity.total_beds)})</Th>
                <Th align="right">ICU beds needed (of {beds(capacity.icu_beds)})</Th>
              </tr>
            </thead>
            <tbody>
              {block.weeks.map((week) => (
                <tr key={week.horizon} className={week.over_capacity ? 'bg-alert-soft' : undefined} data-over={week.over_capacity}>
                  <Td>
                    Week {week.horizon} <span className="text-xs text-muted">({formatDate(week.week_start)})</span>
                  </Td>
                  <Td align="right">{range(week.admissions_low, week.admissions_high)}</Td>
                  <Td align="right">{range(week.beds_low, week.beds_high)}</Td>
                  <Td align="right" className={week.over_capacity ? 'font-semibold text-alert' : undefined}>
                    {range(week.total_beds_low, week.total_beds_high)}
                  </Td>
                  <Td align="right" className={week.icu_over_capacity ? 'font-semibold text-alert' : undefined}>
                    up to {beds(week.icu_total_high)}
                  </Td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {block.missing_regions.length ? (
          <p className="text-xs text-muted">
            Not included (no usable forecast or share): {block.missing_regions.map((m) => `${m.region_name}, ${m.reason}`).join('; ')}.
          </p>
        ) : null}
      </CardBody>
    </Card>
  )
}

function Projection({ plan, onCapacitySaved, isManager }) {
  return (
    <div className="space-y-6">
      {plan.data_status.watermark ? (
        <p className="rounded-md border-2 border-alert/50 bg-alert-soft px-4 py-2 text-center text-sm font-bold uppercase tracking-wider text-alert">
          {plan.data_status.watermark}
        </p>
      ) : null}
      <Note title="A planning estimate, not a prediction of who will be admitted">
        Built from the regional forecast, your hospital&rsquo;s recent share of cases and the assumptions shown here. It assumes the rest of the
        hospital stays as busy as today. Today&rsquo;s occupancy already includes some patients with these diseases, so the projection
        leans high. The low&ndash;high values are a range from the forecast&rsquo;s likely ranges, added up over regions: wider than an 80%
        interval, but each likely range is itself often too narrow.
      </Note>
      <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_24rem]">
        <div className="min-w-0 space-y-6">
          {!plan.available ? (
            <Card>
              <CardBody>
                <UnavailableState title="No estimate yet" reason={plan.reason} />
              </CardBody>
            </Card>
          ) : (
            <>
              {plan.all_diseases ? (
                <Card>
                  <CardHeader title="All diseases together" description="The rest of the hospital as busy as today, plus the expected patients of every disease below." />
                  <CardBody className="flex flex-wrap gap-3">
                    {plan.all_diseases.map((week) => (
                      <div key={week.horizon} className="min-w-[8rem] rounded-md border border-line px-3 py-2">
                        <p className="text-xs text-muted">Week {week.horizon}</p>
                        <p className={`text-lg font-semibold ${week.over_capacity ? 'text-alert' : 'text-ink'}`}>
                          {range(week.total_low, week.total_high)} / {beds(plan.capacity.total_beds)}
                        </p>
                        {week.over_capacity ? <Badge tone="alert">May exceed beds</Badge> : null}
                      </div>
                    ))}
                  </CardBody>
                </Card>
              ) : null}
              {plan.diseases.map((block) => (
                <DiseaseProjection key={block.disease.id} block={block} capacity={plan.capacity} />
              ))}
              <p className="text-xs text-muted">
                Forecast data up to the week starting {formatDate(plan.forecast.data_through)}; computed {formatDateTime(plan.forecast.computed_at)}.
                Week 1 is the first week after that.
              </p>
            </>
          )}
        </div>
        <div className="min-w-0 space-y-6">
          {isManager ? <CapacityForm key={plan.capacity?.id ?? 'none'} capacity={plan.capacity} onSaved={onCapacitySaved} /> : null}
          <AssumptionsCard assumptions={plan.assumptions} editable={false} onSaved={onCapacitySaved} />
        </div>
      </div>
    </div>
  )
}

/** Administrators: choose a hospital to look at, and edit the disease assumptions every hospital uses. */
function AdminPlanning() {
  const hospitals = useApi(() => api.hospitals(), [])
  const [hospitalId, setHospitalId] = useState(null)
  useEffect(() => {
    if (!hospitalId && hospitals.status === 'success' && hospitals.data.length) setHospitalId(hospitals.data[0].id)
  }, [hospitals, hospitalId])
  const assumptions = useApi(() => api.planningAssumptions(), [])
  const plan = useApi(() => api.planning(hospitalId), [hospitalId], { enabled: Boolean(hospitalId) })

  return (
    <div className="space-y-6">
      <AsyncView state={assumptions} what="the assumptions">
        {(rows) => <AssumptionsCard assumptions={rows} editable onSaved={() => Promise.all([assumptions.reload(), plan.reload({ silent: true })])} />}
      </AsyncView>
      <AsyncView state={hospitals} what="hospitals">
        {(list) => (
          <Card>
            <CardBody className="max-w-sm">
              <Field label="Hospital" htmlFor="planning-hospital">
                <Select id="planning-hospital" value={hospitalId || ''} onChange={setHospitalId} options={list.map((h) => ({ value: h.id, label: h.name }))} />
              </Field>
            </CardBody>
          </Card>
        )}
      </AsyncView>
      {hospitalId ? (
        <AsyncView state={plan} what="the resource plan">
          {(data) => <Projection plan={data} isManager={false} onCapacitySaved={() => plan.reload({ silent: true })} />}
        </AsyncView>
      ) : null}
    </div>
  )
}

export default function ResourcePlanning() {
  const { user } = useAuth()
  const isManager = user?.role === 'hospital_manager'
  const plan = useApi(() => api.planning(), [], { enabled: isManager })

  return (
    <>
      <PageHeader
        title="Resource planning"
        description="How many beds the coming weeks may need, from the regional forecast and your hospital's share of cases. A planning estimate."
        actions={<Badge tone="brand">Planning estimate</Badge>}
      />
      {isManager ? (
        <AsyncView state={plan} what="the resource plan">
          {(data) => <Projection plan={data} isManager onCapacitySaved={() => plan.reload({ silent: true })} />}
        </AsyncView>
      ) : (
        <AdminPlanning />
      )}
    </>
  )
}
