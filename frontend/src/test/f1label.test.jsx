/** The round page says which F1 it shows: positive class for EHR, macro average for ECG. */
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { ParticipantsTable } from '../pages/FederatedLearning'
import { startedRound } from './fixtures'

describe('Local model F1 label', () => {
  it('names the positive class for EHR, with the full definition as a tooltip', () => {
    render(<ParticipantsTable round={{ ...startedRound, modality: 'ehr' }} />)
    const label = screen.getByText('Local model F1, adverse outcome')
    expect(label).toHaveAttribute('title', 'F1 of the positive class (adverse outcome), at the 0.5 threshold')
  })

  it('says macro average for ECG', () => {
    render(<ParticipantsTable round={{ ...startedRound, modality: 'ecg' }} />)
    expect(screen.getByText('Local model F1, macro average')).toBeInTheDocument()
  })
})
