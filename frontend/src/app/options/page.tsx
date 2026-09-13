'use client';

import React, { useEffect, useState } from 'react';
import DataTable from '@/components/DataTable';
import { optionsApi, OptionsSnapshotComparison, OptionsSnapshotSummary } from '@/lib/api';
import { useToast } from '@/contexts/ToastContext';

export default function OptionsPage() {
  const { error } = useToast();
  const [symbol, setSymbol] = useState(() => typeof window !== 'undefined' ? new URLSearchParams(window.location.search).get('symbol') || 'Nifty 50' : 'Nifty 50');
  const [expiries, setExpiries] = useState<string[]>([]);
  const [expiry, setExpiry] = useState('');
  const [oiThreshold, setOiThreshold] = useState(10000);
  const [spot, setSpot] = useState<number | null>(null);
  const [chain, setChain] = useState<Record<string, unknown>[]>([]);
  const [strategies, setStrategies] = useState<Record<string, unknown>[]>([]);
  const [provider, setProvider] = useState('—');
  const [freshness, setFreshness] = useState('—');
  const [lastUpdated, setLastUpdated] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [loadingExpiries, setLoadingExpiries] = useState(false);
  const [showAllStrikes, setShowAllStrikes] = useState(false);
  const [analytics, setAnalytics] = useState<Record<string, unknown>>({});
  const [payoffResult, setPayoffResult] = useState<{ prices: number[]; payoff: number[]; summary: Record<string, unknown> } | null>(null);
  const [snapshots, setSnapshots] = useState<OptionsSnapshotSummary[]>([]);
  const [comparison, setComparison] = useState<OptionsSnapshotComparison | null>(null);
  type LabLeg = { option_type: 'CE' | 'PE'; strike: number; premium: number; quantity: number; side: 'BUY' | 'SELL' };
  const [labLegs, setLabLegs] = useState<LabLeg[]>([]);
  const [labRange, setLabRange] = useState(40);

  const numeric = (row: Record<string, unknown>, key: string): number | null => {
    const value = row[key];
    return typeof value === "number" && Number.isFinite(value) ? value : null;
  };
  const strikes = [...new Set(chain.map((row) => numeric(row, 'Strike')).filter((value): value is number => value !== null))].sort((a, b) => a - b);
  const atmStrike = typeof analytics.atm === 'number' ? analytics.atm : null;
  const atmIndex = atmStrike == null ? -1 : strikes.indexOf(atmStrike);
  const visibleStrikes = showAllStrikes || atmIndex < 0
    ? strikes
    : strikes.slice(Math.max(0, atmIndex - 5), atmIndex + 6);
  const visibleChain = chain.filter((row) => { const strike = numeric(row, 'Strike'); return strike !== null && visibleStrikes.includes(strike); });
  const largest = (key: string) => analytics[key] as { strike?: number; oi?: number } | null;
  const riskMetric = (value: unknown) => value === null ? 'UNBOUNDED / NOT FINITE' : typeof value === 'number' ? value.toFixed(2) : 'Unavailable';
  const runStrategy = async (legs = labLegs) => {
    if (atmStrike == null) return;
    if (legs.length === 0) return;
    const step = Math.max(1, Math.round(atmStrike * 0.05));
    const prices = Array.from({ length: 17 }, (_, index) => Math.max(1, atmStrike - labRange + index * Math.ceil((labRange * 2) / 16 / step) * step));
    try {
      setPayoffResult(await optionsApi.payoff(legs, prices));
    } catch (err: unknown) {
      error((err as Error).message);
    }
  };

  const loadPreset = (preset: 'call' | 'put' | 'straddle' | 'spread') => {
    if (atmStrike == null) return;
    const premium = 10;
    const width = Math.max(1, Math.round(atmStrike * 0.05));
    const presets: Record<string, LabLeg[]> = {
      call: [{ option_type: 'CE', strike: atmStrike, premium, quantity: 1, side: 'BUY' }],
      put: [{ option_type: 'PE', strike: atmStrike, premium, quantity: 1, side: 'BUY' }],
      straddle: [
        { option_type: 'CE', strike: atmStrike, premium, quantity: 1, side: 'BUY' },
        { option_type: 'PE', strike: atmStrike, premium, quantity: 1, side: 'BUY' },
      ],
      spread: [
        { option_type: 'CE', strike: atmStrike, premium, quantity: 1, side: 'BUY' },
        { option_type: 'CE', strike: atmStrike + width, premium: premium / 2, quantity: 1, side: 'SELL' },
      ],
    };
    const next = presets[preset];
    setLabLegs(next);
    void runStrategy(next);
  };

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setLoadingExpiries(true);
    optionsApi
      .expiries(symbol)
      .then((items) => {
        setExpiries(items);
        setExpiry(items[0] || '');
      })
      .catch((err: unknown) => error((err as Error).message))
      .finally(() => setLoadingExpiries(false));
  }, [symbol, error]);

  const loadChain = async () => {
    if (!symbol || !expiry) return;
    setLoading(true);
    try {
      const data = await optionsApi.chain(symbol, expiry, oiThreshold);
      setSpot(data.spot);
      setChain(data.chain);
      setStrategies(data.strategies);
      setProvider(data.provider || 'Unavailable');
      setFreshness(data.freshness || 'Unavailable');
      setLastUpdated(data.received_at || null);
      setAnalytics(data.analytics || {});
      optionsApi.history(symbol, expiry).then(setSnapshots).catch(() => setSnapshots([]));
      optionsApi.compareHistory(symbol, expiry).then(setComparison).catch(() => setComparison(null));
    } catch (err: unknown) {
      error((err as Error).message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (expiry) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      loadChain();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [expiry, oiThreshold]);

  return (
    <>
      <div className="page-header">
        <h1 className="page-title">⚡ Options</h1>
        <p className="page-subtitle">
          Live chain snapshot, expiries, and strategy ideas from the backend options engine.
        </p>
      </div>

      <div className="card" style={{ marginBottom: '24px' }}>
        <div className="grid-4">
          <div className="input-group">
            <label>Underlying</label>
            <select className="input" value={symbol} onChange={(e) => setSymbol(e.target.value)}>
              <option value="Nifty 50">Nifty 50</option>
              <option value="Nifty Next 50">Nifty Next 50</option>
              <option value="Nifty Midcap 150">Nifty Midcap 150</option>
              <option value="Nifty Smallcap 250">Nifty Smallcap 250</option>
            </select>
          </div>
          <div className="input-group">
            <label>Expiry</label>
            <select
              className="input"
              value={expiry}
              onChange={(e) => setExpiry(e.target.value)}
              disabled={loadingExpiries || expiries.length === 0}
            >
              {expiries.map((item) => (
                <option key={item} value={item}>
                  {item}
                </option>
              ))}
            </select>
          </div>
          <div className="input-group">
            <label>OI Threshold</label>
            <input
              className="input"
              type="number"
              value={oiThreshold}
              onChange={(e) => setOiThreshold(Number(e.target.value))}
            />
          </div>
          <div className="input-group" style={{ display: 'flex', alignItems: 'end' }}>
            <button className="btn btn-primary btn-block" onClick={loadChain} disabled={loading || !expiry}>
              {loading ? 'Loading...' : 'Load Chain'}
            </button>
          </div>
        </div>
      </div>

      <div className="grid-4" style={{ marginBottom: '24px' }}>
        <div className="metric-card">
          <span className="metric-label">Underlying</span>
          <span className="metric-value">{symbol}</span>
        </div>
        <div className="metric-card">
          <span className="metric-label">Expiry</span>
          <span className="metric-value">{expiry || '—'}</span>
        </div>
        <div className="metric-card">
          <span className="metric-label">Spot</span>
          <span className="metric-value">{spot ? spot.toFixed(2) : '—'}</span>
        </div>
        <div className="metric-card">
          <span className="metric-label">ATM Strike</span>
          <span className="metric-value">{atmStrike == null ? '—' : atmStrike.toFixed(2)}</span>
        </div>
      </div>

      <div className="card" style={{ marginBottom: '24px' }}>
        <div className="grid-4">
          <div><span className="metric-label">Provider</span><div>{provider}</div></div>
          <div><span className="metric-label">Freshness</span><div>{freshness}</div></div>
          <div><span className="metric-label">Last updated</span><div>{lastUpdated ? new Date(lastUpdated).toLocaleString() : '—'}</div></div>
          <div><span className="metric-label">Rows shown</span><div>{visibleChain.length} / {chain.length}</div></div>
          <div><span className="metric-label">Put/Call OI</span><div>{typeof analytics.oi_pcr === 'number' ? analytics.oi_pcr.toFixed(2) : 'Unavailable'}</div></div>
          <div><span className="metric-label">Highest call OI</span><div>{largest('largest_call_oi')?.strike != null ? `${largest('largest_call_oi')!.strike!.toFixed(2)} (${largest('largest_call_oi')!.oi?.toLocaleString() ?? '—'})` : 'Unavailable'}</div></div>
        </div>
        <div style={{ marginTop: '12px' }}><span className="metric-label">Highest put OI</span>{largest('largest_put_oi')?.strike != null ? `${largest('largest_put_oi')!.strike!.toFixed(2)} (${largest('largest_put_oi')!.oi?.toLocaleString() ?? '—'})` : ' Unavailable'}</div>
        <p className="page-subtitle" style={{ marginTop: '12px' }}>OI and PCR are descriptive indicators, not trading recommendations. ATM is the available strike nearest to spot.</p>
      </div>

      <div className="section" style={{ marginBottom: '24px' }}>
        <h3 className="section-title">Chain Snapshot</h3>
        <DataTable
          data={visibleChain}
          columns={['Strike', 'Type', 'Moneyness', 'LTP', 'OI', 'ChangeOI', 'Volume', 'IV', 'Bid', 'Ask']}
          emptyMessage="No options chain loaded yet."
          maxRows={24}
        />
        {strikes.length > 11 && (
          <button className="btn btn-secondary" style={{ marginTop: '12px' }} onClick={() => setShowAllStrikes((current) => !current)}>
            {showAllStrikes ? 'Show ATM window' : `Show all ${strikes.length} strikes`}
          </button>
        )}
      </div>

      <div className="section">
        <h3 className="section-title">What Changed?</h3>
        <p className="page-subtitle">Successful snapshots are shown for provenance. No historical value is inferred when a prior observation is unavailable.</p>
        <p className="page-subtitle">
          {comparison?.status === 'COMPARABLE'
            ? `Compared with the previous snapshot: spot ${comparison.changes.spot?.changed ? 'changed' : 'unchanged'}, provider ${comparison.changes.provider?.changed ? 'changed' : 'unchanged'}.`
            : 'What Changed? is unavailable until two successful snapshots exist.'}
        </p>
        <DataTable
          data={snapshots.map((snapshot) => ({ ...snapshot }))}
          columns={['captured_at', 'provider', 'spot', 'freshness', 'snapshot_id']}
          maxRows={10}
          emptyMessage="No prior options snapshots available."
        />
      </div>

      <div className="section">
        <h3 className="section-title">Strategy Lab</h3>
        <p className="page-subtitle">Read-only, expiry-only multi-leg analysis. Premiums and legs are explicit; this never places orders or predicts probability.</p>
        <div className="grid-4" style={{ marginBottom: '12px' }}>
          <button className="btn btn-secondary" onClick={() => loadPreset('call')} disabled={atmStrike == null}>Long call</button>
          <button className="btn btn-secondary" onClick={() => loadPreset('put')} disabled={atmStrike == null}>Long put</button>
          <button className="btn btn-secondary" onClick={() => loadPreset('straddle')} disabled={atmStrike == null}>Long straddle</button>
          <button className="btn btn-secondary" onClick={() => loadPreset('spread')} disabled={atmStrike == null}>Call spread</button>
        </div>
        {labLegs.map((leg, index) => (
          <div className="grid-4" key={`${index}-${leg.option_type}`} style={{ marginBottom: '8px' }}>
            <select className="input" value={leg.side} onChange={(e) => setLabLegs((items) => items.map((item, i) => i === index ? { ...item, side: e.target.value as LabLeg['side'] } : item))}><option>BUY</option><option>SELL</option></select>
            <select className="input" value={leg.option_type} onChange={(e) => setLabLegs((items) => items.map((item, i) => i === index ? { ...item, option_type: e.target.value as LabLeg['option_type'] } : item))}><option>CE</option><option>PE</option></select>
            <input className="input" type="number" aria-label={`Strike ${index + 1}`} value={leg.strike} onChange={(e) => setLabLegs((items) => items.map((item, i) => i === index ? { ...item, strike: Number(e.target.value) } : item))} />
            <input className="input" type="number" aria-label={`Premium ${index + 1}`} value={leg.premium} onChange={(e) => setLabLegs((items) => items.map((item, i) => i === index ? { ...item, premium: Number(e.target.value) } : item))} />
          </div>
        ))}
        <div style={{ display: 'flex', gap: '8px', alignItems: 'end' }}>
          <button className="btn btn-secondary" onClick={() => setLabLegs((items) => [...items, { option_type: 'CE', strike: atmStrike ?? 0, premium: 10, quantity: 1, side: 'BUY' }])} disabled={atmStrike == null}>Add leg</button>
          <label className="input-group"><span className="metric-label">Range around ATM</span><input className="input" type="number" value={labRange} min={1} onChange={(e) => setLabRange(Number(e.target.value))} /></label>
          <button className="btn btn-primary" onClick={() => void runStrategy()} disabled={labLegs.length === 0 || atmStrike == null}>Calculate payoff</button>
        </div>
        {payoffResult && <DataTable data={payoffResult.prices.map((price, index) => ({ Underlying: price, 'Expiry P/L': payoffResult.payoff[index] }))} columns={['Underlying', 'Expiry P/L']} emptyMessage="No payoff data." />}
        {payoffResult && <p className="page-subtitle">Breakevens: {JSON.stringify(payoffResult.summary.breakevens ?? [])} · Theoretical max loss: {riskMetric(payoffResult.summary.max_loss)} · Theoretical max profit: {riskMetric(payoffResult.summary.max_profit)}</p>}
      </div>

      <div className="section">
        <h3 className="section-title">Legacy Strategy Scanner</h3>
        <p className="page-subtitle">Descriptive legacy suggestions only; not a recommendation or risk model. Use Strategy Lab above for explicit, read-only payoff analysis.</p>
        <DataTable
          data={strategies}
          emptyMessage="No strategy ideas matched the current threshold."
        />
      </div>
    </>
  );
}
