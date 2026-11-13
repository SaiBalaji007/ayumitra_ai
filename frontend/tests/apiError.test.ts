// Run with: npm test   (Node's built-in test runner; Node 24 runs TypeScript directly)
import assert from 'node:assert/strict'
import { describe, it } from 'node:test'
import { AxiosError, AxiosHeaders, type AxiosResponse } from 'axios'
import { apiErrorMessage } from '../src/lib/apiError.ts'

function httpError(status: number, data: unknown) {
  const config = { headers: new AxiosHeaders() }
  const response = { status, statusText: '', data, headers: {}, config } as AxiosResponse
  return new AxiosError(`Request failed with status code ${status}`, 'ERR_BAD_RESPONSE', config, {}, response)
}

describe('apiErrorMessage', () => {
  it('shows DRF field errors with a readable field name', () => {
    const err = httpError(400, { email: ['An account with this email already exists.'], code: 'invalid' })
    assert.equal(apiErrorMessage(err), 'Email: An account with this email already exists.')
  })

  it('humanizes snake_case fields', () => {
    assert.equal(apiErrorMessage(httpError(400, { first_name: ['This field is required.'] })), 'First name: This field is required.')
  })

  it('shows password validator messages from non_field_errors without a prefix', () => {
    const err = httpError(400, { non_field_errors: ['This password is too common.'] })
    assert.equal(apiErrorMessage(err), 'This password is too common.')
  })

  it('prefers detail', () => {
    assert.equal(apiErrorMessage(httpError(401, { detail: 'No active account found with the given credentials', code: 'no_active_account' })), 'No active account found with the given credentials')
  })

  it('never shows the "code" key as the message', () => {
    assert.equal(apiErrorMessage(httpError(400, { code: 'invalid', password: ['Too short.'] })), 'Password: Too short.')
  })

  it('handles nested serializer errors', () => {
    assert.equal(apiErrorMessage(httpError(400, { medicines: [{ dose: ['Invalid.'] }] })), 'Dose: Invalid.')
  })

  // The original bug: a stale server answered with Django's HTML 404 page and the UI said only
  // "Something went wrong".
  it('explains an HTML 404 instead of falling back to a generic message', () => {
    const msg = apiErrorMessage(httpError(404, '<!DOCTYPE html><html><title>Page not found</title></html>'))
    assert.match(msg, /HTTP 404/)
    assert.match(msg, /restart the Django server/)
  })

  it('never shows raw HTML from a 500 page', () => {
    const msg = apiErrorMessage(httpError(500, '<html><body>Traceback ...</body></html>'))
    assert.equal(msg, 'The server hit an error (HTTP 500). Please try again shortly.')
  })

  it('explains proxy errors when Django is down', () => {
    assert.match(apiErrorMessage(httpError(502, '')), /backend is running/)
  })

  it('explains throttling', () => {
    assert.match(apiErrorMessage(httpError(429, { detail: 'Request was throttled. Expected available in 42 seconds.' })), /throttled/)
    assert.match(apiErrorMessage(httpError(429, '')), /Too many attempts/)
  })

  it('reports network failures', () => {
    const err = new AxiosError('Network Error', 'ERR_NETWORK', { headers: new AxiosHeaders() })
    assert.match(apiErrorMessage(err), /Cannot reach the server/)
  })

  it('uses the fallback for non-HTTP errors without leaking details', () => {
    const orig = console.error
    console.error = () => {}
    try {
      assert.equal(apiErrorMessage(new TypeError('x is undefined'), 'Fallback'), 'Fallback')
    } finally {
      console.error = orig
    }
  })
})
