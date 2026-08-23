// src/app/picks/page.tsx
'use client';

import React, { useState, useEffect, useCallback } from 'react';
import { picksApi, type PickSummary } from '@/lib/api';
import { useToast } from '@/contexts/ToastContext';
import DataTable from '@/components/DataTable';
import MetricCard from '@/components/MetricCard';

const OUTCOME_FILTERS = ['All', 'TRAILING', 'HIT_T1', 'HIT_T2', 'MISS', 'EXPIRED'];

export default function PicksPage() {
  const { success, error } = useToast();
  const [picks, setPicks] = useState<Record<string, unknown>[]>([]);
  const [summary, setSummary] = useState<PickSummary | null>(null);
  const [statusFilter, setStatusFilter] = useState('All');
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);

  const [showForm, setShowForm] = useState(false);
  const [symbol, setSymbol] = useState('');
  const [entryPrice, setEntryPrice] = useState('');
  const [targetPrice, setTargetPrice] = useState('');
  const [stopLoss, setStopLoss] = useState('');
  const [strategy, setStrategy] = useState('');
  const [creating, setCreating] = useState(false);

  const loadData = useCallback(() => {
    setLoading(true);
    setLoadError(null);
    Promise.all([
      picksApi.list(statusFilter === 'All' ? undefined : statusFilter),
      picksApi.summary(),
    ])
      .then(([p, s]) => {
        setPicks(p);
        setSummary(s);
      })
      .catch((err: unknown) => {
        setLoadError((err as Error).message || 'Unknown error');
      })
      .finally(() => setLoading(false));
  }, [statusFilter]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    loadData();
  }, [loadData]);

  const handleTrackPick = async (e: React.FormEvent) => {
    e.preventDefault();
    const entry = Number(entryPrice);
    const target = Number(targetPrice);
    const sl = Number(stopLoss);
    if (!symbol.trim() || !entry || !target || !sl) {
      error('Symbol, entry price, target price, and stop loss are all required.');
      return;
    }
    setCreating(true);
    try {
      await picksApi.record({
        symbol: symbol.trim().toUpperCase(),
        entry_price: entry,
        target_price: target,
        stop_loss: sl,
        strategy: strategy.trim(),
      });
      success(`${symbol.trim().toUpperCase()} is now being tracked.`);
      setSymbol('');
      setEntryPrice('');
      setTargetPrice('');
      setStopLoss('');
      setStrategy('');
      setShowForm(false);
      loadData();
    } catch (err: unknown) {
      error((err as Error).message || 'Failed to track pick');
    }
    setCreating(false);
  };

  return (
    <>
      <div className="page-header">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: 12 }}>
          <div>
            <h1 className="page-title">🎯 Picks Tracker</h1>
            <p className="page-subtitle">See whether your past picks actually hit their targets — win rate, average P&amp;L, and days to resolve.</p>
          </div>
          <button className="btn btn-primary" onClick={() => setShowForm(v => !v)}>
            {showForm ? 'Cancel' : '+ Track a Pick'}
          </button>
        </div>
      </div>

      {showForm && (
        <div className="card" style={{ marginBottom: '24px' }}>
          <h3 className="section-title">Track a New Pick</h3>
          <form onSubmit={handleTrackPick}>
            <div className="grid-4" style={{ marginBottom: '16px' }}>
              <div className="input-group">
                <label>Symbol *</label>
                <input className="input" required value={symbol} onChange={e => setSymbol(e.target.value)} placeholder="e.g. RELIANCE" />
              </div>
              <div className="input-group">
                <label>Entry Price *</label>
                <input className="input" type="number" min="0" step="any" required value={entryPrice} onChange={e => setEntryPrice(e.target.value)} />
              </div>
              <div className="input-group">
                <label>Target Price *</label>
                <input className="input" type="number" min="0" step="any" required value={targetPrice} onChange={e => setTargetPrice(e.target.value)} />
              </div>
              <div className="input-group">
                <label>Stop Loss *</label>
                <input className="input" type="number" min="0" step="any" required value={stopLoss} onChange={e => setStopLoss(e.target.value)} />
              </div>
            </div>
            <div className="input-group" style={{ marginBottom: '16px', maxWidth: '400px' }}>
              <label>Strategy (optional)</label>
              <input className="input" value={strategy} onChange={e => setStrategy(e.target.value)} placeholder="e.g. Breakout, Momentum" />
            </div>
            <button className="btn btn-primary" type="submit" disabled={creating}>
              {creating ? 'Tracking...' : 'Track Pick'}
            </button>
          </form>
        </div>
      )}

      <div className="grid-5" style={{ marginBottom: '24px' }}>
        <MetricCard label="Total Picks" value={summary?.total ?? 0} />
        <MetricCard label="Hit Rate" value={`${summary?.hit_rate ?? 0}%`} deltaType={summary && summary.hit_rate >= 50 ? 'positive' : 'negative'} />
        <MetricCard label="Avg P&L" value={`${summary?.avg_pnl ?? 0}%`} deltaType={summary && summary.avg_pnl >= 0 ? 'positive' : 'negative'} />
        <MetricCard label="Best Pick" value={`${summary?.best_pnl ?? 0}%`} deltaType="positive" />
        <MetricCard label="Still Trailing" value={summary?.trailing ?? 0} deltaType="neutral" />
      </div>

      <div className="card" style={{ marginBottom: '24px' }}>
        <div className="input-group" style={{ maxWidth: '260px' }}>
          <label>Outcome</label>
          <select className="input" value={statusFilter} onChange={e => setStatusFilter(e.target.value)}>
            {OUTCOME_FILTERS.map(s => <option key={s} value={s}>{s}</option>)}
          </select>
        </div>
      </div>

      <div className="section">
        {loading ? (
          <div className="loading-overlay">Loading picks...</div>
        ) : loadError ? (
          <div className="empty-state">
            <div className="icon">⚠️</div>
            <p>Couldn&apos;t load picks: {loadError}</p>
            <button className="btn btn-secondary" style={{ marginTop: 12 }} onClick={loadData}>
              Retry
            </button>
          </div>
        ) : (
          <DataTable data={picks} emptyMessage="No picks tracked yet. Track your first pick above." />
        )}
      </div>
    </>
  );
}
