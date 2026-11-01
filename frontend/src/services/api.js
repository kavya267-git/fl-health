/**
 * The single HTTP client for the app.
 *
 * Every request goes through here so authentication and error handling are
 * defined once. Failures are converted into `ApiError` with a `kind` that
 * pages use to choose what to show:
 *
 *   unauthorized     401 - session missing or expired
 *   forbidden        403 - signed in, but the role is not allowed
 *   not_found        404
 *   conflict         409 - the request clashes with current state
 *   validation       422 - the request was rejected as invalid
 *   unavailable      network failure, timeout or 502/503/504
 *   server           any other 5xx
 *   invalid_response the server answered, but not in the expected shape
 */
import axios from 'axios'

export const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000').replace(/\/$/, '')

export class ApiError extends Error {
  constructor(kind, message, status = null) {
    super(message)
    this.name = 'ApiError'
    this.kind = kind
    this.status = status
  }
}

const KIND_BY_STATUS = {
  401: 'unauthorized',
  403: 'forbidden',
  404: 'not_found',
  409: 'conflict',
  422: 'validation',
  502: 'unavailable',
  503: 'unavailable',
  504: 'unavailable',
}

export function toApiError(error) {
  if (error instanceof ApiError) return error
  if (error?.response) {
    const { status, data } = error.response
    const kind = KIND_BY_STATUS[status] || (status >= 500 ? 'server' : 'validation')
    const detail = typeof data?.detail === 'string' ? data.detail : null
    return new ApiError(kind, detail || `The server returned an error (${status}).`, status)
  }
  if (error?.code === 'ECONNABORTED' || error?.code === 'ETIMEDOUT') {
    return new ApiError('unavailable', 'The server took too long to respond.')
  }
  return new ApiError('unavailable', `The server at ${API_BASE_URL} could not be reached.`)
}

let getToken = async () => null
let handleUnauthorized = () => {}

/** Called once by the auth provider to supply the token and the sign-out hook. */
export function configureApi({ tokenProvider, onUnauthorized }) {
  getToken = tokenProvider
  handleUnauthorized = onUnauthorized
}

export const http = axios.create({ baseURL: API_BASE_URL, timeout: 30000 })

http.interceptors.request.use(async (config) => {
  const token = await getToken()
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

http.interceptors.response.use(
  (response) => response,
  (error) => {
    const apiError = toApiError(error)
    // A rejected sign-in or sign-up attempt is not an expired session.
    const url = error?.config?.url || ''
    const isLoginAttempt = url.includes('/api/auth/demo-login') || url.includes('/api/auth/register')
    if (apiError.kind === 'unauthorized' && !isLoginAttempt) handleUnauthorized()
    return Promise.reject(apiError)
  },
)

/**
 * Guard against a response that parsed as JSON but is not what the page
 * expects, so a page never renders `undefined` as if it were data.
 */
export function expectShape(data, { array = false, keys = [] } = {}, what = 'response') {
  const invalid = () => new ApiError('invalid_response', `The server sent a ${what} this page cannot read.`)
  if (array) {
    if (!Array.isArray(data)) throw invalid()
    return data
  }
  if (data === null || typeof data !== 'object' || Array.isArray(data)) throw invalid()
  for (const key of keys) {
    if (!(key in data)) throw invalid()
  }
  return data
}
