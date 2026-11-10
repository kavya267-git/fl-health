/** Starting a round: the UI must wait for the server's confirmation. */
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { PipelineDiagram } from '../components/federated/PipelineDiagram'
import { StartRoundDialog } from '../components/federated/StartRoundDialog'
import { ApiError } from '../services/api'
import { api } from '../services/endpoints'
import { hospitals, startedRound } from './fixtures'

vi.mock('../services/endpoints', () => ({ api: { startRound: vi.fn() } }))

beforeEach(() => vi.resetAllMocks())

function renderDialog(overrides = {}) {
  const props = { modality: 'ehr', hospitals, onClose: vi.fn(), onStarted: vi.fn(), ...overrides }
  render(<StartRoundDialog {...props} />)
  return props
}

describe('StartRoundDialog', () => {
  it('does not report success until the server confirms the round', async () => {
    let confirm
    api.startRound.mockReturnValue(
      new Promise((resolve) => {
        confirm = resolve
      }),
    )
    const props = renderDialog()
    await userEvent.click(screen.getByRole('button', { name: 'Start round' }))

    expect(api.startRound).toHaveBeenCalledTimes(1)
    expect(props.onStarted).not.toHaveBeenCalled()
    expect(screen.getByRole('button', { name: 'Start round' })).toBeDisabled()

    confirm(startedRound)
    await waitFor(() => expect(props.onStarted).toHaveBeenCalledWith(startedRound))
  })

  it('sends the chosen settings', async () => {
    api.startRound.mockResolvedValue(startedRound)
    renderDialog()
    await userEvent.click(screen.getByLabelText('Harbourview Clinic'))
    await userEvent.click(screen.getByRole('button', { name: 'Start round' }))
    await waitFor(() => expect(api.startRound).toHaveBeenCalled())
    expect(api.startRound.mock.calls[0][0]).toMatchObject({
      modality: 'ehr',
      hospital_ids: ['hospital_a', 'hospital_b', 'hospital_c'],
      local_epochs: 2,
      batch_size: 32,
      learning_rate: 0.003,
      min_participants: 2,
      differential_privacy: { enabled: false, noise_multiplier: 0 },
    })
  })

  it('keeps the dialog open and shows the reason when the server refuses', async () => {
    api.startRound.mockRejectedValue(new ApiError('conflict', 'A EHR round is already in progress.', 409))
    const props = renderDialog()
    await userEvent.click(screen.getByRole('button', { name: 'Start round' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('A EHR round is already in progress.')
    expect(props.onStarted).not.toHaveBeenCalled()
    expect(props.onClose).not.toHaveBeenCalled()
    expect(screen.getByRole('button', { name: 'Start round' })).toBeEnabled()
  })

  it('cannot start with fewer hospitals than the minimum, and skips offline hospitals', async () => {
    const withOffline = hospitals.map((h, index) => (index === 3 ? { ...h, online: false } : h))
    renderDialog({ hospitals: withOffline })
    expect(screen.getByLabelText(/Harbourview Clinic/)).toBeDisabled()
    for (const name of ['Northfield General Hospital', 'Riverside Medical Centre']) {
      await userEvent.click(screen.getByLabelText(name))
    }
    expect(screen.getByText('Select at least 2 hospitals.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Start round' })).toBeDisabled()
  })

  it('reveals the differential-privacy settings only when enabled', async () => {
    renderDialog()
    expect(screen.queryByLabelText('Noise multiplier')).not.toBeInTheDocument()
    await userEvent.click(screen.getByLabelText(/Clip each update/))
    expect(screen.getByLabelText('Noise multiplier')).toBeInTheDocument()
    expect(screen.getByLabelText('Clip norm')).toBeInTheDocument()
  })

  it('offers simulated missing values for EHR only, off by default, and sends them as a share', async () => {
    api.startRound.mockResolvedValue(startedRound)
    renderDialog()
    const field = screen.getByLabelText('Simulated missing values (%)')
    expect(field).toHaveValue(0)
    await userEvent.clear(field)
    await userEvent.type(field, '10')
    await userEvent.click(screen.getByRole('button', { name: 'Start round' }))
    await waitFor(() => expect(api.startRound).toHaveBeenCalled())
    expect(api.startRound.mock.calls[0][0].simulated_missing_rate).toBeCloseTo(0.1)
  })

  it('does not offer simulated missing values for ECG', () => {
    renderDialog({ modality: 'ecg' })
    expect(screen.queryByLabelText('Simulated missing values (%)')).not.toBeInTheDocument()
  })
})

describe('PipelineDiagram', () => {
  it('shows the stages of a round and each hospital before any round exists', () => {
    render(<PipelineDiagram round={null} hospitals={hospitals} />)
    for (const text of ['Global model', 'FedAvg', 'New global model']) {
      expect(screen.getByText(text)).toBeInTheDocument()
    }
    for (const hospital of hospitals) expect(screen.getByText(hospital.name)).toBeInTheDocument()
  })

  it('reflects per-hospital progress and FedAvg weights from the round', () => {
    const round = {
      ...startedRound,
      status: 'COMPLETED',
      result_model_version: 1,
      updates_received: 4,
      config: {
        ...startedRound.config,
        aggregation: { coefficients: { hospital_a: 0.4, hospital_b: 0.3, hospital_c: 0.2, hospital_d: 0.1 } },
      },
      participants: startedRound.participants.map((p) => ({ ...p, status: 'EVALUATED', num_samples: 100 })),
    }
    render(<PipelineDiagram round={round} hospitals={hospitals} />)
    expect(screen.getByText('v1')).toBeInTheDocument()
    expect(screen.getByText(/FedAvg weight 40.0%/)).toBeInTheDocument()
    expect(screen.getByText('4 updates averaged by sample count')).toBeInTheDocument()
  })

  it('does not present a new model for a failed round', () => {
    const round = { ...startedRound, status: 'FAILED', error: 'Too few updates' }
    render(<PipelineDiagram round={round} hospitals={hospitals} />)
    expect(screen.getByText('Not created: the round failed')).toBeInTheDocument()
  })
})
