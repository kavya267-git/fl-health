/** Health officer pages: situation report sentences, the forecast panel, exports and the alert workflow. */
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { messageFiles, translate } from '../i18n'
import Alerts from '../pages/Alerts'
import SituationReport, { regionSentences } from '../pages/SituationReport'
import { api } from '../services/endpoints'

const auth = vi.hoisted(() => ({ user: null }))
vi.mock('../context/AuthContext', () => ({ useAuth: () => auth }))

vi.mock('../services/endpoints', () => ({
  api: { situation: vi.fn(), downloadSituation: vi.fn(), alerts: vi.fn(), acknowledgeAlert: vi.fn(), recordAlertOutcome: vi.fn() },
}))

const t = (key, values) => translate('en', key, values)
const WATERMARK = 'SIMULATED DATA – NOT REAL CASES'

const region = (overrides = {}) => ({
  region_id: 'R01',
  region_name: 'North Valley',
  case_count: 42,
  case_rate: null,
  usual_level: 23.4,
  ratio_to_usual: 1.79,
  status: 'ELEVATED',
  status_label: 'Elevated',
  reporting_hospitals: 3,
  expected_hospitals: 4,
  forecast: { available: true, summary: { horizons: [2, 3, 4], predicted_low: 30.2, predicted_high: 38.4, range_low: 20.1, range_high: 51.2 } },
  ...overrides,
})

const report = (about = { available: false, ready: false, running: true }) => ({
  generated_at: '2026-11-04T08:00:00+00:00',
  jurisdiction: ['R01'],
  data_status: { simulated: true, label: 'SIMULATED', watermark: WATERMARK },
  likely_range_note: 'Likely range (based on past errors; often too narrow)',
  about_forecast: about,
  diseases: [
    {
      disease: { id: 'dengue', label: 'Dengue' },
      week: { label: '2026-W44', week_start: '2026-10-26', week_end: '2026-11-01' },
      summary: { CANDIDATE_HOTSPOT: 0, ELEVATED: 1, NORMAL: 0, INSUFFICIENT_DATA: 0 },
      regions: [region()],
    },
  ],
})

function asUser(role, ui) {
  auth.user = { email: 'o@example.org', role }
  return render(ui)
}

beforeEach(() => vi.resetAllMocks())

describe('situation report text', () => {
  it('describes a region in plain sentences from the numbers only', () => {
    expect(regionSentences(region(), t)).toEqual([
      '42 cases this week.',
      'That is 1.8 times the usual level of about 23 a week.',
      'Expected in 2 to 4 weeks: about 30 to 38 a week (likely range 20 to 51).',
      '3 of 4 hospitals reported this week.',
    ])
  })

  it('says what is missing instead of inventing a number', () => {
    const lines = regionSentences(
      region({ case_count: null, ratio_to_usual: null, usual_level: null, forecast: { available: false, reason: 'The forecast is still being computed.' } }),
      t,
    )
    expect(lines[0]).toMatch(/not available/)
    expect(lines).toContain('The forecast is still being computed.')
  })

  it('never uses the word outbreak', () => {
    for (const messages of Object.values(messageFiles)) {
      for (const text of Object.values(messages)) expect(text).not.toMatch(/outbreak/i)
    }
  })
})

describe('situation report page', () => {
  it('shows the watermark, the sentences and that the forecast is still being computed', async () => {
    api.situation.mockResolvedValue(report())
    render(<SituationReport />)
    expect(await screen.findByTestId('situation-watermark')).toHaveTextContent(WATERMARK)
    expect(screen.getByText('42 cases this week.')).toBeInTheDocument()
    expect(screen.getByText(/still being computed\. It runs in the background/)).toBeInTheDocument()
  })

  it('shows the weights and data date in "About this forecast"', async () => {
    api.situation.mockResolvedValue(
      report({
        available: true,
        computed_at: '2026-11-04T07:00:00+00:00',
        data_through: '2026-10-26',
        validation_window: { first_week: '2026-06-15', last_week: '2026-10-26', weeks: 20 },
        members: ['arima_statsmodels', 'prophet', 'lstm'],
        member_labels: { arima_statsmodels: 'ARIMA(2,1,1)', prophet: 'Prophet', lstm: 'LSTM (global)' },
        weights: { 1: { arima_statsmodels: 0.5, prophet: 0.25, lstm: 0.25 } },
      }),
    )
    render(<SituationReport />)
    const panel = (await screen.findByText('About this forecast')).closest('section')
    expect(within(panel).getByText(/ARIMA\(2,1,1\) 50%, Prophet 25%, LSTM \(global\) 25%/)).toBeInTheDocument()
    expect(within(panel).getByText(/20 most recent weeks/)).toBeInTheDocument()
    expect(within(panel).getByText('Likely range (based on past errors; often too narrow).')).toBeInTheDocument()
  })

  it('downloads the CSV and PDF exports', async () => {
    api.situation.mockResolvedValue(report())
    api.downloadSituation.mockResolvedValue('SIMULATED-situation-report.csv')
    render(<SituationReport />)
    await userEvent.click(await screen.findByRole('button', { name: 'Download CSV' }))
    expect(api.downloadSituation).toHaveBeenCalledWith('csv')
    expect(await screen.findByText('Downloaded SIMULATED-situation-report.csv.')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Download PDF' }))
    expect(api.downloadSituation).toHaveBeenCalledWith('pdf')
  })
})

const alert = (overrides = {}) => ({
  id: 7,
  region_id: 'R01',
  region_name: 'North Valley',
  disease: 'dengue',
  disease_label: 'Dengue',
  week_start: '2026-10-19',
  week_label: '2026-W43',
  state: 'OPEN',
  case_count: 51,
  usual_level: 20,
  is_simulated: true,
  acknowledged_by: null,
  acknowledged_at: null,
  outcome: null,
  ...overrides,
})

describe('alerts', () => {
  it('lets a health officer acknowledge an open alert', async () => {
    api.alerts.mockResolvedValue([alert()])
    api.acknowledgeAlert.mockResolvedValue(alert({ state: 'ACKNOWLEDGED' }))
    asUser('health_officer', <Alerts />)
    expect(await screen.findByText('Dengue in North Valley, week 2026-W43: 51 cases against a usual 20.')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Acknowledge' }))
    expect(api.acknowledgeAlert).toHaveBeenCalledWith(7)
    expect(api.alerts).toHaveBeenCalledTimes(2)
  })

  it('asks for an outcome and a note before saving', async () => {
    api.alerts.mockResolvedValue([alert({ state: 'ACKNOWLEDGED', acknowledged_by: 'o@example.org', acknowledged_at: '2026-11-04T08:00:00+00:00' })])
    api.recordAlertOutcome.mockResolvedValue(alert({ state: 'CLOSED' }))
    asUser('health_officer', <Alerts />)
    const save = await screen.findByRole('button', { name: 'Save outcome' })
    expect(save).toBeDisabled()
    await userEvent.selectOptions(screen.getByLabelText('What did you find?'), 'NOT_CONFIRMED')
    expect(save).toBeDisabled()
    await userEvent.type(screen.getByLabelText('Note (how you checked)'), 'Called the district hospital')
    await userEvent.click(save)
    expect(api.recordAlertOutcome).toHaveBeenCalledWith(7, 'NOT_CONFIRMED', 'Called the district hospital')
  })

  it('shows alerts read-only to a coordinator', async () => {
    api.alerts.mockResolvedValue([alert(), alert({ id: 8, state: 'ACKNOWLEDGED' })])
    asUser('coordinator', <Alerts />)
    await screen.findAllByText(/Dengue in North Valley/)
    expect(screen.queryByRole('button', { name: 'Acknowledge' })).toBeNull()
    expect(screen.queryByRole('button', { name: 'Save outcome' })).toBeNull()
  })
})
