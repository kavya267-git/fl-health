import { act, renderHook, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { useApi } from '../hooks/useApi'
import { ApiError } from '../services/api'

describe('useApi', () => {
  it('goes from loading to success', async () => {
    const { result } = renderHook(() => useApi(() => Promise.resolve({ value: 1 }), []))
    expect(result.current.status).toBe('loading')
    await waitFor(() => expect(result.current.status).toBe('success'))
    expect(result.current.data).toEqual({ value: 1 })
    expect(result.current.error).toBeNull()
  })

  it('reports an empty result separately from success', async () => {
    const { result } = renderHook(() => useApi(() => Promise.resolve([]), [], { isEmpty: (data) => data.length === 0 }))
    await waitFor(() => expect(result.current.status).toBe('empty'))
  })

  it('exposes the error kind and clears data on failure', async () => {
    const { result } = renderHook(() => useApi(() => Promise.reject(new ApiError('forbidden', 'No access', 403)), []))
    await waitFor(() => expect(result.current.status).toBe('error'))
    expect(result.current.error.kind).toBe('forbidden')
    expect(result.current.data).toBeNull()
  })

  it('reload repeats the request', async () => {
    const request = vi.fn().mockRejectedValueOnce(new ApiError('unavailable', 'down')).mockResolvedValueOnce('ok')
    const { result } = renderHook(() => useApi(request, []))
    await waitFor(() => expect(result.current.status).toBe('error'))
    await act(() => result.current.reload())
    expect(result.current.status).toBe('success')
    expect(request).toHaveBeenCalledTimes(2)
  })

  it('never shows stale data after a failed silent refresh', async () => {
    const request = vi
      .fn()
      .mockResolvedValueOnce('first')
      .mockRejectedValueOnce(new ApiError('server', 'boom', 500))
    const { result } = renderHook(() => useApi(request, []))
    await waitFor(() => expect(result.current.data).toBe('first'))
    await act(() => result.current.reload({ silent: true }))
    expect(result.current.status).toBe('error')
    expect(result.current.data).toBeNull()
  })

  it('ignores a slow response that a newer request has overtaken', async () => {
    let resolveSlow
    const slow = new Promise((resolve) => {
      resolveSlow = resolve
    })
    const { result, rerender } = renderHook(({ id }) => useApi(() => (id === 1 ? slow : Promise.resolve('second')), [id]), {
      initialProps: { id: 1 },
    })
    rerender({ id: 2 })
    await waitFor(() => expect(result.current.data).toBe('second'))
    await act(async () => resolveSlow('first'))
    expect(result.current.data).toBe('second')
  })

  it('does not call the request while disabled', async () => {
    const request = vi.fn().mockResolvedValue('x')
    renderHook(() => useApi(request, [], { enabled: false }))
    await Promise.resolve()
    expect(request).not.toHaveBeenCalled()
  })
})
