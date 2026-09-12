'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const { ADAPTERS, executeAgentLive, executeQwenWeb, qwenWebHealth, resolveExecutionMode } = require('./providers');

test('qwen_web is recognized but manual by default', () => {
  assert.equal(ADAPTERS.qwen_web.name, 'qwen_web');
  assert.equal(resolveExecutionMode('qwen_web', {}).mode, 'MANUAL_EXPORT');
});

test('missing configuration is not configured', async () => {
  assert.equal(await qwenWebHealth({}), 'MISCONFIGURED');
  assert.equal((await executeQwenWeb({ runId: 'r', prompt: 'x' })).status, 'NOT_CONFIGURED');
});

test('successful response is structured and redacts no credentials', async () => {
  const fake = async () => ({ ok: true, status: 200, json: async () => ({ choices: [{ message: { content: '{"run_id":"r","provider":"qwen_web","model":"qwen","changed_files":[],"production_access":false,"auto_merge":false}' } }] }) });
  const result = await executeQwenWeb({ runId: 'r', model: 'qwen', prompt: 'safe', baseUrl: 'http://private', token: 'secret', fetchImpl: fake });
  assert.equal(result.status, 'AUTOMATED_EXPERIMENTAL');
  assert.equal(result.run_id, 'r');
  assert.equal(result.token_usage, 'NOT_AVAILABLE');
});

test('auth, malformed, timeout, and transient failures are classified', async () => {
  const response = (status, payload = {}) => async () => ({ ok: status === 200, status, json: async () => payload });
  assert.equal((await executeQwenWeb({ runId: 'r', prompt: 'x', baseUrl: 'http://p', token: 't', fetchImpl: response(401) })).status, 'SESSION_EXPIRED');
  assert.equal((await executeQwenWeb({ runId: 'r', prompt: 'x', baseUrl: 'http://p', token: 't', fetchImpl: response(200, {}) })).status, 'MALFORMED_RESPONSE');
  assert.equal((await executeQwenWeb({ runId: 'r', model: 'qwen', prompt: 'x', baseUrl: 'http://p', token: 't', fetchImpl: response(200, { choices: [{ message: { content: '{"run_id":"wrong","provider":"qwen_web","changed_files":[],"production_access":false,"auto_merge":false}' } }] }) })).status, 'INVALID_PROVIDER_RESULT');
  assert.equal((await executeQwenWeb({ runId: 'r', prompt: 'x', baseUrl: 'http://p', token: 't', fetchImpl: response(503) })).transient, true);
});

test('one JSON code fence is accepted but prose remains malformed', async () => {
  const fake = async () => ({ ok: true, status: 200, json: async () => ({ choices: [{ message: { content: '```json\n{"run_id":"r","provider":"qwen_web","changed_files":[],"production_access":false,"auto_merge":false}\n```' } }] }) });
  assert.equal((await executeQwenWeb({ runId: 'r', prompt: 'x', baseUrl: 'http://p', token: 't', fetchImpl: fake })).status, 'AUTOMATED_EXPERIMENTAL');
});

test('live dispatch reports executed only after a real successful Qwen call', async () => {
  const fake = async () => ({ ok: true, status: 200, json: async () => ({ choices: [{ message: { content: '{"run_id":"live-1","provider":"qwen_web","changed_files":[],"production_access":false,"auto_merge":false}' } }] }) });
  const result = await executeAgentLive({ provider: 'qwen_web', prompt: 'x', config: { runId: 'live-1' }, baseUrl: 'http://p', token: 't', fetchImpl: fake });
  assert.equal(result.executed, true);
});
