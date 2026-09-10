// Scan lifecycle independent of page mounts. FORTRESS-V4: the primary
// screener path is now the async job API (POST /api/scan/jobs) — jobId/
// stage/progress are the real, server-reported values a poller (see
// screener/page.tsx) writes here; this module itself never polls or
// infers progress. `start()` (old synchronous /api/scan) is left intact
// for any other caller, unused by the screener now.
export type ScanRow = Record<string, unknown>;
export interface ScanResult {
  results: ScanRow[];
  partial: boolean;
  summary?: string;
  scanned?: number;
  failed?: number;
  universe: string;
  receivedAt: string;
}
export type ScanJobStageName =
  | 'universe' | 'metadata' | 'market_data' | 'indicators' | 'scoring' | 'persistence' | 'completed' | 'failed';
export interface ScanState {
  status: 'idle' | 'running' | 'completed' | 'partial' | 'failed' | 'unknown';
  startedAt: number | null;
  universe: string;
  result: ScanResult | null;
  message: string;
  cacheUnavailable: boolean;
  jobId: string | null;
  stage: ScanJobStageName | null;
  progress: { current: number; total: number } | null;
}
export const emptyScanState: ScanState = {
  status: 'idle', startedAt: null, universe: '', result: null, message: '', cacheUnavailable: false,
  jobId: null, stage: null, progress: null,
};
export function normalizeScanResponse(value: unknown) {
  const envelope = !Array.isArray(value) && value && typeof value === 'object'
    ? value as Record<string, unknown> : {};
  const results = Array.isArray(value) ? value : envelope.results;
  if (!Array.isArray(results) || results.some(row => !row || typeof row !== 'object' || Array.isArray(row))) {
    throw new Error('The scan returned an unreadable response. Check Scan History before retrying.');
  }
  const count = (value: unknown) => typeof value === 'number' && Number.isInteger(value) && value >= 0 ? value : undefined;
  return {
    results: results as ScanRow[],
    partial: envelope.circuit_breaker_tripped === true,
    summary: typeof envelope.summary === 'string' ? envelope.summary : undefined,
    scanned: count(envelope.scanned), failed: count(envelope.failed),
  };
}
type Storage = Pick<globalThis.Storage, 'getItem' | 'setItem'>;
export function createScanStore(user: string, storage?: Storage) {
  let state = emptyScanState;
  let restored = false;
  const listeners = new Set<() => void>();
  const key = `fortress:scan:v1:${user}`;
  const cache = () => storage ?? (typeof window !== 'undefined' ? window.sessionStorage : undefined);
  const publish = (next: ScanState) => {
    state = next;
    try { cache()?.setItem(key, JSON.stringify(state)); }
    catch { state = { ...state, cacheUnavailable: true }; }
    listeners.forEach(listener => listener());
  };
  return {
    getSnapshot: () => state,
    subscribe: (listener: () => void) => { listeners.add(listener); return () => { listeners.delete(listener); }; },
    restore: () => {
      if (restored) return;
      restored = true;
      try {
        const saved = cache()?.getItem(key);
        if (!saved) return;
        const parsed = JSON.parse(saved) as ScanState;
        if (!['idle', 'running', 'completed', 'partial', 'failed', 'unknown'].includes(parsed.status)) return;
        if (parsed.result) {
          normalizeScanResponse(parsed.result);
          if (typeof parsed.result.universe !== 'string' || !Number.isFinite(Date.parse(parsed.result.receivedAt))) return;
        }
        // A running *job* has a jobId the page can reconnect to and poll —
        // unlike the old synchronous request, its outcome is not actually
        // unknown after a refresh, so `status` is preserved as-is.
        const reconnectable = parsed.status === 'running' && !!parsed.jobId;
        publish({ ...emptyScanState, ...parsed,
          status: parsed.status === 'running' && !reconnectable ? 'unknown' : parsed.status,
          message: parsed.status === 'running' && !reconnectable
            ? 'The page refreshed before the scan response arrived. Its server outcome is unknown.'
            : parsed.message,
        });
      } catch { /* Invalid/unavailable browser storage must not block a scan. */ }
    },
    // ── FORTRESS-V4: async scan job lifecycle ──────────────────────────────
    // startJob/updateJobStatus/completeJob/failJob are the only writers a
    // job-polling loop needs; the poller itself lives in screener/page.tsx
    // so this module stays free of timers/network calls.
    startJob: (universe: string, jobId: string) => {
      if (state.status === 'running') return false;
      restored = true;
      publish({ ...state, status: 'running', startedAt: Date.now(), universe, message: '',
        jobId, stage: null, progress: null, result: null });
      return true;
    },
    updateJobStatus: (job: { status: string; stage: string | null; progress: { current: number; total: number } | null; message: string | null; error: string | null }) => {
      if (state.jobId === null) return; // superseded/cleared already — ignore a late poll response
      if (job.status === 'failed') {
        publish({ ...state, status: 'failed', message: job.error || job.message || 'Scan failed.', jobId: null, stage: 'failed' });
        return;
      }
      publish({ ...state, stage: (job.stage as ScanJobStageName) ?? state.stage, progress: job.progress, message: job.message || state.message });
    },
    completeJob: (data: unknown) => {
      if (state.jobId === null) return;
      try {
        const normalized = normalizeScanResponse(data);
        publish({ ...state, status: normalized.partial ? 'partial' : 'completed',
          result: { ...normalized, universe: state.universe, receivedAt: new Date().toISOString() },
          message: normalized.summary ?? '', jobId: null, stage: 'completed', progress: null,
        });
      } catch (err) {
        publish({ ...state, status: 'failed', message: (err as Error).message, jobId: null });
      }
    },
    failJob: (message: string) => {
      if (state.jobId === null) return;
      publish({ ...state, status: 'failed', message, jobId: null, stage: 'failed' });
    },
    start: async (universe: string, request: () => Promise<unknown>) => {
      if (state.status === 'running') return false;
      restored = true;
      publish({ ...state, status: 'running', startedAt: Date.now(), universe, message: '' });
      try {
        const data = normalizeScanResponse(await request());
        publish({ ...state, status: data.partial ? 'partial' : 'completed',
          result: { ...data, universe, receivedAt: new Date().toISOString() },
          message: data.summary ?? '',
        });
        return true;
      } catch (error) {
        const status = error && typeof error === 'object' && 'status' in error ? error.status : undefined;
        const rejected = typeof status === 'number' && status >= 400 && status < 500 && status !== 408;
        publish({ ...state, status: rejected ? 'failed' : 'unknown',
          message: rejected && error instanceof Error ? error.message :
            'The connection ended before a usable response arrived. The server may still be working. Check Scan History before starting another scan.',
        });
        return false;
      }
    },
  };
}
export type ScanStore = ReturnType<typeof createScanStore>;
const stores = new Map<string, ScanStore>();
export function getScanStore(user: string): ScanStore {
  if (!stores.has(user)) stores.set(user, createScanStore(user));
  return stores.get(user)!;
}
