import { CircleAlert, CircleCheck, CircleX, Info } from 'lucide-react'
import { useState } from 'react'
import { Badge, ModalityTag } from '../components/ui/Badge'
import { Button } from '../components/ui/Button'
import { Card, CardBody, CardHeader } from '../components/ui/Card'
import { DefinitionList, Note, PageHeader, Select, Td, Th } from '../components/ui/Misc'
import { AsyncView } from '../components/ui/StateViews'
import { useAuth } from '../context/AuthContext'
import { useSystem } from '../context/SystemContext'
import { useApi } from '../hooks/useApi'
import { API_BASE_URL, toApiError } from '../services/api'
import { api } from '../services/endpoints'
import {
  HOSPITAL_ROLES,
  JURISDICTION_ROLES,
  MODALITIES,
  MODALITY_ORDER,
  ROLE_DESCRIPTIONS,
  ROLE_LABELS,
  ROLE_ORDER,
} from '../utils/constants'
import { DASH, formatDateTime, formatNumber } from '../utils/format'

const CHECK_ICONS = {
  PASS: { icon: CircleCheck, color: 'text-ok', label: 'Pass' },
  WARN: { icon: CircleAlert, color: 'text-warn', label: 'Warning' },
  FAIL: { icon: CircleX, color: 'text-alert', label: 'Fail' },
  INFO: { icon: Info, color: 'text-muted', label: 'Note' },
}

function Environment() {
  const { config } = useSystem()
  return (
    <Card>
      <CardHeader title="Environment" description="How this server is running. These values are set on the server, not here." />
      <CardBody className="space-y-5">
        <DefinitionList
          columns={3}
          items={[
            { term: 'Mode', value: config.demo_mode ? 'Demo (simulated hospitals and data)' : 'Real (configured datasets)' },
            { term: 'Sign-in provider', value: config.auth_provider === 'supabase' ? 'Supabase Auth' : 'Built-in accounts' },
            { term: 'Sign-up', value: config.signup_enabled ? 'Open (new accounts are viewers)' : 'Off (administrator only)' },
            { term: 'Database', value: config.database === 'sqlite' ? 'SQLite (local file)' : 'PostgreSQL' },
            {
              term: 'Hospital nodes',
              value: config.hospital_nodes === 'in-process' ? 'Run inside the API process' : 'External processes over HTTP',
            },
            { term: 'API address', value: API_BASE_URL },
            { term: 'Version', value: config.version },
          ]}
        />
        <div className="overflow-x-auto">
          <table className="w-full border-collapse">
            <thead>
              <tr>
                <Th>Modality</Th>
                <Th>Target architecture</Th>
                <Th>Running now</Th>
                <Th>Backend</Th>
              </tr>
            </thead>
            <tbody>
              {MODALITY_ORDER.map((modality) => {
                const backend = config.model_backends[modality]
                return (
                  <tr key={modality}>
                    <Td>
                      <span className="flex items-center gap-2">
                        <ModalityTag modality={modality} />
                        {MODALITIES[modality].name}
                      </span>
                    </Td>
                    <Td>{backend.target_architecture}</Td>
                    <Td>
                      {backend.architecture || 'Unavailable'} {backend.is_target_architecture ? null : <Badge tone="warn">Stand-in</Badge>}
                    </Td>
                    <Td>{backend.backend || DASH}</Td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
        {!config.pytorch_available ? (
          <Note tone="warn" title="PyTorch is not installed on the server">
            TabNet, CNN-BiLSTM and EfficientNet-B3 need PyTorch. Until it is installed, a small NumPy model stands in for each of them so
            the federated workflow can still run. Results are labelled as coming from the stand-in.
          </Note>
        ) : null}
      </CardBody>
    </Card>
  )
}

function Privacy() {
  const state = useApi(() => api.privacy(), [])
  return (
    <Card>
      <CardHeader title="Privacy" description="What leaves a hospital, what protections are on, and what the automated checks found." />
      <AsyncView state={state} what="the privacy report">
        {(report) => {
          const dp = report.differential_privacy
          return (
            <CardBody className="space-y-6">
              <Note tone="info">{report.statement}</Note>

              <div className="grid gap-6 md:grid-cols-2">
                <div>
                  <h3 className="text-sm font-semibold text-ink">Shared with the coordinator</h3>
                  <ul className="mt-2 list-disc space-y-1 pl-5 text-sm leading-relaxed text-ink">
                    {report.architecture.shared_with_coordinator.map((item) => (
                      <li key={item}>{item}</li>
                    ))}
                  </ul>
                </div>
                <div>
                  <h3 className="text-sm font-semibold text-ink">Never sent by a hospital</h3>
                  <ul className="mt-2 list-disc space-y-1 pl-5 text-sm leading-relaxed text-ink">
                    {report.architecture.never_shared.map((item) => (
                      <li key={item}>{item}</li>
                    ))}
                  </ul>
                  <p className="mt-3 text-sm leading-relaxed text-muted">{report.architecture.raw_data_location}</p>
                </div>
              </div>

              <div>
                <h3 className="text-sm font-semibold text-ink">Validation checks</h3>
                <ul className="mt-2 divide-y divide-line rounded-md border border-line">
                  {report.checks.map((check) => {
                    const meta = CHECK_ICONS[check.status] || CHECK_ICONS.INFO
                    const Icon = meta.icon
                    return (
                      <li key={check.id} className="flex gap-3 px-4 py-3">
                        <Icon className={`mt-0.5 h-4 w-4 shrink-0 ${meta.color}`} aria-hidden="true" />
                        <div className="min-w-0">
                          <p className="text-sm font-medium text-ink">
                            {check.title} <span className={`ml-1 text-xs font-semibold ${meta.color}`}>{meta.label}</span>
                          </p>
                          <p className="mt-0.5 text-sm leading-relaxed text-muted">{check.detail}</p>
                        </div>
                      </li>
                    )
                  })}
                </ul>
                <p className="mt-2 text-xs leading-relaxed text-muted">{report.caveat}</p>
              </div>

              <div>
                <h3 className="flex items-center gap-2 text-sm font-semibold text-ink">
                  Differential privacy <Badge tone="warn">Prototype</Badge>
                </h3>
                <p className="mt-1.5 text-sm leading-relaxed text-ink">
                  {dp.mechanism} It is chosen per round in the Start a new round dialog.{' '}
                  {dp.latest_round
                    ? dp.latest_round.enabled
                      ? `Latest round (${dp.latest_round.round_id}): on, clip norm ${dp.latest_round.clip_norm}, noise multiplier ${dp.latest_round.noise_multiplier}.`
                      : `Latest round (${dp.latest_round.round_id}): off.`
                    : 'No round has run yet.'}
                </p>
                {dp.accounting.length ? (
                  <div className="mt-3 overflow-x-auto rounded-md border border-line">
                    <table className="w-full border-collapse">
                      <thead>
                        <tr>
                          <Th>Hospital</Th>
                          <Th>Model</Th>
                          <Th align="right">Updates sent</Th>
                          <Th align="right">With DP</Th>
                          <Th align="right">Epsilon over DP rounds</Th>
                          <Th>Bound covers every round</Th>
                        </tr>
                      </thead>
                      <tbody>
                        {dp.accounting.map((row) => (
                          <tr key={`${row.hospital_id}:${row.modality}`}>
                            <Td className="font-mono text-[13px]">{row.hospital_id}</Td>
                            <Td>
                              <ModalityTag modality={row.modality} />
                            </Td>
                            <Td align="right">{row.rounds_total}</Td>
                            <Td align="right">{row.rounds_with_dp}</Td>
                            <Td align="right">
                              {row.epsilon_over_dp_rounds === null ? DASH : formatNumber(row.epsilon_over_dp_rounds, 1)}
                            </Td>
                            <Td>{row.bound_covers_all_rounds ? 'Yes' : 'No'}</Td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ) : null}
                <details className="mt-3 rounded-md border border-line px-4 py-3">
                  <summary className="cursor-pointer text-sm font-medium text-ink">Accounting assumptions</summary>
                  <ul className="mt-2 list-disc space-y-1 pl-5 text-sm leading-relaxed text-muted">
                    {dp.assumptions.map((assumption) => (
                      <li key={assumption}>{assumption}</li>
                    ))}
                  </ul>
                </details>
              </div>

              <p className="text-sm leading-relaxed text-ink">
                <span className="font-semibold">Small-count suppression:</span> a hospital never reports a weekly count between 1 and{' '}
                {report.small_cell_suppression.threshold - 1} for a region and disease. The count is withheld, and the regional total for
                that week is shown as not available.
              </p>
            </CardBody>
          )
        }}
      </AsyncView>
    </Card>
  )
}

const ROLE_OPTIONS = ROLE_ORDER.map((role) => ({ value: role, label: ROLE_LABELS[role] }))

/** Checkboxes for a health officer's regions, saved together. */
function JurisdictionPicker({ email, regions, value, pending, disabled, onSave }) {
  const [chosen, setChosen] = useState(value)
  if (!regions.length) {
    return <p className="text-xs text-warn-ink">No regions are loaded, so a jurisdiction cannot be set yet.</p>
  }
  const toggle = (id) => setChosen((current) => (current.includes(id) ? current.filter((r) => r !== id) : [...current, id]))
  const unchanged = chosen.length === value.length && chosen.every((id) => value.includes(id))
  return (
    <fieldset className="space-y-2">
      <legend className="text-xs font-medium text-ink">Jurisdiction for {email}</legend>
      <div className="grid max-h-40 grid-cols-2 gap-x-3 gap-y-1 overflow-y-auto rounded-md border border-line p-2">
        {regions.map((region) => (
          <label key={region.region_id} className="flex items-center gap-1.5 text-xs text-ink">
            <input
              type="checkbox"
              className="h-3.5 w-3.5 accent-[#24489a]"
              checked={chosen.includes(region.region_id)}
              onChange={() => toggle(region.region_id)}
            />
            {region.name} ({region.region_id})
          </label>
        ))}
      </div>
      <Button size="sm" disabled={disabled || chosen.length === 0 || (unchanged && !pending)} onClick={() => onSave(chosen)}>
        Save jurisdiction
      </Button>
      {pending ? <p className="text-xs text-warn-ink">Choose at least one region and save to give this role.</p> : null}
    </fieldset>
  )
}

/** Administrators only: who has an account, and what each person may do. */
function Users() {
  const { user: me } = useAuth()
  const state = useApi(async () => {
    const [users, hospitals, regions] = await Promise.all([
      api.users(),
      api.hospitals(),
      // Regions for health officers' jurisdictions; the user list still works without surveillance data.
      Promise.resolve()
        .then(() => api.analyticsOptions())
        .then(
          (options) => options.regions,
          () => [],
        ),
    ])
    return { users, hospitals, regions }
  }, [])
  const [saving, setSaving] = useState(null)
  const [error, setError] = useState(null)
  const [saved, setSaved] = useState(null)
  // Just saved (shown at once while the list refreshes), or chosen but waiting for a hospital.
  const [changed, setChanged] = useState({})

  async function save(target, role, { hospitalId = null, jurisdiction = null } = {}) {
    setError(null)
    setSaved(null)
    const needsHospital = HOSPITAL_ROLES.includes(role) && !hospitalId
    const needsJurisdiction = JURISDICTION_ROLES.includes(role) && !jurisdiction?.length
    if (needsHospital || needsJurisdiction) {
      // A hospital operator or manager needs a hospital, a health officer a jurisdiction, before anything is saved.
      setChanged((current) => ({
        ...current,
        [target.id]: { role, hospital_id: hospitalId, jurisdiction: jurisdiction || [], pending: true },
      }))
      return
    }
    setSaving(target.id)
    try {
      const updated = HOSPITAL_ROLES.includes(role)
        ? await api.setUserRole(target.id, role, hospitalId)
        : JURISDICTION_ROLES.includes(role)
          ? await api.setUserRole(target.id, role, null, jurisdiction)
          : await api.setUserRole(target.id, role)
      setChanged((current) => ({
        ...current,
        [target.id]: { role: updated.role, hospital_id: updated.hospital_id, jurisdiction: updated.jurisdiction },
      }))
      const scope = updated.hospital_id
        ? ` for ${updated.hospital_id}`
        : updated.jurisdiction?.length
          ? ` for ${updated.jurisdiction.join(', ')}`
          : ''
      setSaved(`${target.email} is now ${ROLE_LABELS[role]}${scope}.`)
      state.reload({ silent: true })
    } catch (failure) {
      setError(toApiError(failure).message)
    } finally {
      setSaving(null)
    }
  }

  return (
    <Card>
      <CardHeader
        title="Users and roles"
        description="People who sign up start as viewers. Only an administrator can change a role, and only here. A hospital operator or manager is linked to one hospital; a health officer to the regions of their jurisdiction."
      />
      <AsyncView state={state} what="the user list">
        {({ users, hospitals, regions }) => (
          <CardBody className="space-y-4">
            {error ? <Note tone="alert">{error}</Note> : null}
            {saved && !error ? <Note tone="ok">{saved}</Note> : null}
            <div className="overflow-x-auto rounded-md border border-line">
              <table className="w-full border-collapse">
                <thead>
                  <tr>
                    <Th>User</Th>
                    <Th>Role</Th>
                    <Th>Joined</Th>
                    <Th>Last sign-in</Th>
                  </tr>
                </thead>
                <tbody>
                  {users.map((user) => {
                    const isMe = user.id === me.id
                    const current = changed[user.id] || {
                      role: user.role,
                      hospital_id: user.hospital_id,
                      jurisdiction: user.jurisdiction,
                    }
                    const lockedReason = isMe ? 'You cannot change your own role.' : user.role_locked_reason
                    const hospitalOptions = [
                      ...(current.hospital_id ? [] : [{ value: '', label: 'Choose a hospital…' }]),
                      ...hospitals.map((h) => ({ value: h.id, label: `${h.name} (${h.id})` })),
                    ]
                    return (
                      <tr key={user.id}>
                        <Td>
                          <p className="font-medium">
                            {user.display_name || user.email} {isMe ? <span className="font-normal text-muted">(you)</span> : null}
                          </p>
                          <p className="text-[13px] text-muted">{user.email}</p>
                        </Td>
                        <Td>
                          {lockedReason ? (
                            <>
                              <Badge tone={current.role === 'admin' ? 'brand' : 'neutral'}>{ROLE_LABELS[current.role] || current.role}</Badge>
                              {current.hospital_id ? <p className="mt-1 text-xs text-ink">{current.hospital_id}</p> : null}
                              {current.jurisdiction?.length ? (
                                <p className="mt-1 text-xs text-ink">{current.jurisdiction.join(', ')}</p>
                              ) : null}
                              <p className="mt-1 text-xs text-muted">{lockedReason}</p>
                            </>
                          ) : (
                            <div className="w-56 space-y-2">
                              <Select
                                aria-label={`Role for ${user.email}`}
                                value={current.role}
                                options={ROLE_OPTIONS}
                                disabled={saving !== null}
                                onChange={(next) =>
                                  save(user, next, {
                                    hospitalId: HOSPITAL_ROLES.includes(next) ? current.hospital_id : null,
                                    jurisdiction: JURISDICTION_ROLES.includes(next) ? current.jurisdiction : null,
                                  })
                                }
                              />
                              {HOSPITAL_ROLES.includes(current.role) ? (
                                <>
                                  <Select
                                    aria-label={`Hospital for ${user.email}`}
                                    value={current.hospital_id || ''}
                                    options={hospitalOptions}
                                    disabled={saving !== null}
                                    onChange={(next) => next && save(user, current.role, { hospitalId: next })}
                                  />
                                  {current.pending ? <p className="text-xs text-warn-ink">Choose the hospital to save this role.</p> : null}
                                </>
                              ) : null}
                              {JURISDICTION_ROLES.includes(current.role) ? (
                                <JurisdictionPicker
                                  email={user.email}
                                  regions={regions}
                                  value={current.jurisdiction || []}
                                  pending={current.pending}
                                  disabled={saving !== null}
                                  onSave={(next) => save(user, current.role, { jurisdiction: next })}
                                />
                              ) : null}
                            </div>
                          )}
                        </Td>
                        <Td className="whitespace-nowrap">{formatDateTime(user.created_at)}</Td>
                        <Td className="whitespace-nowrap">{user.last_login_at ? formatDateTime(user.last_login_at) : 'Never'}</Td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
            <dl className="grid gap-x-6 gap-y-2 text-sm sm:grid-cols-2">
              {ROLE_ORDER.map((role) => (
                <div key={role}>
                  <dt className="font-semibold text-ink">{ROLE_LABELS[role]}</dt>
                  <dd className="mt-0.5 leading-relaxed text-muted">{ROLE_DESCRIPTIONS[role]}</dd>
                </div>
              ))}
            </dl>
          </CardBody>
        )}
      </AsyncView>
    </Card>
  )
}

function Account() {
  const { user, provider, signOut } = useAuth()
  return (
    <Card>
      <CardHeader title="Account" />
      <CardBody className="flex flex-wrap items-end justify-between gap-4">
        <DefinitionList
          columns={3}
          items={[
            { term: 'Signed in as', value: user.email },
            { term: 'Role', value: ROLE_LABELS[user.role] || user.role },
            { term: 'Sign-in provider', value: provider === 'supabase' ? 'Supabase Auth' : 'Built-in sign-in' },
          ]}
        />
        <Button onClick={signOut}>Sign out</Button>
      </CardBody>
    </Card>
  )
}

export default function SettingsPage() {
  const { user } = useAuth()
  const isAdmin = user.role === 'admin'
  return (
    <>
      <PageHeader
        title="Settings"
        description={
          isAdmin ? 'Environment, privacy configuration, users and your account.' : 'Environment, privacy configuration and your account.'
        }
      />
      <div className="space-y-6">
        <Environment />
        <Privacy />
        {isAdmin ? <Users /> : null}
        <Account />
      </div>
    </>
  )
}
