import { CircleAlert, Inbox, LoaderCircle, Lock, ServerOff } from 'lucide-react'
import { WORLD_IMAGE } from '../../assets/illustrations'
import { API_BASE_URL } from '../../services/api'
import { Button } from './Button'

export function LoadingState({ label = 'Loading' }) {
  return (
    <div role="status" className="flex min-h-40 flex-col items-center justify-center gap-3 px-6 py-10 text-muted">
      <LoaderCircle className="h-6 w-6 animate-spin text-brand-600" aria-hidden="true" />
      <p className="text-sm">{label}&hellip;</p>
    </div>
  )
}

/**
 * `illustration` swaps the icon for the small world-map illustration, for the "nothing here yet" states of the
 * federation as a whole (no rounds, no hospitals, no surveillance data). The image is decorative: the title says
 * what is missing.
 */
export function EmptyState({ title, description, action, icon: Icon = Inbox, illustration = false }) {
  return (
    <div className="flex min-h-40 flex-col items-center justify-center gap-2 px-6 py-10 text-center">
      {illustration ? (
        <img src={WORLD_IMAGE.src} alt={WORLD_IMAGE.alt} className="mb-2 w-full max-w-[280px]" width="592" height="380" />
      ) : (
        <Icon className="h-7 w-7 text-faint" aria-hidden="true" />
      )}
      <p className="text-sm font-semibold text-ink">{title}</p>
      {description ? <p className="max-w-md text-sm leading-relaxed text-muted">{description}</p> : null}
      {action ? <div className="mt-2">{action}</div> : null}
    </div>
  )
}

/** What to say for each kind of failure (see services/api.js for the kinds). */
function describe(error, what) {
  switch (error?.kind) {
    case 'unauthorized':
      return { icon: Lock, title: 'Your session has ended', body: 'Sign in again to continue.', retry: false }
    case 'forbidden':
      return { icon: Lock, title: 'You do not have access to this', body: error.message, retry: false }
    case 'unavailable':
      return {
        icon: ServerOff,
        title: 'Server unavailable',
        body: `${error.message} Check that the API is running at ${API_BASE_URL}.`,
        retry: true,
      }
    case 'invalid_response':
      return { icon: CircleAlert, title: 'Unexpected response', body: error.message, retry: true }
    case 'not_found':
      return { icon: CircleAlert, title: 'Not found', body: error.message, retry: false }
    default:
      return { icon: CircleAlert, title: `Unable to retrieve ${what}.`, body: error?.message, retry: true }
  }
}

export function ErrorState({ error, what = 'this data', onRetry }) {
  const { icon: Icon, title, body, retry } = describe(error, what)
  return (
    <div role="alert" className="flex min-h-40 flex-col items-center justify-center gap-2 px-6 py-10 text-center">
      <Icon className="h-7 w-7 text-alert" aria-hidden="true" />
      <p className="text-sm font-semibold text-ink">{title}</p>
      {body ? <p className="max-w-lg text-sm leading-relaxed text-muted">{body}</p> : null}
      {retry && onRetry ? (
        <Button className="mt-2" size="sm" onClick={() => onRetry()}>
          Retry
        </Button>
      ) : null}
    </div>
  )
}

/**
 * Renders the right view for a `useApi` state: loading, error (with Retry),
 * empty, or the children with the data. Stale data is never shown on error.
 */
export function AsyncView({ state, what, loadingLabel, empty, children }) {
  if (state.status === 'loading') return <LoadingState label={loadingLabel || `Loading ${what}`} />
  if (state.status === 'error') return <ErrorState error={state.error} what={what} onRetry={state.reload} />
  if (state.status === 'empty') return empty || <EmptyState title={`No ${what} yet`} />
  return children(state.data)
}

/** An explicit "not available" panel, used instead of placeholder values. */
export function UnavailableState({ title = 'Not available', reason, action }) {
  return (
    <div className="rounded-md border border-dashed border-line-strong bg-canvas px-5 py-6 text-center">
      <p className="text-sm font-semibold text-ink">{title}</p>
      {reason ? <p className="mx-auto mt-1 max-w-xl text-sm leading-relaxed text-muted">{reason}</p> : null}
      {action ? <div className="mt-3">{action}</div> : null}
    </div>
  )
}
