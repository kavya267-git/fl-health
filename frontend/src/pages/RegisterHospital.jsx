import { CircleAlert, CircleCheck } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Logo } from '../components/layout/Logo'
import { Button } from '../components/ui/Button'
import { Field, Select, inputClass } from '../components/ui/Misc'
import { toApiError } from '../services/api'
import { api } from '../services/endpoints'
import { MIN_PASSWORD_LENGTH } from '../utils/constants'

const KINDS = [
  { id: 'ehr', label: 'EHR', hint: 'structured admission records' },
  { id: 'ecg', label: 'ECG', hint: 'single heartbeats' },
  { id: 'xray', label: 'X-ray', hint: 'frontal chest images' },
]
export const CONFIRMATION = 'I confirm we will not upload patient data; training runs on our own machine.'

/** Public page: no sign-in. Creates a request that an administrator approves or rejects. */
export default function RegisterHospital() {
  const [regions, setRegions] = useState([])
  const [regionError, setRegionError] = useState(null)
  const [form, setForm] = useState({
    hospital_name: '',
    region_id: '',
    contact_name: '',
    contact_email: '',
    password: '',
    password_confirm: '',
  })
  const [kinds, setKinds] = useState({})
  const [confirmed, setConfirmed] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [receipt, setReceipt] = useState(null)

  useEffect(() => {
    api
      .registrationRegions()
      .then(setRegions)
      .catch((failure) => setRegionError(toApiError(failure).message))
  }, [])

  const set = (key) => (event) => setForm((f) => ({ ...f, [key]: event.target.value }))
  const chosen = KINDS.filter((k) => kinds[k.id] !== undefined)

  function toggleKind(id) {
    setKinds((current) => {
      const next = { ...current }
      if (next[id] === undefined) next[id] = ''
      else delete next[id]
      return next
    })
  }

  async function submit(event) {
    event.preventDefault()
    setError(null)
    if (form.password.length < MIN_PASSWORD_LENGTH) return setError(`Choose a password of at least ${MIN_PASSWORD_LENGTH} characters.`)
    if (form.password !== form.password_confirm) return setError('The two passwords do not match.')
    if (!chosen.length) return setError('Choose at least one kind of data.')
    const counts = {}
    for (const kind of chosen) {
      const value = Number(kinds[kind.id])
      if (!Number.isInteger(value) || value < 1) return setError(`Enter an approximate number of ${kind.label} records.`)
      counts[kind.id] = value
    }
    setBusy(true)
    try {
      const result = await api.submitRegistration({
        ...form,
        hospital_name: form.hospital_name.trim(),
        contact_name: form.contact_name.trim(),
        contact_email: form.contact_email.trim(),
        modalities: chosen.map((k) => k.id),
        approx_record_counts: counts,
        confirm_no_patient_data: confirmed,
      })
      setReceipt(result)
    } catch (failure) {
      setError(toApiError(failure).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="min-h-screen bg-canvas px-5 py-10">
      <div className="mx-auto w-full max-w-xl">
        <Logo />
        {receipt ? (
          <div className="mt-8 rounded-lg border border-line bg-surface p-6">
            <div className="flex items-start gap-3">
              <CircleCheck className="mt-0.5 h-5 w-5 shrink-0 text-ok" aria-hidden="true" />
              <div>
                <h1 className="text-xl font-semibold text-ink">Request received</h1>
                <p className="mt-2 text-sm leading-relaxed text-muted">
                  {receipt.hospital_name} is waiting for an administrator&rsquo;s approval. Once it is approved, sign in with{' '}
                  <span className="font-medium text-ink">{form.contact_email.trim()}</span> and the password you chose. Your hospital&rsquo;s
                  page then shows how to connect your own computer.
                </p>
                <Link to="/login" className="mt-4 inline-block text-sm font-medium text-brand-700 hover:underline">
                  Go to sign in
                </Link>
              </div>
            </div>
          </div>
        ) : (
          <form className="mt-8 space-y-5 rounded-lg border border-line bg-surface p-6" onSubmit={submit} noValidate>
            <div>
              <h1 className="text-xl font-semibold text-ink">Register your hospital</h1>
              <p className="mt-1.5 text-sm leading-relaxed text-muted">
                An administrator reviews every request. After approval your hospital trains on its own computer with the MediFed Hospital
                Agent; patient records never leave it. No files are uploaded here.
              </p>
            </div>
            {error ? (
              <div role="alert" className="flex gap-2.5 rounded-md border border-alert/25 bg-alert-soft px-3.5 py-3 text-sm text-ink">
                <CircleAlert className="mt-0.5 h-4 w-4 shrink-0 text-alert" aria-hidden="true" />
                <span>{error}</span>
              </div>
            ) : null}

            <Field label="Hospital name" htmlFor="hospital-name">
              <input id="hospital-name" className={inputClass} maxLength={120} value={form.hospital_name} onChange={set('hospital_name')} />
            </Field>
            <Field label="Region" htmlFor="region" hint={regionError || 'The region the hospital serves.'}>
              <Select
                id="region"
                value={form.region_id}
                onChange={(value) => setForm((f) => ({ ...f, region_id: value }))}
                options={[{ value: '', label: 'Choose a region…' }, ...regions.map((r) => ({ value: r.region_id, label: r.name }))]}
              />
            </Field>
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="Contact name" htmlFor="contact-name">
                <input id="contact-name" className={inputClass} maxLength={80} autoComplete="name" value={form.contact_name} onChange={set('contact_name')} />
              </Field>
              <Field label="Contact email" htmlFor="contact-email" hint="You sign in with this email.">
                <input
                  id="contact-email"
                  type="email"
                  className={inputClass}
                  autoComplete="email"
                  value={form.contact_email}
                  onChange={set('contact_email')}
                />
              </Field>
              <Field label="Password" htmlFor="reg-password" hint={`At least ${MIN_PASSWORD_LENGTH} characters.`}>
                <input id="reg-password" type="password" className={inputClass} autoComplete="new-password" value={form.password} onChange={set('password')} />
              </Field>
              <Field label="Confirm password" htmlFor="reg-confirm">
                <input
                  id="reg-confirm"
                  type="password"
                  className={inputClass}
                  autoComplete="new-password"
                  value={form.password_confirm}
                  onChange={set('password_confirm')}
                />
              </Field>
            </div>

            <fieldset>
              <legend className="text-sm font-medium text-ink">Data your hospital will train on</legend>
              <p className="mt-1 text-xs text-muted">Approximate counts are enough. They help the administrator review the request.</p>
              <div className="mt-3 space-y-2">
                {KINDS.map((kind) => {
                  const on = kinds[kind.id] !== undefined
                  return (
                    <div key={kind.id} className="flex flex-wrap items-center gap-3">
                      <label className="flex min-w-0 flex-1 items-center gap-2 text-sm text-ink sm:flex-none sm:basis-64">
                        <input type="checkbox" className="h-4 w-4 shrink-0 accent-[#24489a]" checked={on} onChange={() => toggleKind(kind.id)} />
                        <span className="whitespace-nowrap font-medium">{kind.label}</span>
                        <span className="truncate text-xs text-muted">{kind.hint}</span>
                      </label>
                      {on ? (
                        <div className="w-40">
                          <input
                            aria-label={`Approximate number of ${kind.label} records`}
                            type="number"
                            min={1}
                            placeholder="Approx. records"
                            className={inputClass}
                            value={kinds[kind.id]}
                            onChange={(e) => setKinds((k) => ({ ...k, [kind.id]: e.target.value }))}
                          />
                        </div>
                      ) : null}
                    </div>
                  )
                })}
              </div>
            </fieldset>

            <label className="flex items-start gap-2.5 rounded-md border border-line bg-canvas p-3 text-sm text-ink">
              <input
                type="checkbox"
                className="mt-0.5 h-4 w-4 accent-[#24489a]"
                checked={confirmed}
                onChange={(e) => setConfirmed(e.target.checked)}
              />
              <span>{CONFIRMATION}</span>
            </label>

            <Button type="submit" variant="primary" className="w-full" loading={busy} disabled={!confirmed}>
              Send request
            </Button>
            <p className="text-center text-sm">
              <Link to="/login" className="font-medium text-brand-700 hover:underline">
                Already approved? Sign in
              </Link>
            </p>
          </form>
        )}
      </div>
    </div>
  )
}
