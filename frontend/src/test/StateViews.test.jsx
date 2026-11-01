import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { AsyncView, ErrorState, UnavailableState } from '../components/ui/StateViews'
import { ApiError } from '../services/api'

describe('ErrorState', () => {
  it('names what could not be retrieved and offers Retry', async () => {
    const onRetry = vi.fn()
    render(<ErrorState error={new ApiError('server', 'Database exploded', 500)} what="surveillance data" onRetry={onRetry} />)
    expect(screen.getByRole('alert')).toHaveTextContent('Unable to retrieve surveillance data.')
    expect(screen.getByText('Database exploded')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Retry' }))
    expect(onRetry).toHaveBeenCalledTimes(1)
  })

  it('explains an unreachable server', () => {
    render(<ErrorState error={new ApiError('unavailable', 'The server could not be reached.')} onRetry={() => {}} />)
    expect(screen.getByText('Server unavailable')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument()
  })

  it('does not offer Retry when the user lacks permission', () => {
    render(<ErrorState error={new ApiError('forbidden', 'Your role (viewer) does not allow this action.', 403)} onRetry={() => {}} />)
    expect(screen.getByText('You do not have access to this')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Retry' })).not.toBeInTheDocument()
  })

  it('flags a response it cannot read', () => {
    render(<ErrorState error={new ApiError('invalid_response', 'The server sent a response this page cannot read.')} onRetry={() => {}} />)
    expect(screen.getByText('Unexpected response')).toBeInTheDocument()
  })
})

describe('AsyncView', () => {
  const base = { reload: () => {}, data: null, error: null }

  it('shows a loading indicator', () => {
    render(
      <AsyncView state={{ ...base, status: 'loading' }} what="hospitals">
        {() => <p>content</p>}
      </AsyncView>,
    )
    expect(screen.getByRole('status')).toHaveTextContent('Loading hospitals')
    expect(screen.queryByText('content')).not.toBeInTheDocument()
  })

  it('shows the empty state', () => {
    render(
      <AsyncView state={{ ...base, status: 'empty', data: [] }} what="hospitals">
        {() => <p>content</p>}
      </AsyncView>,
    )
    expect(screen.getByText('No hospitals yet')).toBeInTheDocument()
  })

  it('renders children with the data on success', () => {
    render(
      <AsyncView state={{ ...base, status: 'success', data: { n: 4 } }} what="hospitals">
        {(data) => <p>{data.n} hospitals</p>}
      </AsyncView>,
    )
    expect(screen.getByText('4 hospitals')).toBeInTheDocument()
  })

  it('shows the error instead of the children', () => {
    render(
      <AsyncView state={{ ...base, status: 'error', error: new ApiError('server', 'boom', 500) }} what="hospitals">
        {() => <p>content</p>}
      </AsyncView>,
    )
    expect(screen.getByRole('alert')).toBeInTheDocument()
    expect(screen.queryByText('content')).not.toBeInTheDocument()
  })
})

describe('UnavailableState', () => {
  it('states the reason instead of showing placeholder values', () => {
    render(<UnavailableState title="No explanation available" reason="The global model has not been trained yet." />)
    expect(screen.getByText('No explanation available')).toBeInTheDocument()
    expect(screen.getByText('The global model has not been trained yet.')).toBeInTheDocument()
  })
})
