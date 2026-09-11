// src/app/screener/page.tsx — Stock Screener (most complex page)
'use client';

import React, { useEffect, useRef, useState, useCallback, useMemo, useSyncExternalStore } from 'react';
import { scanApi, researchEvidenceApi, type ScanPayload, type SymbolSuggestion } from '@/lib/api';
import { useToast } from '@/contexts/ToastContext';
import { useAuth } from '@/contexts/AuthContext';
import { emptyScanState, getScanStore } from '@/lib/scan-state';
import { ScanStatus } from '@/components/ScanStatus';
import DataTable from '@/components/DataTable';
import SectorIntelligence, { type SectorPulse } from '@/components/SectorIntelligence';
import ScoreHeatmap, { type HeatmapData } from '@/components/ScoreHeatmap';
import ScannerResultsView from '@/components/ScannerResultsView';
import FortressScoreCard from '@/components/FortressScoreCard';
import HistoricalEvidenceCard from '@/components/HistoricalEvidenceCard';
import { toFortressSignal, fromRealEvidence, type HistoricalEvidence } from '@/lib/score-evidence';

// FORTRESS-V2: single default horizon for historical evidence, per the
// product decision documented in docs/research/score_forward_return_validation.md
// — do not let per-symbol code choose whichever horizon looks best.
const EVIDENCE_HORIZON_DAYS = 20;

const UNAVAILABLE_EVIDENCE: HistoricalEvidence = fromRealEvidence({
  available: false,
  score_bucket: '',
  horizon: EVIDENCE_HORIZON_DAYS,
});

export default function ScreenerPage() {
  const { success, error } = useToast();
  const [universes, setUniverses] = useState<string[]>([]);
  const [universe, setUniverse] = useState('');
  const [portfolioVal, setPortfolioVal] = useState(1000000);
  const [riskPct, setRiskPct] = useState(1.0);
  const [broker, setBroker] = useState('Zerodha');
  const [enableRegime, setEnableRegime] = useState(true);
  const [liquidityMin, setLiquidityMin] = useState(8.0);
  const [marketCapMin, setMarketCapMin] = useState(1500.0);
  const [priceMin, setPriceMin] = useState(80.0);
  const [weights, setWeights] = useState({ technical: 50, fundamental: 25, sentiment: 15, context: 10 });

  const { user } = useAuth();
  const store = useMemo(() => getScanStore(user?.username ?? ''), [user?.username]);
  const scan = useSyncExternalStore(store.subscribe, store.getSnapshot, () => emptyScanState);
  const results = scan.result?.results ?? [];
  const loading = scan.status === 'running';
  useEffect(() => { if (user) store.restore(); }, [store, user]);
  const [universeError, setUniverseError] = useState('');
  const [sectorPulse, setSectorPulse] = useState<Record<string, unknown>[]>([]);
  const [showAdvanced, setShowAdvanced] = useState(false);

  // ── Single-stock search ─────────────────────────────────────────────────
  const [searchQuery, setSearchQuery] = useState('');
  const [suggestions, setSuggestions] = useState<SymbolSuggestion[]>([]);
  const [showSuggestions, setShowSuggestions] = useState(false);
  const [searching, setSearching] = useState(false);
  const [searchResult, setSearchResult] = useState<Record<string, unknown>[]>([]);
  const [searchedSymbol, setSearchedSymbol] = useState('');
  const [historicalEvidence, setHistoricalEvidence] = useState<HistoricalEvidence>(UNAVAILABLE_EVIDENCE);
  const searchBoxRef = useRef<HTMLDivElement>(null);

  const loadUniverses = useCallback(() => {
    scanApi.getUniverses().then(u => {
      setUniverses(u);
      if (u.length > 0) { setUniverse(u[0]); setUniverseError(''); }
      else setUniverseError('No scan universes are available.');
    }).catch(() => setUniverseError('Could not load scan universes. Check your connection and retry.'));
  }, []);
  useEffect(() => { loadUniverses(); }, [loadUniverses]);

  // FORTRESS-V4: poll interval for the active job — cleared on unmount, on
  // job completion/failure, and when a new job starts. A ref (not state)
  // because it's plumbing for the poll loop, not something the UI renders.
  const pollTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const stopPolling = useCallback(() => {
    if (pollTimerRef.current !== null) {
      clearInterval(pollTimerRef.current);
      pollTimerRef.current = null;
    }
  }, []);

  const fetchSectorPulseAfterCompletion = useCallback((forUniverse: string) => {
    setSectorPulse([]);
    scanApi.getSectorPulse(forUniverse).then(sp => setSectorPulse(sp)).catch(() => {});
  }, []);

  // The single poll loop, reused both for a freshly-started job and for one
  // resumed after a page refresh — never starts a second job on its own.
  const pollJob = useCallback((jobId: string, forUniverse: string) => {
    stopPolling();
    pollTimerRef.current = setInterval(async () => {
      try {
        const job = await scanApi.getScanJobStatus(jobId);
        store.updateJobStatus(job);
        if (job.status === 'completed') {
          stopPolling();
          const results = await scanApi.getScanJobResults(jobId);
          store.completeJob(results);
          fetchSectorPulseAfterCompletion(forUniverse);
        } else if (job.status === 'failed') {
          stopPolling(); // store.updateJobStatus(job) above already recorded job.error
        }
      } catch (err: unknown) {
        // A transient poll failure (e.g. one dropped request) must not kill
        // an otherwise-healthy job — keep polling; only stop on a real 4xx.
        const status = err && typeof err === 'object' && 'status' in err ? (err as { status: number }).status : undefined;
        if (typeof status === 'number' && status >= 400 && status < 500) {
          stopPolling();
          store.failJob((err as Error).message || 'Scan job not found.');
        }
      }
    }, 2000);
  }, [store, stopPolling, fetchSectorPulseAfterCompletion]);

  // Resume polling an in-flight job after a refresh — never submits a new one.
  useEffect(() => {
    if (scan.status === 'running' && scan.jobId) {
      pollJob(scan.jobId, scan.universe);
    }
    return stopPolling;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const runScan = useCallback(async () => {
    if (scan.status === 'running') return; // one active job at a time
    try {
      const total = Math.max(weights.technical + weights.fundamental + weights.sentiment + weights.context, 1);
      const payload: ScanPayload = {
        universe,
        portfolio_val: portfolioVal,
        risk_pct: riskPct / 100,
        weights: {
          technical: weights.technical / total,
          fundamental: weights.fundamental / total,
          sentiment: weights.sentiment / total,
          context: weights.context / total,
        },
        enable_regime: enableRegime,
        liquidity_cr_min: liquidityMin,
        market_cap_cr_min: marketCapMin,
        price_min: priceMin,
        broker,
      };
      const { job_id } = await scanApi.startScanJob(payload);
      if (!store.startJob(universe, job_id)) return; // another job won the race
      pollJob(job_id, universe);
    } catch (err: unknown) {
      error(`Could not start scan: ${(err as Error).message}`);
    }
  }, [universe, portfolioVal, riskPct, weights, enableRegime, liquidityMin, marketCapMin, priceMin, broker, store, error, scan.status, pollJob]);

  // Debounced search-as-you-type suggestions — waits for a pause in typing
  // before hitting the backend so every keystroke doesn't fire a request.
  useEffect(() => {
    const query = searchQuery.trim();
    const timer = setTimeout(() => {
      if (query.length < 2) {
        setSuggestions([]);
        return;
      }
      scanApi.searchSymbols(query)
        .then(s => { setSuggestions(s); setShowSuggestions(true); })
        .catch(() => setSuggestions([]));
    }, 300);
    return () => clearTimeout(timer);
  }, [searchQuery]);

  // Close the suggestions dropdown on an outside click.
  useEffect(() => {
    const handleClick = (e: MouseEvent) => {
      if (searchBoxRef.current && !searchBoxRef.current.contains(e.target as Node)) {
        setShowSuggestions(false);
      }
    };
    document.addEventListener('mousedown', handleClick);
    return () => document.removeEventListener('mousedown', handleClick);
  }, []);

  const runSearch = useCallback(async (symbol: string) => {
    const ticker = symbol.trim();
    if (!ticker) return;
    setSearching(true);
    setShowSuggestions(false);
    setHistoricalEvidence(UNAVAILABLE_EVIDENCE); // never keep the previous symbol's evidence on screen mid-search
    try {
      const data = await scanApi.searchStock(ticker, universe || undefined);
      setSearchResult(data);
      setSearchedSymbol((data[0]?.Symbol as string) || ticker.toUpperCase());
      success(`Found ${(data[0]?.Symbol as string) || ticker}`);

      // FORTRESS-V2: real R2 evidence for this symbol's current score/regime.
      // A fetch failure or "available: false" both render as the honest
      // insufficient-evidence state — never a fixture number.
      if (data[0]) {
        const signal = toFortressSignal(data[0]);
        researchEvidenceApi
          .get(signal.totalScore, EVIDENCE_HORIZON_DAYS, signal.marketRegime)
          .then(resp => setHistoricalEvidence(fromRealEvidence(resp)))
          .catch(() => setHistoricalEvidence(UNAVAILABLE_EVIDENCE));
      }
    } catch (err: unknown) {
      setSearchResult([]);
      error(`Search failed: ${(err as Error).message}`);
    } finally {
      setSearching(false);
    }
  }, [universe, success, error]);

  const actionable = results.filter(r => r.Quality_Gate_Pass === true);
  const sectorPulseRows = sectorPulse as unknown as SectorPulse[];
  const actionableHeatmapRows = actionable as unknown as HeatmapData[];

  return (
    <>
      <div className="page-header">
        <h1 className="page-title">📊 Stock Screener</h1>
        <p className="page-subtitle">Configure scan parameters below, then run the screener to find actionable setups.</p>
      </div>

      {/* ── Stock Search ────────────────────────────────────────────────── */}
      <div className="card" style={{ marginBottom: '24px' }}>
        <h3 className="section-title" style={{ marginTop: 0 }}>🔎 Search a Stock</h3>
        <div style={{ display: 'flex', gap: '12px', alignItems: 'flex-end' }}>
          <div className="input-group" style={{ position: 'relative', flex: 1 }} ref={searchBoxRef}>
            <label>Ticker or company name</label>
            <input
              className="input"
              type="text"
              placeholder="e.g. RELIANCE or Reliance Industries"
              value={searchQuery}
              onChange={e => setSearchQuery(e.target.value)}
              onFocus={() => { if (suggestions.length > 0) setShowSuggestions(true); }}
              onKeyDown={e => { if (e.key === 'Enter') runSearch(searchQuery); }}
            />
            {showSuggestions && suggestions.length > 0 && (
              <ul className="search-suggestions">
                {suggestions.map(s => (
                  <li key={s.symbol} onClick={() => { setSearchQuery(s.symbol); runSearch(s.symbol); }}>
                    <strong>{s.symbol}</strong>
                    {s.name && <span className="suggestion-name">{s.name}</span>}
                  </li>
                ))}
              </ul>
            )}
          </div>
          <button
            className="btn btn-primary"
            onClick={() => runSearch(searchQuery)}
            disabled={searching || !searchQuery.trim()}
          >
            {searching ? 'Searching…' : '🔍 Search'}
          </button>
        </div>
      </div>

      {searchResult.length > 0 && (
        <div className="section" style={{ marginBottom: '24px' }}>
          <h3 className="section-title">📌 Search Result — {searchedSymbol}</h3>
          <div className="grid-2" style={{ gap: 16, marginBottom: 16, alignItems: 'start' }}>
            <FortressScoreCard signal={toFortressSignal(searchResult[0])} />
            {/* FORTRESS-V2: real GET /api/research-evidence result, mapped
                by fromRealEvidence(). If no real R2 result exists yet for
                this score bucket, this renders the honest "insufficient
                evidence" state — never fixture/illustrative numbers. */}
            <HistoricalEvidenceCard evidence={historicalEvidence} />
          </div>
          <DataTable data={searchResult} />
        </div>
      )}

      {/* ── Scan Controls ───────────────────────────────────────────────── */}
      <div className="card" style={{ marginBottom: '24px' }}>
        <div className="grid-4" style={{ marginBottom: '16px' }}>
          <div className="input-group">
            <label>Universe</label>
            <select className="input" value={universe} onChange={e => setUniverse(e.target.value)}>
              {universes.map(u => <option key={u} value={u}>{u}</option>)}
            </select>
          </div>
          <div className="input-group">
            <label>Portfolio (₹)</label>
            <input className="input" type="number" value={portfolioVal} onChange={e => setPortfolioVal(Number(e.target.value))} />
          </div>
          <div className="input-group">
            <label>Risk %</label>
            <input className="input" type="number" step="0.1" value={riskPct} onChange={e => setRiskPct(Number(e.target.value))} />
          </div>
          <div className="input-group">
            <label>Broker</label>
            <select className="input" value={broker} onChange={e => setBroker(e.target.value)}>
              <option value="Zerodha">Zerodha</option>
              <option value="Dhan">Dhan</option>
            </select>
          </div>
        </div>

        {/* Advanced Settings */}
        <div className="expander" style={{ marginBottom: '16px' }}>
          <div className="expander-header" onClick={() => setShowAdvanced(!showAdvanced)}>
            ⚙️ Advanced Scan Settings
            <span>{showAdvanced ? '▼' : '▶'}</span>
          </div>
          {showAdvanced && (
            <div className="expander-body">
              <div className="grid-4" style={{ marginBottom: '16px' }}>
                <div className="input-group">
                  <label>
                    <input type="checkbox" checked={enableRegime} onChange={e => setEnableRegime(e.target.checked)} style={{ marginRight: 6 }} />
                    Regime Scaling
                  </label>
                </div>
                <div className="input-group">
                  <label>Liquidity Gate (₹ Cr)</label>
                  <input className="input" type="number" step="0.5" value={liquidityMin} onChange={e => setLiquidityMin(Number(e.target.value))} />
                </div>
                <div className="input-group">
                  <label>Market Cap Gate (₹ Cr)</label>
                  <input className="input" type="number" step="50" value={marketCapMin} onChange={e => setMarketCapMin(Number(e.target.value))} />
                </div>
                <div className="input-group">
                  <label>Min Price (₹)</label>
                  <input className="input" type="number" step="5" value={priceMin} onChange={e => setPriceMin(Number(e.target.value))} />
                </div>
              </div>
              <div className="grid-4">
                {(['technical', 'fundamental', 'sentiment', 'context'] as const).map(w => (
                  <div className="input-group" key={w}>
                    <label>{w.charAt(0).toUpperCase() + w.slice(1)}: {weights[w]}</label>
                    <input type="range" min="0" max="100" value={weights[w]} onChange={e => setWeights(prev => ({ ...prev, [w]: Number(e.target.value) }))} />
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>

        {universeError ? <p role="alert">{universeError} <button className="btn" onClick={() => { setUniverseError(''); loadUniverses(); }}>Retry loading universes</button></p> : universes.length === 0 && <p role="status">Stage: loading scan universes…</p>}
        <button className="btn btn-primary btn-block" onClick={runScan} disabled={loading || !universe || !user}>
          {loading ? 'Scan request in progress…' : scan.status === 'unknown' ? 'Start another scan' : '🔍 Run Screener'}
        </button>
      </div>

      <ScanStatus state={scan} />

      {results.length === 0 && scan.status === 'idle' && (
        <div className="empty-state">
          <div className="icon">🔍</div>
          <p>Run a scan to see actionable stock setups here.</p>
        </div>
      )}

      {/* ── Sector Intelligence ─────────────────────────────────────────── */}
      {sectorPulse.length > 0 && (
        <div className="section">
          <h3 className="section-title">🔥 Sector Intelligence & Rotation</h3>
          <SectorIntelligence data={sectorPulseRows} />
        </div>
      )}

      {/* ── Heatmap ─────────────────────────────────────────────────────── */}
      {actionable.length > 0 && (
        <div className="section">
          <h3 className="section-title">🗺️ Conviction Heatmap</h3>
          <ScoreHeatmap data={actionableHeatmapRows} />
        </div>
      )}

      {/* ── Results (shared with the read-only Historical Stock Screener) ── */}
      <ScannerResultsView results={results} mode="live" />
    </>
  );
}
