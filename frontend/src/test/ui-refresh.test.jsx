/**
 * The illustrations (sign-in, How it works, empty states) and the sidebar entry for How it works.
 */
import { render, screen, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import App from '../App'
import { NETWORK_IMAGE, WORLD_IMAGE } from '../assets/illustrations'
import { navItemsFor } from '../components/layout/navigation'
import { EmptyState } from '../components/ui/StateViews'
import { api } from '../services/endpoints'
import { ROLE_ORDER } from '../utils/constants'
import { adminUser, emptyOverview, systemConfig, viewerUser } from './fixtures'

vi.mock('../services/endpoints', () => ({
  api: {
    systemConfig: vi.fn(),
    me: vi.fn(),
    demoLogin: vi.fn(),
    overview: vi.fn(),
    hospitals: vi.fn(),
    rounds: vi.fn(),
    analyticsOptions: vi.fn(),
    hotspots: vi.fn(),
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
  api.hospitals.mockResolvedValue([])
  api.rounds.mockResolvedValue([])
})

describe('illustrations', () => {
  it('describes the network illustration and leaves the decorative one without alt text', () => {
    expect(NETWORK_IMAGE.alt).toMatch(/hospitals/i)
    expect(NETWORK_IMAGE.alt).toMatch(/model updates/i)
    expect(WORLD_IMAGE.alt).toBe('')
  })

  it('shows the network illustration with its alt text on the sign-in page', async () => {
    open('/login')
    await screen.findByRole('heading', { name: 'Sign in' })
    // One copy for wide screens, one cropped banner for small screens; CSS shows one of them.
    const images = screen.getAllByRole('img', { name: NETWORK_IMAGE.alt })
    expect(images).toHaveLength(2)
    expect(screen.getByText(/does not, on its own, guarantee privacy/)).toBeInTheDocument()
  })

  it('uses the world illustration in an empty state only when asked, as a decorative image', () => {
    const { container, rerender } = render(<EmptyState title="Nothing yet" illustration />)
    const image = container.querySelector('img')
    expect(image).toHaveAttribute('alt', '')
    expect(screen.queryByRole('img')).toBeNull() // alt="" keeps it out of the accessibility tree
    rerender(<EmptyState title="Nothing yet" />)
    expect(container.querySelector('img')).toBeNull()
  })
})

describe('How it works', () => {
  it('is in the sidebar for every role', () => {
    for (const role of ROLE_ORDER) {
      const user = { ...viewerUser, role, hospital_id: role === 'hospital' ? 'hospital_a' : null }
      expect(navItemsFor(user).map((item) => item.to)).toContain('/how-it-works')
    }
  })

  it('shows the illustration, four steps and what never leaves a hospital', async () => {
    signedInAs(viewerUser)
    open('/how-it-works')
    expect(await screen.findByRole('heading', { level: 1, name: 'How it works' })).toBeInTheDocument()
    expect(screen.getByRole('img', { name: NETWORK_IMAGE.alt })).toBeInTheDocument()

    const steps = within(screen.getByRole('list', { name: 'The four steps of a training round' })).getAllByRole('listitem')
    expect(steps).toHaveLength(4)
    expect(steps[1]).toHaveTextContent('Only model updates are sent')

    const box = screen.getByRole('complementary', { name: 'What never leaves a hospital' })
    expect(within(box).getByText('Patient records, names and identifiers')).toBeInTheDocument()
  })
})

describe('empty states with the illustration', () => {
  it('shows "No hospitals connected" when no hospital has registered', async () => {
    signedInAs(adminUser)
    const { container } = open('/hospitals')
    expect(await screen.findByText('No hospitals connected')).toBeInTheDocument()
    expect(container.querySelector(`img[src="${WORLD_IMAGE.src}"]`)).toHaveAttribute('alt', '')
  })

  it('shows "No rounds have been run" on the dashboard before the first round', async () => {
    signedInAs(adminUser)
    const { container } = open('/')
    expect(await screen.findByText('No rounds have been run')).toBeInTheDocument()
    expect(container.querySelector(`img[src="${WORLD_IMAGE.src}"]`)).not.toBeNull()
  })

  it('shows "No surveillance data yet" when there are no diseases or weeks to show', async () => {
    signedInAs(viewerUser)
    api.analyticsOptions.mockResolvedValue({ diseases: [], periods: [], latest_period: null })
    open('/surveillance')
    expect(await screen.findByText('No surveillance data yet')).toBeInTheDocument()
    expect(api.hotspots).not.toHaveBeenCalled()
  })
})
