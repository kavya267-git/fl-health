/** The round page's update check: an Isolation Forest flag is shown as advisory, never as a rejection. */
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { ParticipantsTable } from '../pages/FederatedLearning'
import { startedRound } from './fixtures'

const flagged = {
  scored: true,
  flagged: true,
  score: 0.71,
  history_size: 12,
  relative_norm: 4.2,
  cosine_distance: 0.9,
  reason: "Unusual compared with earlier updates: its size is 4.2× this round's median. Still used in the average.",
}

function roundWith(screenings) {
  return {
    ...startedRound,
    status: 'COMPLETED',
    participants: startedRound.participants.map((p, i) => ({ ...p, status: 'EVALUATED', num_samples: 100, screening: screenings[i] })),
  }
}

describe('Update check', () => {
  it('flags an unusual update as advisory and says it was still used', () => {
    const typical = { ...flagged, flagged: false, reason: null, score: 0.4 }
    const notScored = { scored: false, flagged: false, score: null, reason: 'Not scored: 3 earlier update(s), 8 needed.' }
    render(<ParticipantsTable round={roundWith([flagged, typical, notScored, null])} />)
    expect(screen.getByText('Unusual')).toBeInTheDocument()
    expect(screen.getByText('Typical')).toBeInTheDocument()
    expect(screen.getByText('Not scored yet')).toBeInTheDocument()
    expect(screen.getByText('1 unusual update flagged (still used)')).toBeInTheDocument()
    expect(screen.getByText(/Anomaly score 0.71, compared with 12 earlier updates/)).toBeInTheDocument()
    expect(screen.getByText(/Nothing was rejected automatically/)).toBeInTheDocument()
  })

  it('shows no warning when nothing is flagged', () => {
    render(<ParticipantsTable round={roundWith([null, null, null, null])} />)
    expect(screen.queryByText(/unusual update/)).not.toBeInTheDocument()
  })
})
