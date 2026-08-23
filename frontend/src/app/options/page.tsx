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
  const [loading, setLoading] = useState(false);
  const [loadingExpiries, setLoadingExpiries] = useState(false);

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
          <span className="metric-label">Rows</span>
          <span className="metric-value">{chain.length}</span>
        </div>
      </div>

      <div className="section" style={{ marginBottom: '24px' }}>
        <h3 className="section-title">Chain Snapshot</h3>
        <DataTable
          data={chain}
          columns={['Strike', 'Type', 'IV', 'Delta', 'Gamma', 'Theta', 'Vega', 'OI', 'Premium']}
          emptyMessage="No options chain loaded yet."
          maxRows={24}
        />
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
