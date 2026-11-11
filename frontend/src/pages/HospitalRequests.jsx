import { useState } from 'react'
import { Badge } from '../components/ui/Badge'
import { Button } from '../components/ui/Button'
import { Card } from '../components/ui/Card'
import { Field, Modal, PageHeader, Tabs, inputClass } from '../components/ui/Misc'
import { AsyncView, EmptyState } from '../components/ui/StateViews'
import { useApi } from '../hooks/useApi'
import { toApiError } from '../services/api'
import { api } from '../services/endpoints'
import { MODALITIES } from '../utils/constants'
import { formatDateTime, formatNumber } from '../utils/format'

const TABS = [
  { value: 'PENDING', label: 'Pending' },
  { value: 'APPROVED', label: 'Approved' },
  { value: 'REJECTED', label: 'Rejected' },
  { value: 'REVOKED', label: 'Revoked' },
]
const TONES = { PENDING: 'warn', APPROVED: 'ok', REJECTED: 'alert', REVOKED: 'nodata' }

function ReasonDialog({ request, action, onClose, onDone }) {
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const verb = action === 'reject' ? 'Reject' : 'Revoke'

  async function submit(event) {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await (action === 'reject' ? api.rejectRegistration : api.revokeRegistration)(request.id, reason.trim())
      onDone()
    } catch (failure) {
      setError(toApiError(failure).message)
      setBusy(false)
    }
  }

  return (
    <Modal
      title={`${verb} ${request.hospital_name}`}
      onClose={busy ? () => {} : onClose}
      footer={
        <>
          <Button onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button variant="danger" type="submit" form="reason-form" loading={busy} disabled={reason.trim().length < 3}>
            {verb}
          </Button>
        </>
      }
    >
      <form id="reason-form" onSubmit={submit} className="space-y-3">
        <p className="text-sm text-muted">
          {action === 'reject'
            ? 'The account stays disabled. The reason is stored with the request and in the audit log.'
            : 'The operator can no longer sign in, and the hospital’s node token stops working at once.'}
        </p>
        <Field label="Reason" htmlFor="reason">
          <textarea id="reason" rows={3} maxLength={500} className={inputClass} value={reason} onChange={(e) => setReason(e.target.value)} />
        </Field>
        {error ? <p className="text-sm text-alert">{error}</p> : null}
      </form>
    </Modal>
  )
}

function RequestRow({ request, onChanged }) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [dialog, setDialog] = useState(null)

  async function approve() {
    setBusy(true)
    setError(null)
    try {
      await api.approveRegistration(request.id)
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
            {request.hospital_name}{' '}
            {request.hospital_id ? <span className="font-mono text-xs text-muted">({request.hospital_id})</span> : null}
          </p>
          <p className="mt-0.5 text-sm text-muted">
            {request.region_name || request.region_id} · {request.contact_name} · {request.contact_email}
          </p>
          <p className="mt-1 text-sm text-ink">
            {request.modalities
              .map((m) => `${MODALITIES[m]?.label || m} ~${formatNumber(request.approx_record_counts?.[m])}`)
              .join(' · ')}
          </p>
          <p className="mt-1 text-xs text-muted">
            Submitted {formatDateTime(request.created_at)}
            {request.reviewed_by ? ` · ${request.status.toLowerCase()} by ${request.reviewed_by}, ${formatDateTime(request.reviewed_at)}` : ''}
          </p>
          {request.reason ? <p className="mt-1 text-sm text-ink">Reason: {request.reason}</p> : null}
        </div>
        <div className="flex items-center gap-2">
          <Badge tone={TONES[request.status]}>{request.status.charAt(0) + request.status.slice(1).toLowerCase()}</Badge>
          {request.status === 'PENDING' ? (
            <>
              <Button size="sm" variant="primary" loading={busy} onClick={approve}>
                Approve
              </Button>
              <Button size="sm" onClick={() => setDialog('reject')}>
                Reject
              </Button>
            </>
          ) : null}
          {request.status === 'APPROVED' ? (
            <Button size="sm" onClick={() => setDialog('revoke')}>
              Revoke
            </Button>
          ) : null}
        </div>
      </div>
      {error ? <p className="mt-2 text-sm text-alert">{error}</p> : null}
      {dialog ? (
        <ReasonDialog
          request={request}
          action={dialog}
          onClose={() => setDialog(null)}
          onDone={async () => {
            setDialog(null)
            await onChanged()
          }}
        />
      ) : null}
    </li>
  )
}

/** Administrators only (registrations_manage). Requests are never shown on any public page. */
export default function HospitalRequests() {
  const [tab, setTab] = useState('PENDING')
  const state = useApi(() => api.registrations(tab), [tab], { isEmpty: (rows) => rows.length === 0 })

  return (
    <>
      <PageHeader
        title="Hospital requests"
        description="Hospitals that registered through the public form. Approving creates the hospital and enables its operator's account; nothing is uploaded at any step."
      />
      <div className="mb-4">
        <Tabs value={tab} onChange={setTab} options={TABS} label="Request status" />
      </div>
      <Card>
        <AsyncView state={state} what="hospital requests" empty={<EmptyState title={`No ${tab.toLowerCase()} requests`} />}>
          {(rows) => (
            <ul className="divide-y divide-line">
              {rows.map((request) => (
                <RequestRow
                  key={request.id}
                  request={request}
                  onChanged={async () => {
                    await state.reload({ silent: true })
                    window.dispatchEvent(new Event('medifed:registrations-changed'))
                  }}
                />
              ))}
            </ul>
          )}
        </AsyncView>
      </Card>
    </>
  )
}
