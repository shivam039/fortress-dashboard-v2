'use client';

import React, { useEffect, useState } from 'react';
import DataTable from '@/components/DataTable';
import { optionsApi } from '@/lib/api';
import { useToast } from '@/contexts/ToastContext';

export default function OptionsPage() {
  const { error } = useToast();
  const [symbol, setSymbol] = useState('Nifty 50');
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

  const numeric = (row: Record<string, unknown>, key: string) => {
    const value = Number(row[key]);
    return Number.isFinite(value) ? value : 0;
  };
  const strikes = [...new Set(chain.map((row) => numeric(row, 'Strike')).filter(Boolean))].sort((a, b) => a - b);
  const atmStrike = spot == null || strikes.length === 0
    ? null
    : strikes.reduce((nearest, strike) => Math.abs(strike - spot) < Math.abs(nearest - spot) ? strike : nearest, strikes[0]);
  const atmIndex = atmStrike == null ? -1 : strikes.indexOf(atmStrike);
  const visibleStrikes = showAllStrikes || atmIndex < 0
    ? strikes
    : strikes.slice(Math.max(0, atmIndex - 5), atmIndex + 6);
  const visibleChain = chain.filter((row) => visibleStrikes.includes(numeric(row, 'Strike')));
  const isCall = (row: Record<string, unknown>) => ['CALL', 'CE'].includes(String(row.Type ?? '').toUpperCase());
  const isPut = (row: Record<string, unknown>) => ['PUT', 'PE'].includes(String(row.Type ?? '').toUpperCase());
  const callOi = chain.filter(isCall)
    .sort((a, b) => numeric(b, 'OI') - numeric(a, 'OI')).slice(0, 3);
  const putOi = chain.filter(isPut)
    .sort((a, b) => numeric(b, 'OI') - numeric(a, 'OI')).slice(0, 3);
  const pcr = chain.filter(isPut).reduce((sum, row) => sum + numeric(row, 'OI'), 0)
    / Math.max(1, chain.filter(isCall).reduce((sum, row) => sum + numeric(row, 'OI'), 0));

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
          <div><span className="metric-label">Put/Call OI</span><div>{chain.length ? pcr.toFixed(2) : '—'}</div></div>
          <div><span className="metric-label">Highest call OI</span><div>{callOi[0] ? `${numeric(callOi[0], 'Strike').toFixed(2)} (${numeric(callOi[0], 'OI').toLocaleString()})` : '—'}</div></div>
        </div>
        <div style={{ marginTop: '12px' }}><span className="metric-label">Highest put OI</span>{putOi.length ? putOi.map((row) => `${numeric(row, 'Strike').toFixed(2)} (${numeric(row, 'OI').toLocaleString()})`).join(' · ') : ' —'}</div>
        <p className="page-subtitle" style={{ marginTop: '12px' }}>OI and PCR are descriptive indicators, not trading recommendations. ATM is the available strike nearest to spot.</p>
      </div>

      <div className="section" style={{ marginBottom: '24px' }}>
        <h3 className="section-title">Chain Snapshot</h3>
        <DataTable
          data={visibleChain.map((row) => ({ ...row, Moneyness: numeric(row, 'Strike') === atmStrike ? 'ATM' : numeric(row, 'Strike') < (spot ?? 0) ? 'ITM' : 'OTM' }))}
          columns={['Strike', 'Type', 'IV', 'Delta', 'Gamma', 'Theta', 'Vega', 'OI', 'Premium']}
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
        <h3 className="section-title">Strategy Scanner</h3>
        <DataTable
          data={strategies}
          emptyMessage="No strategy ideas matched the current threshold."
        />
      </div>
    </>
  );
}
