'use client';

import React, { memo, useEffect, useState } from 'react';
import type { ScanState } from '../lib/scan-state';

// Only this small component ticks; result tables and charts do not rerender.
export function formatElapsedSeconds(seconds: number) {
  const safeSeconds = Math.max(0, Math.floor(seconds));
  const minutes = Math.floor(safeSeconds / 60);
  const remainingSeconds = safeSeconds % 60;
  return minutes > 0 ? `${minutes}m ${remainingSeconds}s` : `${remainingSeconds}s`;
}

function Elapsed({ startedAt }: { startedAt: number }) {
  const [now, setNow] = useState(startedAt);
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [startedAt]);
  return <span>Elapsed: {formatElapsedSeconds((now - startedAt) / 1000)}</span>;
}
export const ScanStatus = memo(function ScanStatus({ state, onRetry }: { state: ScanState; onRetry?: () => void }) {
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
  const interrupted = state.status === 'failed' && state.message.toLowerCase().includes('scan interrupted');
  const labels = { idle: 'Ready', running: 'Scan request in progress', completed: 'Scan completed', partial: 'Partial results — scan stopped early', failed: interrupted ? 'Scan interrupted' : 'Scan failed', unknown: 'Scan outcome unknown' };
  return <section className="card" aria-label="Scan status" style={{ marginBottom: 24, overflowWrap: 'anywhere' }}>
    <div role={state.status === 'failed' || uncertain ? 'alert' : 'status'}>
      <strong>{labels[state.status]} — {state.universe}</strong>
      {running && <>
        {/* FORTRESS-V4: real server-reported stage/progress from the async
            job API — never a fabricated percentage. */}
        <p>
          Stage: {state.stage ?? 'starting'}
          {state.progress ? ` — ${state.progress.current}/${state.progress.total} tickers` : ''}
        </p>
        <p>You can navigate within Fortress while this runs — refreshing this page reconnects to the same job.</p>
      </>}
      {state.message && <p>{state.message}</p>}
      {interrupted && <p>The backend stopped processing this scan. This can happen after a server restart or worker interruption.</p>}
      {offline && <p>You are offline. Waiting for connectivity does not confirm that the server is still running. Scans are not automatically retried.</p>}
      {uncertain && <p><a href="/history">Check Scan History</a> for saved results. This request cannot be reattached after refresh. A retry may duplicate server work.</p>}
      {state.status === 'partial' && <p>These are partial results, not a full-universe scan.</p>}
      {state.result?.scanned !== undefined && !running && <p>Attempted: {state.result.scanned} tickers · Failed: {state.result.failed ?? 'not reported'} · Returned: {state.result.results.length}</p>}
    </div>
    {state.status === 'failed' && onRetry && <button className="btn" onClick={onRetry}>Retry Scan</button>}
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
