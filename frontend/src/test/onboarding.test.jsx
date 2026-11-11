/** Hospital onboarding screens: public registration, the administrators' review, and "Connect your hospital". */
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ConnectHospital } from '../components/hospital/ConnectHospital'
import { HOSPITAL_REQUESTS, navItemsFor } from '../components/layout/navigation'
import HospitalRequests from '../pages/HospitalRequests'
import RegisterHospital, { CONFIRMATION } from '../pages/RegisterHospital'
import { api } from '../services/endpoints'
import { AGENT_DOWNLOAD_URL } from '../utils/constants'

vi.mock('../services/endpoints', () => ({
  api: {
    registrationRegions: vi.fn(),
    submitRegistration: vi.fn(),
    registrations: vi.fn(),
    approveRegistration: vi.fn(),
    rejectRegistration: vi.fn(),
    revokeRegistration: vi.fn(),
    generateNodeToken: vi.fn(),
    downloadDataTemplate: vi.fn(),
  },
}))

beforeEach(() => vi.resetAllMocks())

const inRouter = (ui) => render(<MemoryRouter>{ui}</MemoryRouter>)

describe('Register your hospital', () => {
  beforeEach(() => api.registrationRegions.mockResolvedValue([{ region_id: 'R03', name: 'Calderwick' }]))

  async function fill(user) {
    await user.type(screen.getByLabelText('Hospital name'), 'Test City Hospital')
    await user.selectOptions(await screen.findByLabelText('Region'), 'R03')
    await user.type(screen.getByLabelText('Contact name'), 'Asha Rao')
    await user.type(screen.getByLabelText('Contact email'), 'ops@testcity.example')
    await user.type(screen.getByLabelText('Password'), 'city-hospital-pass')
    await user.type(screen.getByLabelText('Confirm password'), 'city-hospital-pass')
    await user.click(screen.getByRole('checkbox', { name: /ECG/ }))
    await user.type(screen.getByLabelText('Approximate number of ECG records'), '500')
  }

  it('cannot be sent until the no-patient-data box is ticked, then sends exactly the form', async () => {
    const user = userEvent.setup()
    api.submitRegistration.mockResolvedValue({ id: 'reg-1', status: 'PENDING', hospital_name: 'Test City Hospital' })
    inRouter(<RegisterHospital />)
    await screen.findByRole('option', { name: 'Calderwick' })
    await fill(user)
    const send = screen.getByRole('button', { name: 'Send request' })
    expect(send).toBeDisabled()
    await user.click(screen.getByRole('checkbox', { name: CONFIRMATION }))
    await user.click(send)
    await waitFor(() => expect(api.submitRegistration).toHaveBeenCalledTimes(1))
    expect(api.submitRegistration.mock.calls[0][0]).toEqual({
      hospital_name: 'Test City Hospital',
      region_id: 'R03',
      contact_name: 'Asha Rao',
      contact_email: 'ops@testcity.example',
      password: 'city-hospital-pass',
      password_confirm: 'city-hospital-pass',
      modalities: ['ecg'],
      approx_record_counts: { ecg: 500 },
      confirm_no_patient_data: true,
    })
    expect(await screen.findByText('Request received')).toBeInTheDocument()
    expect(screen.getByText(/waiting for an administrator/)).toBeInTheDocument()
  })

  it('has no file upload and checks the passwords before sending', async () => {
    const user = userEvent.setup()
    const { container } = inRouter(<RegisterHospital />)
    expect(container.querySelector('input[type="file"]')).toBeNull()
    await screen.findByRole('option', { name: 'Calderwick' })
    await fill(user)
    await user.clear(screen.getByLabelText('Confirm password'))
    await user.type(screen.getByLabelText('Confirm password'), 'something-else')
    await user.click(screen.getByRole('checkbox', { name: CONFIRMATION }))
    await user.click(screen.getByRole('button', { name: 'Send request' }))
    expect(await screen.findByText('The two passwords do not match.')).toBeInTheDocument()
    expect(api.submitRegistration).not.toHaveBeenCalled()
  })
})

const pending = {
  id: 'reg-1',
  hospital_name: 'Test City Hospital',
  region_id: 'R03',
  region_name: 'Calderwick',
  contact_name: 'Asha Rao',
  contact_email: 'ops@testcity.example',
  modalities: ['ecg'],
  approx_record_counts: { ecg: 500 },
  status: 'PENDING',
  created_at: '2026-11-11T10:00:00+00:00',
}

describe('Hospital requests', () => {
  it('approves a pending request', async () => {
    const user = userEvent.setup()
    api.registrations.mockResolvedValue([pending])
    api.approveRegistration.mockResolvedValue({ ...pending, status: 'APPROVED' })
    inRouter(<HospitalRequests />)
    expect(await screen.findByText('Test City Hospital')).toBeInTheDocument()
    expect(screen.getByText(/ECG ~500/)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Approve' }))
    expect(api.approveRegistration).toHaveBeenCalledWith('reg-1')
  })

  it('needs a reason to reject', async () => {
    const user = userEvent.setup()
    api.registrations.mockResolvedValue([pending])
    api.rejectRegistration.mockResolvedValue({ ...pending, status: 'REJECTED' })
    inRouter(<HospitalRequests />)
    await user.click(await screen.findByRole('button', { name: 'Reject' }))
    const dialog = screen.getByRole('dialog')
    const confirm = within(dialog).getByRole('button', { name: 'Reject' })
    expect(confirm).toBeDisabled()
    await user.type(within(dialog).getByLabelText('Reason'), 'Not a hospital')
    await user.click(confirm)
    expect(api.rejectRegistration).toHaveBeenCalledWith('reg-1', 'Not a hospital')
  })

  it('is in the administrator navigation only', () => {
    expect(navItemsFor({ role: 'admin' })).toContainEqual(HOSPITAL_REQUESTS)
    for (const role of ['coordinator', 'viewer', 'hospital', 'hospital_manager', 'researcher', 'health_officer']) {
      expect(navItemsFor({ role, hospital_id: 'hospital_a', jurisdiction: ['R01'] }).map((i) => i.to)).not.toContain('/hospital-requests')
    }
  })
})

const connection = {
  registered: true,
  step: 'NOT_CONNECTED',
  token: null,
  node: null,
  declared_modalities: ['ecg'],
  data_check: {},
  invited_modalities: [],
  node_mode: 'external',
  server_url: 'https://api.medifed.example',
}

describe('Connect your hospital', () => {
  it('shows a new token once, with a copy button, and offers the agent and the template', async () => {
    const user = userEvent.setup()
    api.generateNodeToken.mockResolvedValue({ token: 'tok-123', hospital_id: 'hospital_test_city_hospital' })
    const onChanged = vi.fn()
    inRouter(<ConnectHospital connection={connection} onChanged={onChanged} />)
    expect(screen.getByRole('link', { name: /Download MediFed Hospital Agent for Windows/ })).toHaveAttribute('href', AGENT_DOWNLOAD_URL)
    expect(screen.queryByText(/git clone/i)).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Generate node token' }))
    expect(await screen.findByTestId('node-token')).toHaveTextContent('tok-123')
    expect(screen.getByText('Copy this token now. It is shown only once.')).toBeInTheDocument()
    expect(onChanged).toHaveBeenCalled()
    await user.click(screen.getByRole('button', { name: 'Download data template' }))
    expect(api.downloadDataTemplate).toHaveBeenCalled()
    expect(screen.getByText('https://api.medifed.example')).toBeInTheDocument()
  })

  it('walks the live status from not connected to invited', () => {
    const invited = {
      ...connection,
      step: 'INVITED',
      token: { created_at: '2026-11-11T10:00:00+00:00', created_by: 'ops@testcity.example', revoked_at: null },
      node: { connected: true, hostname: 'TESTCITY-PC', ml_backend: 'pytorch', device: 'cpu', last_seen_at: '2026-11-11T10:05:00+00:00' },
      data_check: { ecg: { passed: true, train_records: 375, val_records: 125, problems: [] } },
      invited_modalities: ['ecg'],
    }
    inRouter(<ConnectHospital connection={invited} onChanged={() => {}} />)
    const steps = screen.getByRole('list', { name: 'Connection status' })
    expect(within(steps).getByText('Invited to rounds').closest('li')).toHaveAttribute('aria-current', 'step')
    expect(screen.getByText('TESTCITY-PC')).toBeInTheDocument()
    expect(screen.getByText('Passed')).toBeInTheDocument()
    expect(screen.getByText('375 / 125')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Generate a new node token' })).toBeInTheDocument()
  })

  it('lists the problems of a failed local check', () => {
    const failed = { ...connection, step: 'CONNECTED', data_check: { ecg: { passed: false, train_records: 3, val_records: 0, problems: ['train: 3 record(s); at least 8 are needed'] } } }
    inRouter(<ConnectHospital connection={failed} onChanged={() => {}} />)
    expect(screen.getByText('Failed')).toBeInTheDocument()
    expect(screen.getByText(/at least 8 are needed/)).toBeInTheDocument()
  })
})
