import { ChevronDown, CircleAlert, CircleCheck } from 'lucide-react'
import { useState } from 'react'
import { Navigate, useLocation } from 'react-router-dom'
import { NETWORK_IMAGE } from '../assets/illustrations'
import { Logo } from '../components/layout/Logo'
import { Button } from '../components/ui/Button'
import { Field, inputClass } from '../components/ui/Misc'
import { LoadingState } from '../components/ui/StateViews'
import { useAuth } from '../context/AuthContext'
import { useSystem } from '../context/SystemContext'
import { toApiError } from '../services/api'
import { MIN_PASSWORD_LENGTH, ROLE_LABELS, homePathFor } from '../utils/constants'

function Message({ tone, children }) {
  const Icon = tone === 'ok' ? CircleCheck : CircleAlert
  const colors = tone === 'ok' ? 'border-ok/25 bg-ok-soft text-ink' : 'border-alert/25 bg-alert-soft text-ink'
  return (
    <div role={tone === 'ok' ? 'status' : 'alert'} className={`flex gap-2.5 rounded-md border px-3.5 py-3 text-sm leading-snug ${colors}`}>
      <Icon className={`mt-0.5 h-4 w-4 shrink-0 ${tone === 'ok' ? 'text-ok' : 'text-alert'}`} aria-hidden="true" />
      <span>{children}</span>
    </div>
  )
}

function DemoAccountList({ accounts, onUse }) {
  return (
    <ul className="mt-3 divide-y divide-line">
      {accounts.map((account) => (
        <li key={account.email} className="flex items-center justify-between gap-3 py-2">
          <div className="min-w-0">
            <p className="truncate text-sm text-ink">{account.email}</p>
            <p className="text-xs text-muted">
              {ROLE_LABELS[account.role] || account.role}
              {account.hospital_id ? ` · ${account.hospital_id}` : ''}
            </p>
          </div>
          <Button size="sm" variant="ghost" onClick={() => onUse(account.email)}>
            Use
          </Button>
        </li>
      ))}
    </ul>
  )
}

const COPY = {
  signin: { title: 'Sign in', submit: 'Sign in' },
  signup: { title: 'Create your account', submit: 'Create account' },
  reset: { title: 'Reset your password', submit: 'Send reset link' },
}

export default function Login() {
  const { status, user, provider, notice, signIn, signUp, requestPasswordReset } = useAuth()
  const { config } = useSystem()
  const location = useLocation()
  const [mode, setMode] = useState('signin') // 'signin' | 'signup' | 'reset'
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [info, setInfo] = useState(null)

  // Once signed in: back to the page that asked for sign-in, or to this user's home page.
  if (status === 'signedIn') {
    const from = location.state?.from
    return <Navigate to={from && from !== '/' ? from : homePathFor(user)} replace />
  }

  const isDemo = provider === 'demo'
  const canSignUp = Boolean(config?.signup_enabled)

  function switchMode(next) {
    setMode(next)
    setError(null)
    setInfo(null)
    setPassword('')
    setConfirm('')
  }

  async function handleSignIn() {
    try {
      await signIn(email.trim(), password) // the redirect above takes over once signed in
    } catch (failure) {
      const apiError = toApiError(failure)
      setError(apiError.kind === 'unavailable' ? `Unable to sign in. ${apiError.message}` : apiError.message)
    }
  }

  async function handleSignUp() {
    if (password.length < MIN_PASSWORD_LENGTH) {
      setError(`Choose a password of at least ${MIN_PASSWORD_LENGTH} characters.`)
      return
    }
    if (password !== confirm) {
      setError('The two passwords do not match.')
      return
    }
    try {
      const result = await signUp(email.trim(), password, name.trim())
      if (result.signedIn) return
      // Supabase is set to confirm email addresses before the first sign-in.
      switchMode('signin')
      setInfo(`Account created. Open the confirmation link sent to ${email.trim()}, then sign in.`)
    } catch (failure) {
      const apiError = toApiError(failure)
      setError(apiError.kind === 'unavailable' ? `Unable to create the account. ${apiError.message}` : apiError.message)
    }
  }

  async function handleReset() {
    try {
      await requestPasswordReset(email.trim())
      setInfo(`If an account exists for ${email.trim()}, a reset link is on its way.`)
    } catch (failure) {
      setError(toApiError(failure).message)
    }
  }

  async function handleSubmit(event) {
    event.preventDefault()
    setError(null)
    setInfo(null)
    setBusy(true)
    try {
      await { signin: handleSignIn, signup: handleSignUp, reset: handleReset }[mode]()
    } finally {
      setBusy(false)
    }
  }

  const demoAccounts = config?.demo_accounts || []
  const operatorAccounts = demoAccounts.filter((account) => account.role === 'hospital')
  const roleAccounts = demoAccounts.filter((account) => account.role !== 'hospital')
  const incomplete = !email || (mode !== 'reset' && !password) || (mode === 'signup' && !confirm)
  const linkClass = 'font-medium text-brand-700 hover:underline'

  return (
    <div className="grid min-h-screen lg:grid-cols-[1.05fr_1fr]">
      {/* What the platform is, for someone seeing it for the first time. */}
      {/* Stays one screen tall while the form column scrolls, so the privacy note is always in view. */}
      <section className="sticky top-0 hidden h-screen flex-col overflow-hidden bg-canvas lg:flex">
        <div className="px-12 pt-10">
          <Logo />
          <div className="mt-10 max-w-lg">
            <h1 className="text-[2.1rem] font-semibold leading-[1.15] tracking-tight text-brand-950">
              Hospitals train shared models together. Patient records stay where they are.
            </h1>
            <p className="mt-5 text-base leading-relaxed text-muted">
              Each hospital trains on its own EHR, ECG and chest X-ray data. Only model updates travel to the coordinator, which averages
              them into a shared model and sends it back.
            </p>
          </div>
        </div>
        {/* Directly under the paragraph; its edges fade into the page background (#eef3fb). */}
        <img src={NETWORK_IMAGE.src} alt={NETWORK_IMAGE.alt} className="fade-edges mt-6 min-h-0 w-full shrink object-contain px-6" />
        <div className="mt-auto px-12 pb-10 pt-6">
          <p className="max-w-lg text-xs leading-relaxed text-muted">
            Federated learning reduces the need to centralise raw patient data. It does not, on its own, guarantee privacy. This is a
            research prototype and not a medical device.
          </p>
        </div>
      </section>

      <section className="flex items-center justify-center px-5 py-10">
        <div className="w-full max-w-sm">
          <div className="mb-6 lg:hidden">
            <Logo />
            <img
              src={NETWORK_IMAGE.src}
              alt={NETWORK_IMAGE.alt}
              className="fade-edges mt-5 h-36 w-full object-cover object-center"
            />
            <p className="mt-3 text-xs leading-relaxed text-muted">
              Patient records stay at each hospital; only model updates are shared. A research prototype, not a medical device.
            </p>
          </div>

          {status === 'loading' ? (
            <LoadingState label="Checking your session" />
          ) : status === 'misconfigured' ? (
            <div>
              <h2 className="text-xl font-semibold text-ink">Sign-in is not configured</h2>
              <p className="mt-3 text-sm leading-relaxed text-muted">
                This server uses Supabase for authentication, but the web app has no Supabase settings. Set{' '}
                <code className="font-mono text-[13px]">VITE_SUPABASE_URL</code> and{' '}
                <code className="font-mono text-[13px]">VITE_SUPABASE_ANON_KEY</code> in{' '}
                <code className="font-mono text-[13px]">frontend/.env</code> and restart the dev server.
              </p>
            </div>
          ) : (
            <>
              <h2 className="text-xl font-semibold text-ink">{COPY[mode].title}</h2>
              <p className="mt-1.5 text-sm leading-relaxed text-muted">
                {mode === 'signin'
                  ? isDemo
                    ? 'Use your account, or one of the demo accounts below.'
                    : 'Use your MediFed account.'
                  : mode === 'signup'
                    ? 'New accounts have read-only access. An administrator can give you more.'
                    : 'Enter your email and we will send you a link to choose a new password.'}
              </p>

              <form className="mt-6 space-y-4" onSubmit={handleSubmit} noValidate>
                {notice && !error && !info ? <Message tone="alert">{notice}</Message> : null}
                {error ? <Message tone="alert">{error}</Message> : null}
                {info ? <Message tone="ok">{info}</Message> : null}

                {mode === 'signup' ? (
                  <Field label="Name" htmlFor="name">
                    <input
                      id="name"
                      type="text"
                      autoComplete="name"
                      maxLength={80}
                      value={name}
                      onChange={(event) => setName(event.target.value)}
                      className={inputClass}
                    />
                  </Field>
                ) : null}

                <Field label="Email" htmlFor="email">
                  <input
                    id="email"
                    type="email"
                    autoComplete={mode === 'signup' ? 'email' : 'username'}
                    required
                    value={email}
                    onChange={(event) => setEmail(event.target.value)}
                    className={inputClass}
                  />
                </Field>

                {mode !== 'reset' ? (
                  <Field
                    label="Password"
                    htmlFor="password"
                    hint={mode === 'signup' ? `At least ${MIN_PASSWORD_LENGTH} characters.` : undefined}
                  >
                    <input
                      id="password"
                      type="password"
                      autoComplete={mode === 'signup' ? 'new-password' : 'current-password'}
                      required
                      value={password}
                      onChange={(event) => setPassword(event.target.value)}
                      className={inputClass}
                    />
                  </Field>
                ) : null}

                {mode === 'signup' ? (
                  <Field label="Confirm password" htmlFor="confirm-password">
                    <input
                      id="confirm-password"
                      type="password"
                      autoComplete="new-password"
                      required
                      value={confirm}
                      onChange={(event) => setConfirm(event.target.value)}
                      className={inputClass}
                    />
                  </Field>
                ) : null}

                <Button type="submit" variant="primary" className="w-full" loading={busy} disabled={incomplete}>
                  {COPY[mode].submit}
                </Button>
              </form>

              <div className="mt-4 flex flex-wrap items-center justify-between gap-x-4 gap-y-2 text-sm">
                {mode === 'signin' ? (
                  <>
                    {canSignUp ? (
                      <button type="button" className={linkClass} onClick={() => switchMode('signup')}>
                        Create an account
                      </button>
                    ) : (
                      <span className="text-muted">Need an account? Ask an administrator.</span>
                    )}
                    <button type="button" className={linkClass} onClick={() => switchMode('reset')}>
                      Forgot password?
                    </button>
                  </>
                ) : (
                  <button type="button" className={linkClass} onClick={() => switchMode('signin')}>
                    {mode === 'signup' ? 'Already have an account? Sign in' : 'Back to sign in'}
                  </button>
                )}
              </div>

              {mode === 'signup' ? (
                <p className="mt-6 rounded-md border border-line bg-surface p-4 text-xs leading-relaxed text-muted">
                  <span className="font-semibold text-ink">Administrator accounts cannot be created here.</span> Every new account starts as
                  a {ROLE_LABELS.viewer}. Coordinator and administrator access is granted by an existing administrator under Settings.
                </p>
              ) : null}

              {isDemo && mode === 'signin' && config?.demo_accounts?.length ? (
                <div className="mt-8 rounded-md border border-line bg-surface p-4">
                  <p className="text-sm font-semibold text-ink">Demo accounts</p>
                  <p className="mt-1 text-xs leading-relaxed text-muted">
                    All use the password set by <code className="font-mono">DEMO_PASSWORD</code> on the server (default{' '}
                    <code className="font-mono">demo-password</code>).
                  </p>
                  <DemoAccountList accounts={roleAccounts} onUse={setEmail} />
                  {operatorAccounts.length ? (
                    <details className="group mt-2 border-t border-line pt-2">
                      <summary className="flex cursor-pointer list-none items-center justify-between py-1.5 text-sm font-medium text-brand-700">
                        Hospital operator accounts ({operatorAccounts.length})
                        <ChevronDown className="h-4 w-4 transition-transform group-open:rotate-180" aria-hidden="true" />
                      </summary>
                      <p className="mt-1 text-xs leading-relaxed text-muted">
                        One per hospital. Sign in as your hospital&rsquo;s operator on that hospital&rsquo;s laptop.
                      </p>
                      <DemoAccountList accounts={operatorAccounts} onUse={setEmail} />
                    </details>
                  ) : null}
                </div>
              ) : null}
            </>
          )}
        </div>
      </section>
    </div>
  )
}
