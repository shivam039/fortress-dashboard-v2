// Scan lifecycle independent of page mounts; no polling or inferred progress.
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
export interface ScanState {
  status: 'idle' | 'running' | 'completed' | 'partial' | 'failed' | 'unknown';
  startedAt: number | null;
  universe: string;
  result: ScanResult | null;
  message: string;
  cacheUnavailable: boolean;
}
export const emptyScanState: ScanState = {
  status: 'idle', startedAt: null, universe: '', result: null, message: '', cacheUnavailable: false,
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
        publish({ ...emptyScanState, ...parsed,
          status: parsed.status === 'running' ? 'unknown' : parsed.status,
          message: parsed.status === 'running' ? 'The page refreshed before the scan response arrived. Its server outcome is unknown.' : parsed.message,
        });
      } catch { /* Invalid/unavailable browser storage must not block a scan. */ }
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
