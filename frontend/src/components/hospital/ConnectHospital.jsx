import { Check, Circle, Copy, Download, KeyRound } from 'lucide-react'
import { useState } from 'react'
import { AGENT_SHOTS } from '../../assets/agent'
import { toApiError } from '../../services/api'
import { api } from '../../services/endpoints'
import { AGENT_DOWNLOAD_URL, MODALITIES } from '../../utils/constants'
import { classNames, formatDateTime, formatNumber } from '../../utils/format'
import { Badge } from '../ui/Badge'
import { Button } from '../ui/Button'
import { Card, CardBody, CardHeader } from '../ui/Card'
import { Note } from '../ui/Misc'

const STEPS = [
  { id: 'NOT_CONNECTED', label: 'Not connected' },
  { id: 'CONNECTED', label: 'Connected' },
  { id: 'DATA_CHECKED', label: 'Data check passed' },
  { id: 'INVITED', label: 'Invited to rounds' },
]

/** Not connected -> Connected -> data check passed -> invited to rounds. */
export function ConnectionSteps({ connection }) {
  const reached = STEPS.findIndex((s) => s.id === connection.step)
  return (
    <ol className="grid gap-2 sm:grid-cols-4" aria-label="Connection status">
      {STEPS.map((step, index) => {
        const done = index <= reached && connection.step !== 'NOT_CONNECTED'
        const current = index === reached
        return (
          <li
            key={step.id}
            aria-current={current ? 'step' : undefined}
            className={classNames(
              'flex items-center gap-2 rounded-md border px-3 py-2 text-sm',
              current ? 'border-brand-600 bg-brand-50 font-medium text-ink' : 'border-line text-muted',
            )}
          >
            {done ? <Check className="h-4 w-4 text-ok" aria-hidden="true" /> : <Circle className="h-4 w-4" aria-hidden="true" />}
            {step.label}
          </li>
        )
      })}
    </ol>
  )
}

function TokenPanel({ connection, onIssued }) {
  const [token, setToken] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [copied, setCopied] = useState(false)
  const issued = connection.token && !connection.token.revoked_at

  async function generate() {
    if (issued && !window.confirm('A new token replaces the current one at once: a connected agent stops until you paste the new token. Continue?')) {
      return
    }
    setBusy(true)
    setError(null)
    try {
      const result = await api.generateNodeToken()
      setToken(result.token)
      setCopied(false)
      onIssued()
    } catch (failure) {
      setError(toApiError(failure).message)
    } finally {
      setBusy(false)
    }
  }

  async function copy() {
    try {
      await navigator.clipboard.writeText(token)
      setCopied(true)
    } catch {
      setCopied(false)
    }
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-3">
        <Button variant={issued ? 'secondary' : 'primary'} icon={KeyRound} loading={busy} onClick={generate}>
          {issued ? 'Generate a new node token' : 'Generate node token'}
        </Button>
        {issued ? (
          <span className="text-sm text-muted">
            Current token created {formatDateTime(connection.token.created_at)} by {connection.token.created_by}.
          </span>
        ) : null}
      </div>
      {error ? <p className="text-sm text-alert">{error}</p> : null}
      {token ? (
        <div className="rounded-md border border-warn/40 bg-warn-soft p-3">
          <p className="text-sm font-medium text-ink">Copy this token now. It is shown only once.</p>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <code data-testid="node-token" className="min-w-0 flex-1 break-all rounded bg-surface px-2 py-1.5 font-mono text-[13px] text-ink">
              {token}
            </code>
            <Button size="sm" icon={copied ? Check : Copy} onClick={copy}>
              {copied ? 'Copied' : 'Copy'}
            </Button>
          </div>
          <p className="mt-2 text-xs text-muted">
            The server keeps only a fingerprint (hash) of it. If you lose it, generate a new one; the old one stops working.
          </p>
        </div>
      ) : null}
    </div>
  )
}

function DataCheckTable({ connection }) {
  const modalities = connection.declared_modalities
  if (!modalities.length) return null
  return (
    <table className="w-full border-collapse text-sm">
      <thead>
        <tr className="text-left text-xs text-muted">
          <th className="py-1.5 font-medium">Data</th>
          <th className="py-1.5 font-medium">Local check</th>
          <th className="py-1.5 text-right font-medium">Training / held-out records</th>
          <th className="py-1.5 font-medium">Invited</th>
        </tr>
      </thead>
      <tbody className="divide-y divide-line">
        {modalities.map((m) => {
          const check = connection.data_check?.[m]
          return (
            <tr key={m}>
              <td className="py-2">{MODALITIES[m]?.label || m}</td>
              <td className="py-2">
                {!check ? (
                  <Badge tone="nodata">Not checked yet</Badge>
                ) : check.passed ? (
                  <Badge tone="ok">Passed</Badge>
                ) : (
                  <span>
                    <Badge tone="alert">Failed</Badge>
                    <span className="mt-1 block max-w-md text-xs text-alert">{check.problems.join('; ')}</span>
                  </span>
                )}
              </td>
              <td className="py-2 text-right tabular-nums">
                {check ? `${formatNumber(check.train_records)} / ${formatNumber(check.val_records)}` : '—'}
              </td>
              <td className="py-2">{connection.invited_modalities.includes(m) ? 'Yes' : 'No'}</td>
            </tr>
          )
        })}
      </tbody>
    </table>
  )
}

function AgentSteps() {
  return (
    <ol className="grid gap-4 md:grid-cols-3">
      {AGENT_SHOTS.map((shot, index) => (
        <li key={shot.title} className="min-w-0 rounded-md border border-line bg-surface">
          <img src={shot.src} alt={shot.alt} className="w-full rounded-t-md border-b border-line" loading="lazy" />
          <div className="p-3">
            <p className="text-sm font-semibold text-ink">
              {index + 1}. {shot.title}
            </p>
            <p className="mt-1 text-xs leading-relaxed text-muted">{shot.text}</p>
          </div>
        </li>
      ))}
    </ol>
  )
}

/** "Connect your hospital": for a hospital that registered through the public form, once approved. */
export function ConnectHospital({ connection, onChanged }) {
  const [templateError, setTemplateError] = useState(null)

  async function downloadTemplate() {
    setTemplateError(null)
    try {
      await api.downloadDataTemplate()
    } catch (failure) {
      setTemplateError(toApiError(failure).message)
    }
  }

  return (
    <Card>
      <CardHeader
        title="Connect your hospital"
        description="Your records stay on your own computer. The MediFed Hospital Agent trains there and sends only model updates, record counts and summary metrics."
      />
      <CardBody className="space-y-6">
        <ConnectionSteps connection={connection} />

        <section>
          <h3 className="text-sm font-semibold text-ink">a) Node token</h3>
          <p className="mb-3 mt-1 text-sm text-muted">The agent uses it to prove it acts for this hospital.</p>
          <TokenPanel connection={connection} onIssued={onChanged} />
        </section>

        <section>
          <h3 className="text-sm font-semibold text-ink">b) Download the agent</h3>
          <p className="mb-3 mt-1 text-sm text-muted">
            For Windows 10 or 11. Unzip it and open <span className="font-medium text-ink">MediFed Hospital Agent.exe</span>. No other
            software is needed.
          </p>
          <a
            href={AGENT_DOWNLOAD_URL}
            className="inline-flex items-center gap-2 rounded-md bg-brand-700 px-4 py-2 text-sm font-medium text-white hover:bg-brand-800"
          >
            <Download className="h-4 w-4" aria-hidden="true" />
            Download MediFed Hospital Agent for Windows
          </a>
          {connection.server_url ? (
            <p className="mt-2 text-xs text-muted">
              Server address to use in the agent: <code className="font-mono text-ink">{connection.server_url}</code>
            </p>
          ) : null}
        </section>

        <section>
          <h3 className="mb-3 text-sm font-semibold text-ink">c) Connect in three steps</h3>
          <AgentSteps />
        </section>

        <section>
          <h3 className="text-sm font-semibold text-ink">d) Prepare your data</h3>
          <p className="mb-3 mt-1 text-sm text-muted">
            Column lists, value ranges, and one example row of made-up values for each kind of data. To try the agent first, use its
            &ldquo;Use sample data (SIMULATED)&rdquo; button instead.
          </p>
          <Button icon={Download} onClick={downloadTemplate}>
            Download data template
          </Button>
          {templateError ? <p className="mt-2 text-sm text-alert">{templateError}</p> : null}
        </section>

        <section>
          <h3 className="mb-3 text-sm font-semibold text-ink">e) Live status</h3>
          {connection.node?.connected ? (
            <p className="mb-3 text-sm text-ink">
              Connected from <span className="font-medium">{connection.node.hostname}</span> ({connection.node.ml_backend} on{' '}
              {connection.node.device?.toUpperCase()}), last heartbeat {formatDateTime(connection.node.last_seen_at)}.
            </p>
          ) : (
            <p className="mb-3 text-sm text-muted">The agent is not connected.</p>
          )}
          <DataCheckTable connection={connection} />
          {connection.node_mode !== 'external' ? (
            <Note tone="warn" className="mt-3">
              This server runs its hospitals inside the API (in-process). Registered hospitals join only when it uses external nodes.
            </Note>
          ) : null}
        </section>
      </CardBody>
    </Card>
  )
}
