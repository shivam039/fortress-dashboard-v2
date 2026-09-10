import { test } from 'node:test';
import assert from 'node:assert/strict';
import scanState from '../.scan-tests/lib/scan-state.js';
const { createScanStore, normalizeScanResponse } = scanState;
import { renderToStaticMarkup } from 'react-dom/server';
import React from 'react';
import scanComponents from '../.scan-tests/components/ScanStatus.js';
const { ScanStatus } = scanComponents;
const memory = () => {
  let value = null;
  return { getItem: () => value, setItem: (_, next) => { value = next; } };
};
const row = { Symbol: 'TEST', Score: 0 };

test('response adapter preserves breaker counts, zero scores, and empty results', () => {
  assert.equal(normalizeScanResponse([row]).results[0].Score, 0);
  const data = normalizeScanResponse({ results: [], circuit_breaker_tripped: true, scanned: 10, failed: 9, summary: 'Provider unavailable' });
  assert.equal(data.partial, true);
  assert.equal(data.scanned, 10);
  assert.equal(data.failed, 9);
  assert.equal(data.summary, 'Provider unavailable');
  assert.throws(() => normalizeScanResponse({ invalid: true }));
});

test('request starts immediately, prevents duplicates, preserves old results until completion', async () => {
  const store = createScanStore('user', memory());
  await store.start('Old', async () => [row]);
  let finish;
  const pending = store.start('New', () => new Promise(resolve => { finish = resolve; }));
  assert.equal(store.getSnapshot().status, 'running');
  assert.equal(store.getSnapshot().result.universe, 'Old');
  assert.equal(await store.start('Duplicate', () => assert.fail('duplicate request')), false);
  finish([]);
  await pending;
  assert.equal(store.getSnapshot().status, 'completed');
  assert.deepEqual(store.getSnapshot().result.results, []);
  assert.ok(store.getSnapshot().result.receivedAt);
});

test('partial and failure remain visible without discarding last usable results', async () => {
  const store = createScanStore('user', memory());
  await store.start('Test', async () => ({ results: [row], circuit_breaker_tripped: true, scanned: 10, failed: 8 }));
  assert.equal(store.getSnapshot().status, 'partial');
  await store.start('Test', async () => { throw new TypeError('Failed to fetch'); });
  assert.equal(store.getSnapshot().status, 'unknown');
  assert.equal(store.getSnapshot().result.results.length, 1);
  await store.start('Test', async () => { throw Object.assign(new Error('Universe not found'), { status: 404 }); });
  assert.equal(store.getSnapshot().status, 'failed');
  assert.match(store.getSnapshot().message, /Universe not found/);
});

test('refresh restores results, marks interrupted request unknown, and never resubmits', async () => {
  const storage = memory();
  const first = createScanStore('user', storage);
  await first.start('Old', async () => [row]);
  let finish;
  const pending = first.start('New', () => new Promise(resolve => { finish = resolve; }));
  const restored = createScanStore('user', storage);
  restored.restore();
  assert.equal(restored.getSnapshot().status, 'unknown');
  assert.equal(restored.getSnapshot().result.results.length, 1);
  finish([]);
  await pending;
});

test('blocked or corrupt storage does not prevent scanning; subscriptions detach', async () => {
  const store = createScanStore('user', { getItem: () => '{', setItem: () => { throw Error('quota'); } });
  store.restore();
  let notifications = 0;
  const unsubscribe = store.subscribe(() => notifications++);
  await store.start('Test', async () => [row]);
  assert.equal(store.getSnapshot().status, 'completed');
  assert.equal(store.getSnapshot().cacheUnavailable, true);
  assert.ok(notifications >= 2);
  unsubscribe();
  const before = notifications;
  await store.start('Test', async () => []);
  assert.equal(notifications, before);
});

test('user scopes cannot restore another user results', async () => {
  const values = new Map();
  const storage = { getItem: key => values.get(key), setItem: (key, value) => values.set(key, value) };
  await createScanStore('Alice', storage).start('Test', async () => [row]);
  const bob = createScanStore('Bob', storage);
  bob.restore();
  assert.equal(bob.getSnapshot().result, null);
});

test('status rendering covers running, completion, partial, unknown and failures without fake percentages', async () => {
  const store = createScanStore('user', memory());
  for (const status of ['running', 'completed', 'partial', 'unknown', 'failed']) {
    const html = renderToStaticMarkup(React.createElement(ScanStatus, { state: { ...store.getSnapshot(), status, startedAt: Date.now(), universe: 'Test' } }));
    assert.match(html, /role="(?:status|alert)"/);
    assert.doesNotMatch(html, /aria-valuenow|\d+%/);
    if (status === 'running') assert.match(html, /Stage: starting/);
    if (status === 'unknown') assert.match(html, /Scan History/);
    if (status === 'partial') assert.match(html, /Partial results/);
  }
});

// ── FORTRESS-V4: async scan job lifecycle ──────────────────────────────────

test('startJob begins a running state with the real job id, and rejects a second job while one is active', () => {
  const store = createScanStore('user', memory());
  assert.equal(store.startJob('Nifty 50', 'job-1'), true);
  assert.equal(store.getSnapshot().status, 'running');
  assert.equal(store.getSnapshot().jobId, 'job-1');
  assert.equal(store.startJob('Nifty 50', 'job-2'), false); // no duplicate submission
  assert.equal(store.getSnapshot().jobId, 'job-1');
});

test('updateJobStatus reports real server stage/progress, never a fabricated percentage', () => {
  const store = createScanStore('user', memory());
  store.startJob('Nifty 50', 'job-1');
  store.updateJobStatus({ status: 'running', stage: 'market_data', progress: { current: 12, total: 50 }, message: 'Fetching market data', error: null });
  const html = renderToStaticMarkup(React.createElement(ScanStatus, { state: store.getSnapshot() }));
  assert.match(html, /market_data/);
  assert.match(html, /12\/50 tickers/);
  assert.doesNotMatch(html, /\d+%/);
});

test('completeJob retrieves and stores the real results, ending the job', () => {
  const store = createScanStore('user', memory());
  store.startJob('Nifty 50', 'job-1');
  store.completeJob([row]);
  const snap = store.getSnapshot();
  assert.equal(snap.status, 'completed');
  assert.equal(snap.jobId, null);
  assert.equal(snap.result.results.length, 1);
});

test('a failed job surfaces the failure and clears the job id', () => {
  const store = createScanStore('user', memory());
  store.startJob('Nifty 50', 'job-1');
  store.updateJobStatus({ status: 'failed', stage: 'market_data', progress: null, message: null, error: 'Provider unavailable' });
  const snap = store.getSnapshot();
  assert.equal(snap.status, 'failed');
  assert.equal(snap.jobId, null);
  assert.equal(snap.message, 'Provider unavailable');
});

test('a refresh with an in-flight job id stays running (reconnectable), not unknown', () => {
  const storage = memory();
  const store = createScanStore('user', storage);
  store.startJob('Nifty 50', 'job-1');
  const resumed = createScanStore('user', storage);
  resumed.restore();
  assert.equal(resumed.getSnapshot().status, 'running');
  assert.equal(resumed.getSnapshot().jobId, 'job-1');
});

test('a refresh with no job id (old synchronous shape) still degrades to unknown', () => {
  const storage = memory();
  const store = createScanStore('user', storage);
  store.start('Nifty 50', () => new Promise(() => {})); // never resolves — status stays 'running', no jobId
  const resumed = createScanStore('user', storage);
  resumed.restore();
  assert.equal(resumed.getSnapshot().status, 'unknown');
});

test('the screener page starts an async job, not the old synchronous scan', async () => {
  const fs = await import('node:fs');
  const src = fs.readFileSync(new URL('../src/app/screener/page.tsx', import.meta.url), 'utf8');
  assert.match(src, /scanApi\.startScanJob/);
  assert.match(src, /scanApi\.getScanJobStatus/);
  assert.match(src, /scanApi\.getScanJobResults/);
});
