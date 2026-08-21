// src/app/screener/page.tsx — Stock Screener (most complex page)
'use client';

import React, { useEffect, useState, useCallback } from 'react';
import { scanApi, type ScanPayload } from '@/lib/api';
import { useToast } from '@/contexts/ToastContext';
import MetricCard from '@/components/MetricCard';
import DataTable from '@/components/DataTable';
import SectorIntelligence, { type SectorPulse } from '@/components/SectorIntelligence';
import ScoreHeatmap, { type HeatmapData } from '@/components/ScoreHeatmap';

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

  const [results, setResults] = useState<Record<string, unknown>[]>([]);
  const [sectorPulse, setSectorPulse] = useState<Record<string, unknown>[]>([]);
  const [loading, setLoading] = useState(false);
  const [showAdvanced, setShowAdvanced] = useState(false);

  useEffect(() => {
    scanApi.getUniverses().then(u => {
      setUniverses(u);
      if (u.length > 0) setUniverse(u[0]);
    }).catch(() => {});
  }, []);

  const runScan = useCallback(async () => {
    setLoading(true);
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
      const data = await scanApi.runScan(payload);
      setResults(data);
      success(`Scan completed — ${data.length} results`);

      // Also fetch sector pulse
      try {
        const sp = await scanApi.getSectorPulse(universe);
        setSectorPulse(sp);
      } catch {}
    } catch (err: unknown) {
      error(`Scan failed: ${(err as Error).message}`);
    } finally {
      setLoading(false);
    }
  }, [universe, portfolioVal, riskPct, weights, enableRegime, liquidityMin, marketCapMin, priceMin, broker, success, error]);

  const momentum = results.filter(r => r.Strategy === 'Momentum Pick');
  const longTerm = results.filter(r => r.Strategy === 'Long-Term Pick');
  const actionable = results.filter(r => r.Quality_Gate_Pass === true);
  const sectorPulseRows = sectorPulse as unknown as SectorPulse[];
  const actionableHeatmapRows = actionable as unknown as HeatmapData[];
  const filtered = results.filter(r => r.Quality_Gate_Pass === false);

  return (
    <>
      <div className="page-header">
        <h1 className="page-title">📊 Stock Screener</h1>
        <p className="page-subtitle">Configure scan parameters below, then run the screener to find actionable setups.</p>
      </div>

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

        <button className="btn btn-primary btn-block" onClick={runScan} disabled={loading || !universe}>
          {loading ? (
            <>
              <span className="spinner" style={{ width: 18, height: 18, borderWidth: 2 }} />
              Scanning…
            </>
          ) : (
            '🔍 Run Screener'
          )}
        </button>
      </div>

      {results.length === 0 && !loading && (
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

      {/* ── Summary metrics ─────────────────────────────────────────────── */}
      {results.length > 0 && (
        <div className="grid-4" style={{ marginBottom: '24px' }}>
          <MetricCard label="Total Results" value={results.length} />
          <MetricCard label="Actionable" value={actionable.length} deltaType="positive" />
          <MetricCard label="Momentum Picks" value={momentum.length} />
          <MetricCard label="Long-Term Picks" value={longTerm.length} />
        </div>
      )}

      {/* ── Strategic splits ────────────────────────────────────────────── */}
      {momentum.length > 0 && (
        <div className="section">
          <h3 className="section-title">🚀 Momentum Picks ({momentum.length})</h3>
          <DataTable data={momentum} columns={['Symbol', 'Company', 'Price', 'Score', 'Strategy', 'Velocity', 'Target_10D', 'Stop_Loss', 'Position_Qty']} />
        </div>
      )}

      {longTerm.length > 0 && (
        <div className="section">
          <h3 className="section-title">💎 Long-Term Picks ({longTerm.length})</h3>
          <DataTable data={longTerm} columns={['Symbol', 'Company', 'Price', 'Score', 'Strategy', 'Velocity', 'Target_10D', 'Stop_Loss', 'Position_Qty']} />
        </div>
      )}

      {/* ── Full Results ────────────────────────────────────────────────── */}
      {results.length > 0 && (
        <div className="section">
          <h3 className="section-title">📋 All Scan Results</h3>
          <DataTable data={results} />
        </div>
      )}

      {/* ── Filtered Out ────────────────────────────────────────────────── */}
      {filtered.length > 0 && (
        <div className="section">
          <div className="expander">
            <div className="expander-header">
              Filtered Out ({filtered.length}) — Hard Quality Gates
            </div>
            <div className="expander-body">
              <DataTable data={filtered} />
            </div>
          </div>
        </div>
      )}
    </>
  );
}
