/**
 * The new roles in the dashboard: what each one sees in the sidebar, where it lands, and how an administrator
 * gives a health officer a jurisdiction. The server enforces the rules (backend/tests/test_permissions.py);
 * these tests check that the dashboard does not offer what the server would refuse.
 */
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import App from '../App'
import { navItemsFor } from '../components/layout/navigation'
import { api } from '../services/endpoints'
import { ROLE_LABELS, ROLE_ORDER, canChangeParticipation, canOpenHospitalDetails, homePathFor } from '../utils/constants'
import { adminUser, analyticsOptions, emptyOverview, managedUsers, systemConfig, viewerUser } from './fixtures'

vi.mock('../services/endpoints', () => ({
  api: {
    systemConfig: vi.fn(),
    me: vi.fn(),
    overview: vi.fn(),
    hospitals: vi.fn(),
    rounds: vi.fn(),
    users: vi.fn(),
    setUserRole: vi.fn(),
    privacy: vi.fn(),
    analyticsOptions: vi.fn(),
    hotspots: vi.fn(),
    situation: vi.fn(),
  },
}))

const officer = { ...viewerUser, id: 'demo-officer-north', role: 'health_officer', jurisdiction: ['R01', 'R02'] }
const manager = { ...viewerUser, id: 'demo-manager-a', role: 'hospital_manager', hospital_id: 'hospital_a' }
const researcher = { ...viewerUser, id: 'demo-researcher', role: 'researcher' }

function open(path, user) {
  sessionStorage.setItem('fl-healthcare.demo-token', 'token-for-tests')
  api.me.mockResolvedValue(user)
  window.history.pushState({}, '', path)
  return render(<App />)
}

beforeEach(() => {
  vi.resetAllMocks()
  api.systemConfig.mockResolvedValue(systemConfig)
  api.overview.mockResolvedValue(emptyOverview)
  api.hospitals.mockResolvedValue([])
  api.rounds.mockResolvedValue([])
  api.analyticsOptions.mockResolvedValue(analyticsOptions)
  api.hotspots.mockReturnValue(new Promise(() => {}))
})

describe('roles in the sidebar', () => {
  const paths = (user) => navItemsFor(user).map((item) => item.to)

  it('has a label and a description for every role', () => {
    for (const role of ROLE_ORDER) expect(ROLE_LABELS[role]).toBeTruthy()
    expect(ROLE_ORDER).toEqual(expect.arrayContaining(['hospital_manager', 'health_officer', 'researcher']))
  })

  it('gives a health officer only the jurisdiction pages', () => {
    expect(paths(officer)).toEqual(['/situation', '/surveillance', '/alerts', '/forecasting', '/how-it-works', '/settings'])
    expect(navItemsFor(officer).find((item) => item.to === '/surveillance').label).toBe('Jurisdiction map')
    expect(homePathFor(officer)).toBe('/situation')
  })

  it('shows the situation report and alerts to administrators and coordinators, not to other roles', () => {
    for (const role of ['admin', 'coordinator']) expect(paths({ ...viewerUser, role })).toEqual(expect.arrayContaining(['/situation', '/alerts']))
    for (const user of [viewerUser, researcher, manager]) {
      expect(paths(user)).not.toContain('/situation')
      expect(paths(user)).not.toContain('/alerts')
    }
  })

  it("gives a hospital manager resource planning first, their hospital's page, but not the participation switch", () => {
    expect(paths(manager).slice(0, 2)).toEqual(['/planning', '/my-hospital'])
    expect(paths(manager)).not.toContain('/audit')
    expect(homePathFor(manager)).toBe('/planning')
    for (const user of [viewerUser, researcher, officer, { ...manager, role: 'hospital' }]) expect(paths(user)).not.toContain('/planning')
    expect(paths({ ...viewerUser, role: 'admin' })).toContain('/planning')
    expect(canChangeParticipation(manager)).toBe(false)
    expect(canChangeParticipation({ ...manager, role: 'hospital' })).toBe(true)
  })

  it('gives a researcher the read-only pages without the audit log or hospital details', () => {
    expect(paths(researcher)).not.toContain('/audit')
    expect(paths(researcher)).toContain('/surveillance')
    expect(canOpenHospitalDetails(researcher)).toBe(false)
    expect(canOpenHospitalDetails(viewerUser)).toBe(true)
  })
})

describe('health officer home', () => {
  it('sends a health officer from the dashboard address to the situation report, without asking for the overview', async () => {
    api.situation.mockReturnValue(new Promise(() => {}))
    open('/', officer)
    await screen.findByText(/Loading the situation report/)
    expect(window.location.pathname).toBe('/situation')
    expect(api.overview).not.toHaveBeenCalled()
  })
})

describe('assigning a jurisdiction', () => {
  it('asks for at least one region before a health officer role is saved', async () => {
    api.users.mockResolvedValue(managedUsers)
    api.privacy.mockReturnValue(new Promise(() => {}))
    api.setUserRole.mockResolvedValue({ ...managedUsers[1], role: 'health_officer', jurisdiction: ['R01', 'R02'] })
    open('/settings', adminUser)

    await userEvent.selectOptions(await screen.findByLabelText('Role for priya@example.org'), 'health_officer')
    expect(api.setUserRole).not.toHaveBeenCalled()
    const picker = screen.getByRole('group', { name: 'Jurisdiction for priya@example.org' })
    const save = within(picker).getByRole('button', { name: 'Save jurisdiction' })
    expect(save).toBeDisabled()

    const [first, second] = analyticsOptions.regions
    await userEvent.click(within(picker).getByLabelText(`${first.name} (${first.region_id})`))
    await userEvent.click(within(picker).getByLabelText(`${second.name} (${second.region_id})`))
    await userEvent.click(save)
    expect(api.setUserRole).toHaveBeenCalledWith('local-1', 'health_officer', null, [first.region_id, second.region_id])
    expect(await screen.findByText(/priya@example.org is now Health officer for R01, R02/)).toBeInTheDocument()
  })
})
