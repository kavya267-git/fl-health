/**
 * Whole-app tests: routing, authentication and the dashboard, with the API
 * layer replaced by controllable fakes.
 */
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import App from '../App'
import { ApiError } from '../services/api'
import { api } from '../services/endpoints'
import { adminUser, emptyOverview, hospitals, managedUsers, signedUpUser, systemConfig, trainedOverview, viewerUser } from './fixtures'

vi.mock('../services/endpoints', () => ({
  api: {
    systemConfig: vi.fn(),
    me: vi.fn(),
    demoLogin: vi.fn(),
    register: vi.fn(),
    users: vi.fn(),
    setUserRole: vi.fn(),
    privacy: vi.fn(),
    recordSession: vi.fn(),
    overview: vi.fn(),
    hospitals: vi.fn(),
    rounds: vi.fn(),
    audit: vi.fn(),
    verifyAudit: vi.fn(),
  },
}))

function open(path) {
  window.history.pushState({}, '', path)
  return render(<App />)
}

function signedInAs(user) {
  sessionStorage.setItem('fl-healthcare.demo-token', 'token-for-tests')
  api.me.mockResolvedValue(user)
}

beforeEach(() => {
  vi.resetAllMocks()
  api.systemConfig.mockResolvedValue(systemConfig)
  api.overview.mockResolvedValue(emptyOverview)
  api.hospitals.mockResolvedValue(hospitals)
  api.rounds.mockResolvedValue([])
})

describe('routing and authentication', () => {
  it('sends a visitor without a session to the sign-in page', async () => {
    open('/models')
    expect(await screen.findByRole('heading', { name: 'Sign in' })).toBeInTheDocument()
    expect(window.location.pathname).toBe('/login')
    expect(api.overview).not.toHaveBeenCalled()
  })

  it('signs in, then shows the dashboard', async () => {
    api.demoLogin.mockResolvedValue({ access_token: 'abc', token_type: 'bearer', expires_in: 3600, user: adminUser })
    open('/login')
    await userEvent.type(await screen.findByLabelText('Email'), 'admin@fl-healthcare.demo')
    await userEvent.type(screen.getByLabelText('Password'), 'demo-password')
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }))

    expect(await screen.findByRole('heading', { name: 'Dashboard' })).toBeInTheDocument()
    expect(api.demoLogin).toHaveBeenCalledWith('admin@fl-healthcare.demo', 'demo-password')
    expect(window.location.pathname).toBe('/')
    expect(sessionStorage.getItem('fl-healthcare.demo-token')).toBe('abc')
  })

  it('shows the server message when sign-in is rejected and stays on the page', async () => {
    api.demoLogin.mockRejectedValue(new ApiError('unauthorized', 'Incorrect email or password.', 401))
    open('/login')
    await userEvent.type(await screen.findByLabelText('Email'), 'admin@fl-healthcare.demo')
    await userEvent.type(screen.getByLabelText('Password'), 'wrong')
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Incorrect email or password.')
    expect(window.location.pathname).toBe('/login')
  })

  it('fills the email from a demo account and explains that reset is not available in demo mode', async () => {
    open('/login')
    await userEvent.click(await screen.findByRole('button', { name: 'Use' }))
    expect(screen.getByLabelText('Email')).toHaveValue('admin@fl-healthcare.demo')
    await userEvent.click(screen.getByRole('button', { name: 'Forgot password?' }))
    await userEvent.click(screen.getByRole('button', { name: 'Send reset link' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(/not available for demo accounts/)
  })

  it('restores a saved session and renders the requested page', async () => {
    signedInAs(adminUser)
    open('/')
    expect(await screen.findByRole('heading', { name: 'Dashboard' })).toBeInTheDocument()
    expect(screen.getByText('Demo Administrator')).toBeInTheDocument()
  })

  it('returns to sign-in when the saved session is no longer valid', async () => {
    sessionStorage.setItem('fl-healthcare.demo-token', 'expired')
    api.me.mockRejectedValue(new ApiError('unauthorized', 'Your session has expired. Sign in again.', 401))
    open('/')
    expect(await screen.findByRole('heading', { name: 'Sign in' })).toBeInTheDocument()
    expect(sessionStorage.getItem('fl-healthcare.demo-token')).toBeNull()
  })

  it('signs out', async () => {
    signedInAs(adminUser)
    open('/')
    await userEvent.click(await screen.findByRole('button', { name: /Sign out/ }))
    expect(await screen.findByRole('heading', { name: 'Sign in' })).toBeInTheDocument()
  })

  it('shows every section in the navigation and a not-found page for unknown addresses', async () => {
    signedInAs(adminUser)
    open('/no-such-page')
    expect(await screen.findByText('This page does not exist')).toBeInTheDocument()
    const nav = screen.getByRole('navigation', { name: 'Main' })
    for (const label of [
      'Dashboard',
      'Hospitals',
      'Federated Learning',
      'Models',
      'Disease Surveillance',
      'Forecasting',
      'Explainability',
      'Audit Logs',
      'Settings',
    ]) {
      expect(within(nav).getByRole('link', { name: label })).toBeInTheDocument()
    }
  })

  it('says so, with Retry, when the server cannot be reached at all', async () => {
    api.systemConfig.mockRejectedValueOnce(new ApiError('unavailable', 'The server could not be reached.'))
    open('/')
    expect(await screen.findByText('Server unavailable')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Retry' }))
    expect(await screen.findByRole('heading', { name: 'Sign in' })).toBeInTheDocument()
  })
})

describe('creating an account', () => {
  async function openSignUp() {
    open('/login')
    await userEvent.click(await screen.findByRole('button', { name: 'Create an account' }))
    expect(screen.getByRole('heading', { name: 'Create your account' })).toBeInTheDocument()
  }

  async function fill({ password = 'correct horse 42', confirm = password } = {}) {
    await userEvent.type(screen.getByLabelText('Name'), 'Priya N')
    await userEvent.type(screen.getByLabelText('Email'), 'priya@example.org')
    await userEvent.type(screen.getByLabelText('Password'), password)
    await userEvent.type(screen.getByLabelText('Confirm password'), confirm)
    await userEvent.click(screen.getByRole('button', { name: 'Create account' }))
  }

  it('creates the account, signs it in and says up front that it is not an administrator account', async () => {
    api.register.mockResolvedValue({ access_token: 'new', token_type: 'bearer', expires_in: 3600, user: signedUpUser })
    await openSignUp()
    expect(screen.getByText('Administrator accounts cannot be created here.')).toBeInTheDocument()
    await fill()

    expect(await screen.findByRole('heading', { name: 'Dashboard' })).toBeInTheDocument()
    expect(api.register).toHaveBeenCalledWith('priya@example.org', 'correct horse 42', 'Priya N')
    expect(sessionStorage.getItem('fl-healthcare.demo-token')).toBe('new')
    expect(screen.getAllByText('Viewer').length).toBeGreaterThanOrEqual(1)
  })

  it('checks the password before asking the server', async () => {
    await openSignUp()
    await fill({ password: 'short' })
    expect(await screen.findByRole('alert')).toHaveTextContent('at least 8 characters')
    await userEvent.clear(screen.getByLabelText('Password'))
    await userEvent.clear(screen.getByLabelText('Confirm password'))
    await userEvent.type(screen.getByLabelText('Password'), 'correct horse 42')
    await userEvent.type(screen.getByLabelText('Confirm password'), 'correct horse 43')
    await userEvent.click(screen.getByRole('button', { name: 'Create account' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('do not match')
    expect(api.register).not.toHaveBeenCalled()
  })

  it('shows why the server refused, and stays on the form', async () => {
    api.register.mockRejectedValue(new ApiError('conflict', 'An account with this email already exists. Sign in instead.', 409))
    await openSignUp()
    await fill()
    expect(await screen.findByRole('alert')).toHaveTextContent('already exists')
    expect(window.location.pathname).toBe('/login')
  })

  it('does not offer sign-up when the server has it switched off', async () => {
    api.systemConfig.mockResolvedValue({ ...systemConfig, signup_enabled: false })
    open('/login')
    expect(await screen.findByText('Need an account? Ask an administrator.')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Create an account' })).not.toBeInTheDocument()
  })
})

describe('dashboard', () => {
  it('shows dashes, not invented numbers, before any round has run', async () => {
    signedInAs(adminUser)
    open('/')
    const hospitalsStat = (await screen.findByText('Participating hospitals')).closest('div').parentElement
    expect(within(hospitalsStat).getByText('4')).toBeInTheDocument()
    const roundsStat = screen.getByText('FL rounds').closest('div').parentElement
    expect(within(roundsStat).getByText('—')).toBeInTheDocument()
    expect(within(roundsStat).getByText('No rounds run yet')).toBeInTheDocument()
    expect(screen.getByText('No rounds have been run')).toBeInTheDocument()
    expect(screen.getByText('Shown after the first completed round.')).toBeInTheDocument()
    expect(screen.queryByText(/%/)).not.toBeInTheDocument()
  })

  it('labels simulated data', async () => {
    signedInAs(adminUser)
    open('/')
    await screen.findByText('Participating hospitals')
    expect(screen.getAllByText('SIMULATED / DEMONSTRATION DATA').length).toBeGreaterThanOrEqual(1)
  })

  it('shows real metrics once a model is trained', async () => {
    signedInAs(adminUser)
    api.overview.mockResolvedValue(trainedOverview)
    open('/')
    const performance = (await screen.findByText('Global model performance')).closest('div').parentElement
    expect(within(performance).getByText('48.2%')).toBeInTheDocument()
    const roundsStat = screen.getByText('FL rounds').closest('div').parentElement
    expect(within(roundsStat).getByText('2')).toBeInTheDocument()
    expect(within(roundsStat).getByText(/1 failed/)).toBeInTheDocument()
  })

  it('says a section is unavailable instead of leaving it blank', async () => {
    signedInAs(adminUser)
    open('/')
    expect(await screen.findByText('Surveillance data is not available')).toBeInTheDocument()
    expect(screen.getByText('No aggregated surveillance reports are configured.')).toBeInTheDocument()
  })

  it('shows an error with Retry when the summary cannot be loaded, then recovers', async () => {
    signedInAs(adminUser)
    api.overview.mockRejectedValueOnce(new ApiError('server', 'The server hit an unexpected error.', 500))
    open('/')
    expect(await screen.findByText('Unable to retrieve the dashboard summary.')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Retry' }))
    expect(await screen.findByText('Participating hospitals')).toBeInTheDocument()
    expect(api.overview).toHaveBeenCalledTimes(2)
  })
})

describe('roles', () => {
  it('shows a viewer that the audit log is restricted', async () => {
    signedInAs(viewerUser)
    api.audit.mockRejectedValue(
      new ApiError('forbidden', 'Your role (viewer) does not allow this action. Required: admin or coordinator.', 403),
    )
    open('/audit')
    expect(await screen.findByText('You do not have access to this')).toBeInTheDocument()
    expect(screen.getByText(/Required: admin or coordinator/)).toBeInTheDocument()
  })

  it('does not offer a viewer the Start new round button', async () => {
    signedInAs(viewerUser)
    open('/federated')
    expect(await screen.findByText('Your role can follow rounds but not start them.')).toBeInTheDocument()
    await waitFor(() => expect(api.rounds).toHaveBeenCalled())
    expect(screen.queryByRole('button', { name: /Start new round/ })).not.toBeInTheDocument()
  })

  it("lets an administrator change another user's role, but not their own or a locked one", async () => {
    signedInAs(adminUser)
    api.privacy.mockRejectedValue(new ApiError('unavailable', 'not needed here'))
    api.users.mockResolvedValue(managedUsers)
    api.setUserRole.mockResolvedValue({ ...managedUsers[1], role: 'coordinator' })
    open('/settings')

    const select = await screen.findByLabelText('Role for priya@example.org')
    expect(select).toHaveValue('viewer')
    expect(screen.queryByLabelText('Role for admin@fl-healthcare.demo')).not.toBeInTheDocument()
    expect(screen.getByText('You cannot change your own role.')).toBeInTheDocument()

    await userEvent.selectOptions(select, 'coordinator')
    expect(api.setUserRole).toHaveBeenCalledWith('local-1', 'coordinator')
    expect(await screen.findByText('priya@example.org is now FL coordinator.')).toBeInTheDocument()
    await waitFor(() => expect(api.users).toHaveBeenCalledTimes(2))
  })

  it('does not show user management to anyone but an administrator', async () => {
    signedInAs(viewerUser)
    api.privacy.mockRejectedValue(new ApiError('unavailable', 'not needed here'))
    open('/settings')
    expect(await screen.findByRole('heading', { name: 'Settings' })).toBeInTheDocument()
    expect(screen.queryByText('Users and roles')).not.toBeInTheDocument()
    expect(api.users).not.toHaveBeenCalled()
  })
})
