import { describe, expect, it } from 'vitest'
import { ApiError, expectShape, toApiError } from '../services/api'

const httpError = (status, data) => ({ response: { status, data }, config: { url: '/api/x' } })

describe('toApiError', () => {
  it.each([
    [401, 'unauthorized'],
    [403, 'forbidden'],
    [404, 'not_found'],
    [409, 'conflict'],
    [422, 'validation'],
    [503, 'unavailable'],
    [500, 'server'],
  ])('maps HTTP %i to "%s"', (status, kind) => {
    const error = toApiError(httpError(status, { detail: 'Server said no.' }))
    expect(error).toBeInstanceOf(ApiError)
    expect(error.kind).toBe(kind)
    expect(error.status).toBe(status)
    expect(error.message).toBe('Server said no.')
  })

  it('treats a request with no response as the server being unavailable', () => {
    const error = toApiError({ message: 'Network Error' })
    expect(error.kind).toBe('unavailable')
    expect(error.message).toMatch(/could not be reached/)
  })

  it('treats a timeout as unavailable', () => {
    expect(toApiError({ code: 'ECONNABORTED' }).kind).toBe('unavailable')
  })

  it('falls back to a generic message when the body has no detail', () => {
    expect(toApiError(httpError(500, '<html>oops</html>')).message).toMatch(/500/)
  })

  it('passes an ApiError through unchanged', () => {
    const original = new ApiError('conflict', 'Already running', 409)
    expect(toApiError(original)).toBe(original)
  })
})

describe('expectShape', () => {
  it('returns the data when the expected keys are present', () => {
    const data = { kpis: {}, models: [] }
    expect(expectShape(data, { keys: ['kpis', 'models'] })).toBe(data)
  })

  it('rejects a response that is missing a key', () => {
    expect(() => expectShape({ kpis: {} }, { keys: ['kpis', 'models'] }, 'dashboard summary')).toThrowError(
      expect.objectContaining({ kind: 'invalid_response' }),
    )
  })

  it('rejects the wrong container type', () => {
    expect(() => expectShape({ items: [] }, { array: true })).toThrowError(expect.objectContaining({ kind: 'invalid_response' }))
    expect(() => expectShape([], { keys: ['a'] })).toThrowError(expect.objectContaining({ kind: 'invalid_response' }))
    expect(() => expectShape('<html>', { keys: [] })).toThrowError(expect.objectContaining({ kind: 'invalid_response' }))
    expect(() => expectShape(null, { keys: [] })).toThrowError(expect.objectContaining({ kind: 'invalid_response' }))
  })
})
