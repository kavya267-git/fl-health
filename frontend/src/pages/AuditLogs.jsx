import { ChevronDown, ChevronRight, Search, ShieldCheck } from 'lucide-react'
import { Fragment, useEffect, useState } from 'react'
import { Badge } from '../components/ui/Badge'
import { Button } from '../components/ui/Button'
import { Card, CardBody } from '../components/ui/Card'
import { Field, Note, PageHeader, Select, Td, Th, inputClass } from '../components/ui/Misc'
import { AsyncView, EmptyState } from '../components/ui/StateViews'
import { useApi } from '../hooks/useApi'
import { toApiError } from '../services/api'
import { api } from '../services/endpoints'
import { AUDIT_ACTION_LABELS } from '../utils/constants'
import { DASH, formatDateTime, formatNumber } from '../utils/format'

const PAGE_SIZE = 25
const STATUS_OPTIONS = [
  { value: '', label: 'Any status' },
  { value: 'SUCCESS', label: 'Success' },
  { value: 'FAILED', label: 'Failed' },
  { value: 'REJECTED', label: 'Rejected' },
]
const STATUS_TONES = { SUCCESS: 'ok', FAILED: 'alert', REJECTED: 'alert' }
const STATUS_LABELS = { SUCCESS: 'Success', FAILED: 'Failed', REJECTED: 'Rejected' }

/** Delays a fast-changing value so typing in the search box does not fire a request per keystroke. */
function useDebounced(value, delayMs) {
  const [debounced, setDebounced] = useState(value)
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delayMs)
    return () => clearTimeout(timer)
  }, [value, delayMs])
  return debounced
}

function Verification({ result }) {
  if (result.error) {
    return (
      <Note tone="alert" title="The audit chain could not be checked">
        {result.error}
      </Note>
    )
  }
  return (
    <Note tone={result.valid ? 'ok' : 'alert'} title={result.valid ? 'The audit chain is intact' : 'The audit chain is broken'}>
      {result.valid
        ? `All ${formatNumber(result.entries_checked)} entries match their hashes and link to the entry before them.`
        : `Entry ${result.first_invalid_id} fails the check. ${result.reason}`}{' '}
      {result.note}
    </Note>
  )
}

export default function AuditLogs() {
  const [search, setSearch] = useState('')
  const [action, setAction] = useState('')
  const [status, setStatus] = useState('')
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')
  const [page, setPage] = useState(0)
  const [expanded, setExpanded] = useState(null)
  const [verification, setVerification] = useState(null)
  const [verifying, setVerifying] = useState(false)
  const debouncedSearch = useDebounced(search, 300)

  // Any filter change returns to the first page.
  useEffect(() => setPage(0), [debouncedSearch, action, status, dateFrom, dateTo])

  const state = useApi(
    () =>
      api.audit({
        search: debouncedSearch || undefined,
        action: action || undefined,
        status: status || undefined,
        date_from: dateFrom || undefined,
        date_to: dateTo || undefined,
        limit: PAGE_SIZE,
        offset: page * PAGE_SIZE,
      }),
    [debouncedSearch, action, status, dateFrom, dateTo, page],
    { isEmpty: (data) => data.items.length === 0 },
  )

  async function verify() {
    setVerifying(true)
    try {
      setVerification(await api.verifyAudit())
    } catch (error) {
      setVerification({ error: toApiError(error).message })
    } finally {
      setVerifying(false)
    }
  }

  const hasFilters = Boolean(search || action || status || dateFrom || dateTo)
  const clearFilters = () => {
    setSearch('')
    setAction('')
    setStatus('')
    setDateFrom('')
    setDateTo('')
  }
  const actionOptions = [
    { value: '', label: 'Any action' },
    ...Object.entries(AUDIT_ACTION_LABELS).map(([value, label]) => ({ value, label })),
  ]

  return (
    <>
      <PageHeader
        title="Audit Logs"
        description="A record of what happened and who did it. Each entry is hashed together with the one before it, so a changed or deleted entry can be detected."
        actions={
          <Button icon={ShieldCheck} loading={verifying} onClick={verify}>
            Verify chain
          </Button>
        }
      />

      {verification ? (
        <div className="mb-5">
          <Verification result={verification} />
        </div>
      ) : null}

      <Card className="mb-5">
        <CardBody className="grid gap-4 md:grid-cols-2 xl:grid-cols-[1.4fr_1fr_0.8fr_0.8fr_0.8fr_auto] xl:items-end">
          <Field label="Search" htmlFor="audit-search">
            <div className="relative">
              <Search className="pointer-events-none absolute left-3 top-3 h-4 w-4 text-faint" aria-hidden="true" />
              <input
                id="audit-search"
                type="search"
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                placeholder="Search entries"
                className={`${inputClass} pl-9`}
              />
            </div>
          </Field>
          <Field label="Action" htmlFor="audit-action">
            <Select id="audit-action" value={action} onChange={setAction} options={actionOptions} />
          </Field>
          <Field label="Status" htmlFor="audit-status">
            <Select id="audit-status" value={status} onChange={setStatus} options={STATUS_OPTIONS} />
          </Field>
          <Field label="From" htmlFor="audit-from">
            <input
              id="audit-from"
              type="date"
              value={dateFrom}
              max={dateTo || undefined}
              onChange={(e) => setDateFrom(e.target.value)}
              className={inputClass}
            />
          </Field>
          <Field label="To" htmlFor="audit-to">
            <input
              id="audit-to"
              type="date"
              value={dateTo}
              min={dateFrom || undefined}
              onChange={(e) => setDateTo(e.target.value)}
              className={inputClass}
            />
          </Field>
          <Button onClick={clearFilters} disabled={!hasFilters}>
            Clear filters
          </Button>
        </CardBody>
      </Card>

      <Card>
        <AsyncView
          state={state}
          what="the audit log"
          empty={
            <EmptyState
              title={hasFilters ? 'No entries match these filters' : 'No audit entries yet'}
              description={
                hasFilters ? 'Widen the date range or clear the filters.' : 'Entries appear as soon as someone signs in or a round runs.'
              }
              action={
                hasFilters ? (
                  <Button size="sm" onClick={clearFilters}>
                    Clear filters
                  </Button>
                ) : null
              }
            />
          }
        >
          {(data) => {
            const first = data.offset + 1
            const last = data.offset + data.items.length
            return (
              <>
                <div className="overflow-x-auto">
                  <table className="w-full border-collapse">
                    <thead>
                      <tr>
                        <Th className="w-8" />
                        <Th>Timestamp</Th>
                        <Th>Actor</Th>
                        <Th>Action</Th>
                        <Th>Hospital</Th>
                        <Th>FL Round</Th>
                        <Th>Model Version</Th>
                        <Th>Status</Th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.items.map((entry) => {
                        const open = expanded === entry.id
                        return (
                          <Fragment key={entry.id}>
                            <tr className={open ? 'bg-canvas' : 'hover:bg-canvas'}>
                              <Td>
                                <button
                                  type="button"
                                  onClick={() => setExpanded(open ? null : entry.id)}
                                  aria-expanded={open}
                                  aria-label={`${open ? 'Hide' : 'Show'} details for entry ${entry.id}`}
                                  className="rounded p-0.5 text-muted hover:text-ink"
                                >
                                  {open ? (
                                    <ChevronDown className="h-4 w-4" aria-hidden="true" />
                                  ) : (
                                    <ChevronRight className="h-4 w-4" aria-hidden="true" />
                                  )}
                                </button>
                              </Td>
                              <Td className="whitespace-nowrap">{formatDateTime(entry.timestamp)}</Td>
                              <Td className="max-w-56 truncate" title={entry.actor}>
                                {entry.actor}
                              </Td>
                              <Td>{AUDIT_ACTION_LABELS[entry.action] || entry.action}</Td>
                              <Td className="whitespace-nowrap font-mono text-[13px]">{entry.hospital_id || DASH}</Td>
                              <Td className="whitespace-nowrap font-mono text-[13px]">{entry.round_id || DASH}</Td>
                              <Td>{entry.model_version || DASH}</Td>
                              <Td>
                                <Badge tone={STATUS_TONES[entry.status] || 'neutral'}>{STATUS_LABELS[entry.status] || entry.status}</Badge>
                              </Td>
                            </tr>
                            {open ? (
                              <tr className="bg-canvas">
                                <td />
                                <td colSpan={7} className="border-b border-line px-4 pb-4 pt-1">
                                  <dl className="grid gap-x-6 gap-y-2 text-xs sm:grid-cols-2">
                                    <div>
                                      <dt className="text-muted">Entry hash</dt>
                                      <dd className="break-all font-mono text-ink">{entry.current_hash}</dd>
                                    </div>
                                    <div>
                                      <dt className="text-muted">Previous entry hash</dt>
                                      <dd className="break-all font-mono text-ink">{entry.previous_hash}</dd>
                                    </div>
                                    <div className="sm:col-span-2">
                                      <dt className="text-muted">Details</dt>
                                      <dd>
                                        <pre className="mt-1 max-h-56 overflow-auto rounded border border-line bg-surface p-3 font-mono text-xs leading-relaxed text-ink">
                                          {JSON.stringify(entry.details ?? {}, null, 2)}
                                        </pre>
                                      </dd>
                                    </div>
                                  </dl>
                                </td>
                              </tr>
                            ) : null}
                          </Fragment>
                        )
                      })}
                    </tbody>
                  </table>
                </div>
                <div className="flex flex-wrap items-center justify-between gap-3 px-4 py-3">
                  <p className="text-sm text-muted">
                    Showing {formatNumber(first)} to {formatNumber(last)} of {formatNumber(data.total)}, newest first
                  </p>
                  <div className="flex gap-2">
                    <Button size="sm" disabled={page === 0} onClick={() => setPage((p) => p - 1)}>
                      Newer
                    </Button>
                    <Button size="sm" disabled={last >= data.total} onClick={() => setPage((p) => p + 1)}>
                      Older
                    </Button>
                  </div>
                </div>
              </>
            )
          }}
        </AsyncView>
      </Card>
    </>
  )
}
