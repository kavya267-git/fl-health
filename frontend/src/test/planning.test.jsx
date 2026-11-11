/** Resource planning page: the plain sentences, highlighted weeks, assumptions label and the capacity form. */
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import ResourcePlanning, { groupSentence } from '../pages/ResourcePlanning'
import { api } from '../services/endpoints'

const auth = vi.hoisted(() => ({ user: null }))
vi.mock('../context/AuthContext', () => ({ useAuth: () => auth }))
vi.mock('../services/endpoints', () => ({ api: { planning: vi.fn(), setCapacity: vi.fn(), hospitals: vi.fn(), planningAssumptions: vi.fn() } }))

const WATERMARK = 'SIMULATED DATA – NOT REAL CASES'

// The worked example of docs/resource-planning.md: 40 beds, 30 in use, weeks 2-4 may exceed them.
const weeks = [
  { horizon: 1, beds: [4, 5, 6.5], total: [34, 36.5], over: false },
  { horizon: 2, beds: [6.214286, 8.142857, 10.785714], total: [36.214286, 40.785714], over: true },
  { horizon: 3, beds: [6.928571, 9.571429, 12.928571], total: [36.928571, 42.928571], over: true },
  { horizon: 4, beds: [5.642857, 8, 11.071429], total: [35.642857, 41.071429], over: true },
].map((w) => ({
  horizon: w.horizon,
  week_start: `2026-11-0${w.horizon + 1}`,
  label: `2026-W4${4 + w.horizon}`,
  admissions_low: 4,
  admissions_high: 9.5,
  beds_low: w.beds[0],
  beds_mid: w.beds[1],
  beds_high: w.beds[2],
  total_beds_low: w.total[0],
  total_beds_high: w.total[1],
  icu_total_high: 3 + w.beds[2] / 10,
  over_capacity: w.over,
  icu_over_capacity: 3 + w.beds[2] / 10 > 4,
}))
const groups = [
  { first_week: 1, last_week: 1, over_capacity: false, total_low: 34, total_high: 36.5, beds_low: 4, beds_high: 6.5 },
  { first_week: 2, last_week: 4, over_capacity: true, total_low: 35.642857, total_high: 42.928571, beds_low: 5.642857, beds_high: 12.928571 },
]

const plan = (overrides = {}) => ({
  available: true,
  hospital: { id: 'hospital_a', name: 'Northfield General Hospital' },
  label: 'Planning estimate',
  capacity: { id: 1, total_beds: 40, icu_beds: 4, occupancy_percent: 75, entered_at: '2026-11-10T08:00:00+00:00', entered_by: 'manager_a@fl-healthcare.demo' },
  assumptions: [
    { disease: 'dengue', disease_label: 'Dengue', admission_rate: 0.2, icu_share: 0.1, length_of_stay_days: 10, is_default: true, label: 'Assumed values, replace with local figures' },
  ],
  data_status: { simulated: true, label: 'SIMULATED', watermark: WATERMARK },
  current_beds_occupied: 30,
  forecast: { data_through: '2026-11-02', computed_at: '2026-11-10T07:00:00+00:00', level: 0.8 },
  diseases: [
    {
      disease: { id: 'dengue', label: 'Dengue' },
      available: true,
      regions: [{ region_id: 'R01', region_name: 'Ashgrove', share: 0.25 }],
      missing_regions: [],
      assumptions: {},
      weeks,
      groups,
    },
  ],
  all_diseases: weeks.map((w) => ({ horizon: w.horizon, total_low: w.total_beds_low, total_high: w.total_beds_high, over_capacity: w.over_capacity })),
  ...overrides,
})

beforeEach(() => {
  vi.resetAllMocks()
  auth.user = { email: 'manager_a@fl-healthcare.demo', role: 'hospital_manager', hospital_id: 'hospital_a' }
})

describe('plain sentences', () => {
  it('says which weeks may need more beds than the hospital has, with the range', () => {
    expect(groupSentence(groups[1], 'Dengue', 40)).toBe(
      'Weeks 2–4: if the rest of the hospital stays as busy as today, with the expected dengue patients, you may need 36–43 of your 40 beds. That could be more than you have.',
    )
    expect(groupSentence(groups[0], 'Dengue', 40)).toBe(
      'Week 1: if the rest of the hospital stays as busy as today, with the expected dengue patients, you may need 34–37 of your 40 beds.',
    )
  })
})

describe('resource planning page', () => {
  it('highlights the weeks that may exceed the beds and labels everything as an estimate', async () => {
    api.planning.mockResolvedValue(plan())
    render(<ResourcePlanning />)
    expect(await screen.findByText(/Weeks 2–4: if the rest of the hospital/)).toBeInTheDocument()
    expect(screen.getAllByText('Planning estimate').length).toBeGreaterThan(0)
    expect(screen.getByText(WATERMARK)).toBeInTheDocument()
    expect(screen.getByTestId('assumed-label')).toHaveTextContent('Assumed values, replace with local figures')
    const rows = document.querySelectorAll('tr[data-over]')
    expect([...rows].map((r) => r.getAttribute('data-over'))).toEqual(['false', 'true', 'true', 'true'])
    expect(screen.getByText('Ashgrove 25%', { exact: false })).toBeInTheDocument()
  })

  it('names the home district when the catchment is the home district', async () => {
    api.planning.mockResolvedValue(
      plan({
        catchment: { basis: 'home_district', region_id: 'KA-DHARWAD', region_name: 'Dharwad', share: 1, hospitals_sharing: 1 },
        diseases: [{ ...plan().diseases[0], regions: [{ region_id: 'KA-DHARWAD', region_name: 'Dharwad', share: 1 }] }],
      }),
    )
    render(<ResourcePlanning />)
    expect(await screen.findByText('Catchment: your home district, Dharwad (100% of its cases).')).toBeInTheDocument()
    expect(screen.getByText(/your hospital's catchment \(its home district, Dharwad\)/)).toBeInTheDocument()
    expect(screen.queryByText(/Your share of cases \(last 8 weeks\)/)).not.toBeInTheDocument()
  })

  it('explains what is missing instead of showing an estimate', async () => {
    api.planning.mockResolvedValue(plan({ available: false, capacity: null, reason: "Enter your hospital's beds and current occupancy to see the projection." }))
    render(<ResourcePlanning />)
    expect(await screen.findByText("Enter your hospital's beds and current occupancy to see the projection.")).toBeInTheDocument()
  })

  it('saves the capacity form', async () => {
    api.planning.mockResolvedValue(plan({ available: false, capacity: null, reason: 'Enter your beds.' }))
    api.setCapacity.mockResolvedValue({ total_beds: 40 })
    render(<ResourcePlanning />)
    await userEvent.type(await screen.findByLabelText('Total beds'), '40')
    await userEvent.type(screen.getByLabelText('ICU beds'), '4')
    await userEvent.type(screen.getByLabelText('Beds in use now (%)'), '75')
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))
    expect(api.setCapacity).toHaveBeenCalledWith({ total_beds: 40, icu_beds: 4, occupancy_percent: 75 })
    expect(api.planning).toHaveBeenCalledTimes(2)
  })
})
