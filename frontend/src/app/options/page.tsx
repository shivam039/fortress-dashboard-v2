'use client';

import React, { useEffect, useState } from 'react';
import DataTable from '@/components/DataTable';
import { optionsApi, OptionsSnapshotSummary } from '@/lib/api';
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
  const explorePayoff = async () => {
    if (atmStrike == null) return;
    const premium = 10;
    const prices = Array.from({ length: 9 }, (_, index) => Math.max(1, atmStrike - 4 * premium + index * premium));
    try {
      setPayoffResult(await optionsApi.payoff([{ option_type: 'CE', strike: atmStrike, premium }], prices));
    } catch (err: unknown) {
      error((err as Error).message);
    }
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
        <DataTable
          data={snapshots.map((snapshot) => ({ ...snapshot }))}
          columns={['captured_at', 'provider', 'spot', 'freshness', 'snapshot_id']}
          maxRows={10}
          emptyMessage="No prior options snapshots available."
        />
      </div>

      <div className="section">
        <h3 className="section-title">Strategy Lab</h3>
        <p className="page-subtitle">Read-only expiry payoff exploration using the canonical ATM strike. This does not place orders.</p>
        <button className="btn btn-secondary" onClick={explorePayoff} disabled={atmStrike == null}>Explore ATM call payoff</button>
        {payoffResult && <DataTable data={payoffResult.prices.map((price, index) => ({ Underlying: price, 'Expiry P/L': payoffResult.payoff[index] }))} columns={['Underlying', 'Expiry P/L']} emptyMessage="No payoff data." />}
        {payoffResult && <p className="page-subtitle">Breakevens: {JSON.stringify(payoffResult.summary.breakevens ?? [])} · Max loss: {String(payoffResult.summary.max_loss ?? 'Unavailable')} · Max profit: {String(payoffResult.summary.max_profit ?? 'Unavailable')}</p>}
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
