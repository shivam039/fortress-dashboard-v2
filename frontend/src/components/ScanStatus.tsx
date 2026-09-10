'use client';

import React, { memo, useEffect, useState } from 'react';
import type { ScanState } from '../lib/scan-state';

// Only this small component ticks; result tables and charts do not rerender.
function Elapsed({ startedAt }: { startedAt: number }) {
  const [now, setNow] = useState(startedAt);
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [startedAt]);
  return <span>Elapsed: {Math.max(0, Math.floor((now - startedAt) / 1000))}s (request wait time)</span>;
}
export const ScanStatus = memo(function ScanStatus({ state }: { state: ScanState }) {
  const [offline, setOffline] = useState(false);
  useEffect(() => {
    const update = () => setOffline(!navigator.onLine);
    update();
    window.addEventListener('online', update);
    window.addEventListener('offline', update);
    return () => { window.removeEventListener('online', update); window.removeEventListener('offline', update); };
  }, []);
  if (state.status === 'idle' && !state.result) return null;
  const running = state.status === 'running';
  const uncertain = state.status === 'unknown';
  const labels = { idle: 'Ready', running: 'Scan request in progress', completed: 'Scan completed', partial: 'Partial results — scan stopped early', failed: 'Scan failed', unknown: 'Scan outcome unknown' };
  return <section className="card" aria-label="Scan status" style={{ marginBottom: 24, overflowWrap: 'anywhere' }}>
    <div role={state.status === 'failed' || uncertain ? 'alert' : 'status'}>
      <strong>{labels[state.status]} — {state.universe}</strong>
      {running && <>
        <p>Stage: awaiting scan response. Live server stages and counts are unavailable.</p>
        <p>Results arrive when processing finishes. You can use existing results or navigate within Fortress while waiting.</p>
      </>}
      {state.message && <p>{state.message}</p>}
      {offline && <p>You are offline. Waiting for connectivity does not confirm that the server is still running. Scans are not automatically retried.</p>}
      {uncertain && <p><a href="/history">Check Scan History</a> for saved results. This request cannot be reattached after refresh. A retry may duplicate server work.</p>}
      {state.status === 'partial' && <p>These are partial results, not a full-universe scan.</p>}
      {state.result?.scanned !== undefined && !running && <p>Attempted: {state.result.scanned} tickers · Failed: {state.result.failed ?? 'not reported'} · Returned: {state.result.results.length}</p>}
    </div>
    {running && state.startedAt && <Elapsed key={state.startedAt} startedAt={state.startedAt} />}
    {state.result && <p>
      Showing {state.result.partial ? 'partial' : 'completed-response'} results for {state.result.universe}: {state.result.results.length} rows.
      {' '}Received <time dateTime={state.result.receivedAt}>{new Date(state.result.receivedAt).toLocaleString()}</time> (browser time; market-data freshness is not reported).
      {(running || uncertain || state.status === 'failed') && ' These are the previous results.'}
    </p>}
    {state.status === 'completed' && state.result?.results.length === 0 && <p>No rows returned. This can mean no matches or unavailable market data.</p>}
    {state.cacheUnavailable && <p>Browser storage is unavailable or full. Results remain usable here but may not survive a refresh.</p>}
  </section>;
});
