import { useCallback, useEffect, useRef, useState } from 'react'
import { toApiError } from '../services/api'

/**
 * Runs an API call and tracks its state.
 *
 * status: 'loading' | 'success' | 'empty' | 'error'
 *   - 'empty' is success with nothing to show (decided by `isEmpty`)
 *   - on 'error', `error.kind` says why (see services/api.js)
 *
 * `reload()` repeats the call. With `{ silent: true }` the current data stays
 * on screen while it refreshes (used for polling); if a silent refresh fails,
 * the error replaces the data so stale values are never shown as current.
 */
export function useApi(request, deps = [], { isEmpty, enabled = true } = {}) {
  const [state, setState] = useState({ status: 'loading', data: null, error: null })
  const latest = useRef(0)
  const requestRef = useRef(request)
  const emptyRef = useRef(isEmpty)
  requestRef.current = request
  emptyRef.current = isEmpty

  const run = useCallback(async ({ silent = false } = {}) => {
    const ticket = ++latest.current
    if (!silent) setState({ status: 'loading', data: null, error: null })
    try {
      const data = await requestRef.current()
      if (ticket !== latest.current) return // a newer request superseded this one
      const empty = emptyRef.current ? emptyRef.current(data) : false
      setState({ status: empty ? 'empty' : 'success', data, error: null })
    } catch (error) {
      if (ticket !== latest.current) return
      setState({ status: 'error', data: null, error: toApiError(error) })
    }
  }, [])

  useEffect(() => {
    if (!enabled) return undefined
    run()
    return () => {
      latest.current += 1 // ignore a response that arrives after unmount or a dependency change
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, enabled, run])

  return { ...state, reload: run }
}
