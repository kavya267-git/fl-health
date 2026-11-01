import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react'
import { ApiError, configureApi, toApiError } from '../services/api'
import { api } from '../services/endpoints'
import { getSupabase, isSupabaseConfigured } from '../services/supabase'
import { useSystem } from './SystemContext'

const AuthContext = createContext(null)
const DEMO_TOKEN_KEY = 'fl-healthcare.demo-token'

/**
 * Authentication state.
 *
 * The server decides the provider (see /api/system/config):
 *   - "supabase": sign in with Supabase Auth in the browser; the access token
 *     is sent to the API, which verifies it and looks up the user's role.
 *   - "demo": the API issues a short-lived token for a built-in demo account
 *     or an account created through the sign-up form.
 *
 * Signing up never grants more than the viewer role, whichever provider is used.
 *
 * status: 'loading' | 'signedOut' | 'signedIn' | 'misconfigured'
 */
export function AuthProvider({ children }) {
  const { status: systemStatus, config } = useSystem()
  const provider = config?.auth_provider
  const [auth, setAuth] = useState({ status: 'loading', user: null, notice: null })
  const demoToken = useRef(null)

  const signOutLocally = useCallback((notice = null) => {
    demoToken.current = null
    try {
      sessionStorage.removeItem(DEMO_TOKEN_KEY)
    } catch {
      /* storage may be unavailable; the in-memory token is already cleared */
    }
    setAuth({ status: 'signedOut', user: null, notice })
  }, [])

  // Give the HTTP client a way to get the current token and to react to 401s.
  useEffect(() => {
    configureApi({
      tokenProvider: async () => {
        if (provider === 'supabase') {
          const client = getSupabase()
          if (!client) return null
          const { data } = await client.auth.getSession()
          return data.session?.access_token ?? null
        }
        return demoToken.current
      },
      onUnauthorized: () => {
        if (provider === 'supabase') getSupabase()?.auth.signOut()
        signOutLocally('Your session has ended. Sign in again to continue.')
      },
    })
  }, [provider, signOutLocally])

  // Restore an existing session once the provider is known.
  useEffect(() => {
    if (systemStatus !== 'success') return undefined
    let cancelled = false

    async function restore() {
      if (provider === 'supabase' && !isSupabaseConfigured) {
        setAuth({ status: 'misconfigured', user: null, notice: null })
        return
      }
      let hasSession = false
      if (provider === 'supabase') {
        const { data } = await getSupabase().auth.getSession()
        hasSession = Boolean(data.session)
      } else {
        try {
          demoToken.current = sessionStorage.getItem(DEMO_TOKEN_KEY)
        } catch {
          demoToken.current = null
        }
        hasSession = Boolean(demoToken.current)
      }
      if (!hasSession) {
        if (!cancelled) setAuth({ status: 'signedOut', user: null, notice: null })
        return
      }
      try {
        const user = await api.me()
        if (!cancelled) setAuth({ status: 'signedIn', user, notice: null })
      } catch (error) {
        if (cancelled) return
        const apiError = toApiError(error)
        signOutLocally(apiError.kind === 'unauthorized' ? null : apiError.message)
      }
    }

    restore()
    return () => {
      cancelled = true
    }
  }, [systemStatus, provider, signOutLocally])

  /** Keep the token the API issued and mark the user as signed in. */
  const startDemoSession = useCallback((result) => {
    demoToken.current = result.access_token
    try {
      sessionStorage.setItem(DEMO_TOKEN_KEY, result.access_token)
    } catch {
      /* without storage the session simply lasts until the tab is reloaded */
    }
    setAuth({ status: 'signedIn', user: result.user, notice: null })
    return result.user
  }, [])

  const signIn = useCallback(
    async (email, password) => {
      if (provider === 'supabase') {
        const { error } = await getSupabase().auth.signInWithPassword({ email, password })
        if (error) throw new ApiError('unauthorized', error.message || 'Incorrect email or password.', 401)
        // Tell the API about the new session so the sign-in is audited, and get the role.
        const { user } = await api.recordSession()
        setAuth({ status: 'signedIn', user, notice: null })
        return user
      }
      return startDemoSession(await api.demoLogin(email, password))
    },
    [provider, startDemoSession],
  )

  /**
   * Create an account. Resolves to `{ signedIn: true, user }`, or to
   * `{ signedIn: false }` when Supabase wants the email confirmed first.
   * The new account is a viewer; only an administrator can change that.
   */
  const signUp = useCallback(
    async (email, password, displayName) => {
      if (provider === 'supabase') {
        const { data, error } = await getSupabase().auth.signUp({
          email,
          password,
          options: { data: { display_name: displayName }, emailRedirectTo: `${window.location.origin}/login` },
        })
        if (error) throw new ApiError('validation', error.message || 'The account could not be created.')
        if (!data?.session) return { signedIn: false }
        const { user } = await api.recordSession()
        setAuth({ status: 'signedIn', user, notice: null })
        return { signedIn: true, user }
      }
      const user = startDemoSession(await api.register(email, password, displayName))
      return { signedIn: true, user }
    },
    [provider, startDemoSession],
  )

  const signOut = useCallback(async () => {
    if (provider === 'supabase') await getSupabase()?.auth.signOut()
    signOutLocally()
  }, [provider, signOutLocally])

  const requestPasswordReset = useCallback(
    async (email) => {
      if (provider !== 'supabase') {
        throw new ApiError('validation', 'Password reset is handled by Supabase and is not available for demo accounts.')
      }
      const { error } = await getSupabase().auth.resetPasswordForEmail(email, {
        redirectTo: `${window.location.origin}/login`,
      })
      if (error) throw new ApiError('validation', error.message)
    },
    [provider],
  )

  const value = useMemo(
    () => ({ ...auth, provider, signIn, signUp, signOut, requestPasswordReset }),
    [auth, provider, signIn, signUp, signOut, requestPasswordReset],
  )
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const value = useContext(AuthContext)
  if (!value) throw new Error('useAuth must be used inside <AuthProvider>')
  return value
}
