// src/lib/api.ts — Typed API client for the Fortress FastAPI backend
const API_BASE =
  process.env.NEXT_PUBLIC_API_URL ||
  process.env.BACKEND_URL ||
  'http://localhost:8000';


type ApiRecord = Record<string, unknown>;

export function asArray<T>(value: unknown, candidateKeys: string[] = []): T[] {
  if (Array.isArray(value)) {
    return value as T[];
  }

  if (value && typeof value === 'object') {
    const record = value as ApiRecord;
    for (const key of candidateKeys) {
      const candidate = record[key];
      if (Array.isArray(candidate)) {
        return candidate as T[];
      }
    }
  }

  return [];
}

export class APIError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
    this.name = 'APIError';
  }
}

// Default request timeout. Without this, a `fetch()` with no AbortController
// waits indefinitely — if the backend genuinely hangs (or the connection
// dies silently), the UI just spins forever with no way to tell "still
// working" apart from "actually stuck". 60s comfortably covers ordinary
// endpoints; slow/bulk endpoints (scans) pass a longer override below.
const DEFAULT_TIMEOUT_MS = 60_000;

async function request<T>(
  endpoint: string,
  options: RequestInit = {},
  timeoutMs: number = DEFAULT_TIMEOUT_MS
): Promise<T> {
  const url = `${API_BASE}${endpoint}`;
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(options.headers as Record<string, string> || {}),
  };

  if (typeof window !== 'undefined') {
    const token = localStorage.getItem('fortress_token');
    if (token && !headers['Authorization']) {
      headers['Authorization'] = `Bearer ${token}`;
    }
  }

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);

  let res: Response;
  try {
    res = await fetch(url, {
      credentials: 'include', // send httpOnly cookies if supported
      ...options,
      headers,
      signal: controller.signal,
    });
  } catch (err) {
    if (controller.signal.aborted) {
      throw new APIError(
        `Timed out after ${Math.round(timeoutMs / 1000)}s waiting for a response. ` +
          `The backend may still be working — check its terminal — or it may be stuck.`,
        408
      );
    }
    throw err;
  } finally {
    clearTimeout(timer);
  }

  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try {
      const body = await res.json();
      detail = body.detail || body.error || detail;
    } catch {}
    throw new APIError(detail, res.status);
  }

  return res.json();
}

// ── Generic methods ──────────────────────────────────────────────────────────

export const api = {
  get: <T>(endpoint: string, timeoutMs?: number) => request<T>(endpoint, {}, timeoutMs),

  post: <T>(endpoint: string, body: unknown, timeoutMs?: number) =>
    request<T>(
      endpoint,
      {
        method: 'POST',
        body: JSON.stringify(body),
      },
      timeoutMs
    ),

  put: <T>(endpoint: string, body: unknown, timeoutMs?: number) =>
    request<T>(
      endpoint,
      {
        method: 'PUT',
        body: JSON.stringify(body),
      },
      timeoutMs
    ),

  delete: <T>(endpoint: string, timeoutMs?: number) =>
    request<T>(endpoint, { method: 'DELETE' }, timeoutMs),
};

// ── Auth ─────────────────────────────────────────────────────────────────────

export interface AuthResponse {
  token: string;
  username: string;
  role: string;
  message: string;
}

export interface UserProfile {
  username: string;
  full_name: string;
  email: string;
  phone: string;
  account_status: string;
  role?: string;
  last_login_at: string | null;
  created_at?: string;
}

export const authApi = {
  login: async (username: string, password: string) => {
    const res = await api.post<AuthResponse>('/api/auth/login', { username, password });
    if (typeof window !== 'undefined' && res?.token) {
      localStorage.setItem('fortress_token', res.token);
    }
    return res;
  },

  signup: async (data: { username: string; password: string; full_name?: string; email?: string }) => {
    const res = await api.post<AuthResponse>('/api/auth/signup', data);
    if (typeof window !== 'undefined' && res?.token) {
      localStorage.setItem('fortress_token', res.token);
    }
    return res;
  },

  guest: async () => {
    const res = await api.post<AuthResponse>('/api/auth/guest', {});
    if (typeof window !== 'undefined' && res?.token) {
      localStorage.setItem('fortress_token', res.token);
    }
    return res;
  },

  me: () => api.get<UserProfile>('/api/auth/me'),

  logout: async () => {
    try {
      await api.post<{ message: string }>('/api/auth/logout', {});
    } finally {
      if (typeof window !== 'undefined') {
        localStorage.removeItem('fortress_token');
      }
    }
  },
};

// ── Health ───────────────────────────────────────────────────────────────────

export const healthApi = {
  check: async (): Promise<boolean> => {
    try {
      await api.get('/api/health');
      return true;
    } catch {
      return false;
    }
  },
};

// ── Market data provider status ─────────────────────────────────────────────

export interface MarketDataStatus {
  primary: string; // "indstocks" | "yfinance" — LIVE PRICE source, untouched by the OHLCV toggle below
  primary_label: string; // "INDmoney" | "Yahoo Finance"
  fallback: string; // "yfinance" | "none"
  auth_mode: string; // "totp" | "static_token" | "none"
  indstocks_token_set: string;
  ohlcv_source: string; // "bhavcopy" (default) | "indstocks" — OHLCV/scan data source, toggleable
  ohlcv_source_label: string; // "NSE Bhav Copy" | "INDmoney" | "Yahoo Finance"
  universes: Record<string, number>;
}

export type OhlcvProvider = 'bhavcopy' | 'indstocks';

export const marketDataApi = {
  status: () => api.get<MarketDataStatus>('/api/market-data-status'),

  getProvider: () =>
    api.get<{ provider: OhlcvProvider }>('/api/settings/data-provider'),

  // Switch the OHLCV/scan data source. Only affects historical/scan data —
  // live price (the "primary"/"primary_label" fields above) always comes
  // from INDstocks/yfinance regardless, since Bhav Copy is end-of-day only.
  setProvider: (provider: OhlcvProvider) =>
    api.post<{ status: string; provider: OhlcvProvider }>(
      '/api/settings/data-provider',
      { provider }
    ),
};

// ── Bhav Copy status/backfill ────────────────────────────────────────────────
//
// ohlcv_calls_by_source is the concrete proof that Bhav Copy is actually
// serving data: MarketDataStatus.ohlcv_source above just reflects the
// *preference setting*, not what actually satisfied any given OHLCV call —
// a "bhavcopy" preference silently falls back to indstocks/yfinance
// per-symbol whenever Bhav Copy has no data yet (e.g. before a backfill
// finishes). These counts are cumulative since the backend process started
// (or the last reset).

export interface BhavcopyStatus {
  trade_date: string;
  status: string; // "done" | "not_yet_published" | "error" | "never_attempted"
  backfill_in_progress: boolean;
  backfill_started_at: string | null;
  ohlcv_calls_by_source: Record<string, number>;
  trading_days_covered: number;
  symbol_count: number;
  earliest_date: string | null;
  latest_date: string | null;
}

export const bhavcopyApi = {
  status: () => api.get<BhavcopyStatus>('/api/bhavcopy/status'),
};

// ── Scan ─────────────────────────────────────────────────────────────────────

export interface ScanPayload {
  universe: string;
  portfolio_val: number;
  risk_pct: number;
  weights?: Record<string, number>;
  enable_regime?: boolean;
  liquidity_cr_min?: number;
  market_cap_cr_min?: number;
  price_min?: number;
  broker?: string;
}

// A full scan walks every ticker in a universe (up to 250 for Nifty Smallcap
// 250) through INDstocks/yfinance data fetches plus per-ticker scoring, so it
// legitimately takes longer than a typical API call — the default 60s
// timeout is too tight for this specific endpoint and would misreport a
// slow-but-working scan as "stuck".
const SCAN_TIMEOUT_MS = 240_000; // 4 minutes

export interface SymbolSuggestion {
  symbol: string;
  name: string;
}

export interface ScanJobCreated {
  job_id: string;
  status: 'queued';
}

// Real pipeline stages a scan job reports progress through — see
// engine/main.py's execute_scan() for where each one is emitted.
export type ScanJobStage =
  | 'universe'
  | 'metadata'
  | 'market_data'
  | 'indicators'
  | 'scoring'
  | 'persistence'
  | 'completed'
  | 'failed';

export interface ScanJobStatus {
  job_id: string;
  status: 'queued' | 'running' | 'completed' | 'failed';
  stage: ScanJobStage | null;
  progress: { current: number; total: number };
  message: string | null;
  universe: string | null;
  error: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export const scanApi = {
  // Preserve the backend summary and circuit-breaker metadata for scan UX.
  runScanDetailed: (payload: ScanPayload) =>
    api.post<unknown>('/api/scan', payload, SCAN_TIMEOUT_MS),
  getUniverses: async () =>
    asArray<string>(await api.get<unknown>('/api/universes'), [
      'universes',
      'data',
      'results',
    ]),
  runScan: async (payload: ScanPayload) =>
    asArray<ApiRecord>(
      await api.post<unknown>('/api/scan', payload, SCAN_TIMEOUT_MS),
      ['results', 'data', 'stocks', 'items']
    ),
  // ── Async scan jobs (FORTRESS-P3) ─────────────────────────────────────────
  // Same scan as runScan() above, but off the request path: POST creates a
  // job and returns immediately, then the caller polls getScanJobStatus()
  // for progress and getScanJobResults() once status is "completed". Job
  // state is server-side (DB-backed), so a page reload just needs the
  // job_id back (see the screener page's localStorage handling) to resume
  // watching the same job — nothing scan-related is lost.
  startScanJob: (payload: ScanPayload) =>
    api.post<ScanJobCreated>('/api/scan/jobs', payload),
  getScanJobStatus: (jobId: string) =>
    api.get<ScanJobStatus>(`/api/scan/jobs/${encodeURIComponent(jobId)}/status`),
  // Raw response: a completed job's body is the same shape runScan() itself
  // returns (a bare array, or the aborted-early/no-results object); a job
  // still in flight or one that failed returns a {status: ...} object
  // instead — callers should check `status` on non-array responses.
  getScanJobResults: (jobId: string) =>
    api.get<unknown>(`/api/scan/jobs/${encodeURIComponent(jobId)}/results`),
  getSectorPulse: async (universe: string) =>
    asArray<ApiRecord>(
      await api.get<unknown>(
        `/api/sector-pulse?universe=${encodeURIComponent(universe)}`,
        SCAN_TIMEOUT_MS
      ),
      ['sector_pulse', 'sectors', 'data', 'results', 'items']
    ),
  // Search-as-you-type ticker/company-name suggestions (INDstocks
  // instruments cache when available, Bhav Copy's symbol list as fallback —
  // see GET /api/symbols/search).
  searchSymbols: async (q: string) =>
    asArray<SymbolSuggestion>(
      await api.get<unknown>(`/api/symbols/search?q=${encodeURIComponent(q)}`),
      ['results', 'data']
    ),
  // Fetch live data + the full scan-row scoring for one arbitrary ticker,
  // outside the curated universes — see GET /api/scan/search. Same
  // SCAN_TIMEOUT_MS as a full scan since it runs the identical
  // fetch-then-score pipeline for that one symbol.
  searchStock: async (symbol: string, universe?: string) =>
    asArray<ApiRecord>(
      await api.get<unknown>(
        `/api/scan/search?symbol=${encodeURIComponent(symbol)}` +
          (universe ? `&universe=${encodeURIComponent(universe)}` : ''),
        SCAN_TIMEOUT_MS
      ),
      ['results', 'data']
    ),
};

// ── Mutual Fund ──────────────────────────────────────────────────────────────

export const mfApi = {
  // With no `limit`, this discovers and scores essentially the whole
  // direct-growth mutual fund universe (hundreds to low thousands of
  // schemes) — same reasoning as SCAN_TIMEOUT_MS above, the default 60s
  // timeout is too tight for this endpoint.
  getAnalysis: (limit?: number) =>
    api.get<Record<string, unknown>[]>(
      `/api/mf-analysis${limit ? `?limit=${limit}` : ''}`,
      SCAN_TIMEOUT_MS
    ),

  triggerJob: (payload: { job_type: string; force_refresh?: boolean; scheme_codes?: string[] }) =>
    api.post<{ status: string; message: string }>('/mf/trigger-job', payload),
};

// ── Orders ───────────────────────────────────────────────────────────────────

export interface OrderStats {
  total: number;
  executed: number;
  pending: number;
  rejected: number;
  cancelled: number;
}

export const ordersApi = {
  list: (filters?: Record<string, string>) => {
    const params = new URLSearchParams();
    if (filters) {
      Object.entries(filters).forEach(([k, v]) => {
        if (v && v !== 'All') params.set(k, v);
      });
    }
    const qs = params.toString();
    return api.get<Record<string, unknown>[]>(`/api/orders${qs ? `?${qs}` : ''}`);
  },
  create: (order: Record<string, unknown>) => api.post('/api/orders', order),
  stats: () => api.get<OrderStats>('/api/orders/stats'),
};

// ── Brokers ──────────────────────────────────────────────────────────────────

export const brokersApi = {
  list: () => api.get<Record<string, unknown>[]>('/api/brokers'),
  connect: (data: Record<string, string>) => api.post('/api/brokers', data),
  disconnect: (brokerName: string) => api.delete(`/api/brokers/${encodeURIComponent(brokerName)}`),
};

// ── Commodities ──────────────────────────────────────────────────────────────

export const commoditiesApi = {
  list: (forceRefresh?: boolean) =>
    api.get<Record<string, unknown>[]>(
      `/api/commodities${forceRefresh ? '?force_refresh=true' : ''}`,
      SCAN_TIMEOUT_MS
    ),
};

// ── Picks ────────────────────────────────────────────────────────────────────

export interface PickSummary {
  total: number;
  hits: number;
  misses: number;
  expired: number;
  trailing: number;
  hit_rate: number;
  avg_pnl: number;
  avg_days: number;
  best_pnl: number;
  worst_pnl: number;
}

export const picksApi = {
  list: (status?: string) =>
    api.get<Record<string, unknown>[]>(`/api/picks${status ? `?status=${status}` : ''}`),
  record: (data: Record<string, unknown>) => api.post('/api/picks', data),
  summary: () => api.get<PickSummary>('/api/picks/summary'),
};

// ── Paper Trading (FORTRESS-V4) ───────────────────────────────────────────────
//
// PAPER TRADE only — engine/paper_trading/logic.py never places a real
// broker order. Every trade here is a simulation against real price data.

export interface PaperTrade {
  trade_id: number;
  signal_id: number;
  symbol: string;
  entry_timestamp: string;
  entry_price: number;
  quantity: number;
  notional: number;
  stop_price: number | null;
  target_price: number | null;
  status: 'open' | 'closed';
  exit_timestamp?: string | null;
  exit_price?: number | null;
  exit_reason?: string | null;
  gross_pnl?: number | null;
  net_pnl?: number | null;
  costs_modeled?: number | null;
  holding_period_days?: number | null;
}

export interface PaperTradeMetrics {
  trade_count: number;
  total_gross_pnl: number;
  total_net_pnl: number;
  win_rate_pct: number | null;
  avg_win: number | null;
  avg_loss: number | null;
  expectancy: number | null;
  max_drawdown: number;
  total_exposure: number;
  turnover: number;
  portfolio_return_pct: number | null;
  benchmark_excess_return_pct: number | null;
}

export interface PaperPositionValuation extends PaperTrade {
  current_price: number | null;
  unrealized_pnl: number | null;
  unrealized_return_pct: number | null;
  distance_to_stop_pct: number | null;
  distance_to_target_pct: number | null;
  signal: FortressSignalLedgerRow | null;
  policy_version?: string | null;
}

export interface FortressSignalLedgerRow {
  id: number;
  generated_at: string;
  symbol: string;
  sector?: string | null;
  score?: number | null;
  market_regime?: string | null;
  suggested_entry?: number | null;
  stop_loss?: number | null;
  target?: number | null;
  explanation?: string | null;
}

export const paperTradingApi = {
  list: (status?: 'open' | 'closed') =>
    api.get<PaperTrade[]>(`/api/paper-trades${status ? `?status=${status}` : ''}`),
  metrics: () => api.get<PaperTradeMetrics>('/api/paper-trades/metrics'),
  openValuation: () => api.get<PaperPositionValuation[]>('/api/paper-trades/open/valuation'),
  signals: (limit = 20) => api.get<FortressSignalLedgerRow[]>(`/api/paper-trades/signals?limit=${limit}`),
  open: (signalId: number) => api.post<PaperTrade & { label: string }>('/api/paper-trades', { signal_id: signalId }),
  close: (tradeId: number) =>
    api.post<(PaperTrade & { label: string }) | { status: 'not_ready'; reason: string; trade_id: number }>(
      `/api/paper-trades/${tradeId}/close`,
      {}
    ),
};

// ── Scan History ─────────────────────────────────────────────────────────────

export interface ScanHistoryEntry {
  scan_id: number;
  timestamp: string;
  universe: string;
  scan_type: string;
  // FORTRESS-UX1: lightweight per-run count so the history list can show
  // "N stocks analysed" without fetching every run's full payload.
  num_scanned?: number;
}

export const historyApi = {
  timestamps: () => api.get<ScanHistoryEntry[]>('/api/history/timestamps'),
  data: (scanId: number) =>
    api.get<Record<string, unknown>[]>(`/api/history/data?scan_id=${scanId}`),
};

// ── Research Evidence (FORTRESS-V2) ─────────────────────────────────────────
//
// Real FORTRESS-R2 forward-return evidence for a current Fortress score.
// `available: false` in the response is not a fetch failure — it is the
// honest "no real result for this bucket/horizon (yet)" case; callers must
// render that as insufficient-evidence, never substitute fixture data.

import type { RealEvidenceResponse } from '@/lib/score-evidence';

export const researchEvidenceApi = {
  get: (score: number, horizon = 20, regime?: string) => {
    const params = new URLSearchParams({ score: String(score), horizon: String(horizon) });
    if (regime) params.set('regime', regime);
    return api.get<RealEvidenceResponse>(`/api/research-evidence?${params.toString()}`);
  },
};

// ── Options ────────────────────────────────────────────────────────────────

export const optionsApi = {
  expiries: (symbol: string) =>
    api.get<string[]>(`/api/options/expiries?symbol=${encodeURIComponent(symbol)}`),
  chain: (symbol: string, expiry: string, oiThreshold = 10000) =>
    api.get<{
      symbol: string;
      expiry: string;
      spot: number;
      chain: Record<string, unknown>[];
      strategies: Record<string, unknown>[];
    }>(
      `/api/options/chain?symbol=${encodeURIComponent(symbol)}&expiry=${encodeURIComponent(
        expiry
      )}&oi_threshold=${oiThreshold}`
    ),
};

// ── REITs & InvITs ────────────────────────────────────────────────────────────

import type { InvestmentInstrument, RefreshJob, WatchlistItem, PortfolioItem } from '@/lib/types';

export const reitApi = {
  list: (opts?: { type?: string; sort_by?: string; desc?: boolean }) => {
    const params = new URLSearchParams();
    if (opts?.type) params.set('type', opts.type);
    if (opts?.sort_by) params.set('sort_by', opts.sort_by);
    if (opts?.desc !== undefined) params.set('desc', String(opts.desc));
    const qs = params.toString();
    return api.get<InvestmentInstrument[]>(`/api/reit-invits${qs ? `?${qs}` : ''}`);
  },
  detail: (symbol: string) =>
    api.get<InvestmentInstrument>(`/api/reit-invits/${encodeURIComponent(symbol)}`),
  refresh: (force = false) =>
    api.post<{ status: string; message: string }>('/api/reit-invits/refresh', { force }),
  status: () => api.get<RefreshJob>('/api/reit-invits/status'),
};

// ── US Investing ──────────────────────────────────────────────────────────────

export const usInvestingApi = {
  list: (opts?: {
    asset_type?: string;
    sector?: string;
    include_inr?: boolean;
    sort_by?: string;
    desc?: boolean;
  }) => {
    const params = new URLSearchParams();
    if (opts?.asset_type) params.set('asset_type', opts.asset_type);
    if (opts?.sector) params.set('sector', opts.sector);
    if (opts?.include_inr !== undefined) params.set('include_inr', String(opts.include_inr));
    if (opts?.sort_by) params.set('sort_by', opts.sort_by);
    if (opts?.desc !== undefined) params.set('desc', String(opts.desc));
    const qs = params.toString();
    return api.get<InvestmentInstrument[]>(`/api/us-investing${qs ? `?${qs}` : ''}`);
  },
  detail: (symbol: string, includeInr = true) =>
    api.get<InvestmentInstrument>(
      `/api/us-investing/${encodeURIComponent(symbol)}?include_inr=${includeInr}`
    ),
  search: (q: string) =>
    api.get<Record<string, unknown>[]>(`/api/us-investing/search?q=${encodeURIComponent(q)}`),
  refresh: (force = false, include_inr = true) =>
    api.post<{ status: string; message: string }>('/api/us-investing/refresh', {
      force,
      include_inr,
    }),
  status: () => api.get<RefreshJob>('/api/us-investing/status'),
};

// ── Investments (Watchlist & Portfolio) ───────────────────────────────────────

export const investmentsApi = {
  watchlist: {
    list: () => api.get<WatchlistItem[]>('/api/investments/watchlist'),
    add: (item: { symbol: string; name?: string; asset_class: string; notes?: string }) =>
      api.post<{ status: string; symbol: string }>('/api/investments/watchlist', item),
    remove: (symbol: string) =>
      api.delete<{ status: string; symbol: string }>(
        `/api/investments/watchlist/${encodeURIComponent(symbol)}`
      ),
  },
  portfolio: {
    list: () => api.get<PortfolioItem[]>('/api/investments/portfolio'),
    upsert: (item: Omit<PortfolioItem, 'id' | 'updated_at' | 'pnl_pct' | 'current_price'>) =>
      api.post<{ status: string; symbol: string }>('/api/investments/portfolio', item),
    remove: (symbol: string) =>
      api.delete<{ status: string; symbol: string }>(
        `/api/investments/portfolio/${encodeURIComponent(symbol)}`
      ),
  },
  refreshStatus: (jobType?: string) => {
    const qs = jobType ? `?job_type=${encodeURIComponent(jobType)}` : '';
    return api.get<RefreshJob | RefreshJob[]>(`/api/investments/refresh-status${qs}`);
  },
};
