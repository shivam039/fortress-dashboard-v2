// src/app/reit-invits/page.tsx — REITs & InvITs investment section
'use client';

import React, { useState, useEffect, useMemo, useCallback } from 'react';
import { reitApi } from '@/lib/api';
import { useToast } from '@/contexts/ToastContext';
import type { InvestmentInstrument } from '@/lib/types';
import ConvictionScoreCard from '@/components/ConvictionScoreCard';
import DataFreshnessBadge from '@/components/DataFreshnessBadge';
import WatchlistButton from '@/components/WatchlistButton';

const SORT_OPTIONS = [
  { value: 'conviction_score', label: 'Conviction Score' },
  { value: 'yield_pct', label: 'Yield %' },
  { value: 'returns_1y', label: '1Y Return' },
  { value: 'returns_1m', label: '1M Return' },
  { value: 'confidence_score', label: 'Confidence' },
];

function fmt(v: number | null | undefined, suffix = '%', decimals = 1): string {
  if (v === null || v === undefined) return '—';
  return `${v >= 0 ? '' : ''}${v.toFixed(decimals)}${suffix}`;
}

function ReturnBadge({ value }: { value: number | null | undefined }) {
  if (value === null || value === undefined) return <span style={{ color: 'var(--text-muted)' }}>—</span>;
  const color = value >= 0 ? 'var(--color-success)' : 'var(--color-danger)';
  return <span style={{ color, fontWeight: 600 }}>{value >= 0 ? '+' : ''}{value.toFixed(1)}%</span>;
}

export default function ReitInvitsPage() {
  const { success, error } = useToast();
  const [instruments, setInstruments] = useState<InvestmentInstrument[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [typeFilter, setTypeFilter] = useState<'ALL' | 'REIT' | 'InvIT'>('ALL');
  const [sortBy, setSortBy] = useState('conviction_score');
  const [sortDesc, setSortDesc] = useState(true);
  const [search, setSearch] = useState('');
  const [selectedSymbol, setSelectedSymbol] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState<string | null>(null);

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const data = await reitApi.list({ sort_by: sortBy, desc: sortDesc });
      setInstruments(data);
      if (data.length > 0) setLastUpdated(data[0].last_updated);
    } catch (err: unknown) {
      error(`Failed to load REIT/InvIT data: ${(err as Error).message}`);
    } finally {
      setLoading(false);
    }
  }, [sortBy, sortDesc, error]);

  useEffect(() => { loadData(); }, [loadData]);

  const handleRefresh = async () => {
    setRefreshing(true);
    try {
      await reitApi.refresh(true);
      success('Refresh started — data will update in ~30 seconds');
      setTimeout(() => loadData(), 30_000);
    } catch (err: unknown) {
      error(`Refresh failed: ${(err as Error).message}`);
    } finally {
      setRefreshing(false);
    }
  };

  const filtered = useMemo(() => {
    let list = instruments;
    if (typeFilter !== 'ALL') list = list.filter(i => i.asset_class === typeFilter);
    if (search.trim()) {
      const q = search.toLowerCase();
      list = list.filter(i =>
        i.symbol.toLowerCase().includes(q) || i.name.toLowerCase().includes(q)
      );
    }
    return list;
  }, [instruments, typeFilter, search]);

  const summary = useMemo(() => ({
    count: filtered.length,
    avgYield: filtered.length
      ? filtered.reduce((s, i) => s + (i.yield_pct ?? 0), 0) / filtered.filter(i => i.yield_pct !== null).length
      : 0,
    avgScore: filtered.length
      ? filtered.reduce((s, i) => s + (i.conviction_score ?? 0), 0) / filtered.filter(i => i.conviction_score !== null).length
      : 0,
    topScore: filtered.length ? Math.max(...filtered.map(i => i.conviction_score ?? 0)) : 0,
  }), [filtered]);

  const selectedInstrument = instruments.find(i => i.symbol === selectedSymbol) ?? null;

  return (
    <>
      {/* ── Header ── */}
      <div className="page-header">
        <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', flexWrap: 'wrap', gap: 12 }}>
          <div>
            <h1 className="page-title">🏢 REITs & InvITs</h1>
            <p className="page-subtitle">
              Indian Real Estate Investment Trusts and Infrastructure Investment Trusts — conviction scores, yields, and risk analysis.
            </p>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
            <DataFreshnessBadge isoTimestamp={lastUpdated} />
            <button
              id="reit-refresh-btn"
              className="btn btn-secondary btn-sm"
              onClick={handleRefresh}
              disabled={refreshing || loading}
            >
              {refreshing ? '⟳ Refreshing…' : '⟳ Refresh Data'}
            </button>
          </div>
        </div>
      </div>

      {/* ── Summary cards ── */}
      <div className="metrics-row" style={{ marginBottom: 24 }}>
        {[
          { label: 'Instruments', value: summary.count.toString(), icon: '🏢' },
          { label: 'Avg Yield', value: isNaN(summary.avgYield) ? '—' : `${summary.avgYield.toFixed(1)}%`, icon: '💰' },
          { label: 'Avg Score', value: isNaN(summary.avgScore) ? '—' : summary.avgScore.toFixed(0), icon: '📊' },
          { label: 'Top Score', value: summary.topScore > 0 ? summary.topScore.toFixed(0) : '—', icon: '🏆' },
        ].map(m => (
          <div key={m.label} className="metric-card">
            <span className="metric-label">{m.icon} {m.label}</span>
            <span className="metric-value">{m.value}</span>
          </div>
        ))}
      </div>

      {/* ── Filters ── */}
      <div className="card" style={{ marginBottom: 20, padding: '14px 16px' }}>
        <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', alignItems: 'center' }}>
          <input
            id="reit-search"
            className="input"
            placeholder="Search by name or symbol…"
            value={search}
            onChange={e => setSearch(e.target.value)}
            style={{ minWidth: 200, flex: 1 }}
          />
          <div style={{ display: 'flex', gap: 6 }}>
            {(['ALL', 'REIT', 'InvIT'] as const).map(t => (
              <button
                key={t}
                id={`reit-filter-${t.toLowerCase()}`}
                className={`btn btn-sm ${typeFilter === t ? 'btn-primary' : 'btn-secondary'}`}
                onClick={() => setTypeFilter(t)}
              >
                {t}
              </button>
            ))}
          </div>
          <select
            id="reit-sort"
            className="input"
            value={sortBy}
            onChange={e => setSortBy(e.target.value)}
            style={{ minWidth: 160 }}
          >
            {SORT_OPTIONS.map(o => (
              <option key={o.value} value={o.value}>{o.label}</option>
            ))}
          </select>
          <button
            className="btn btn-sm btn-secondary"
            onClick={() => setSortDesc(v => !v)}
          >
            {sortDesc ? '↓ Desc' : '↑ Asc'}
          </button>
        </div>
      </div>

      {/* ── Main content ── */}
      <div style={{ display: 'grid', gridTemplateColumns: selectedSymbol ? '1fr 320px' : '1fr', gap: 20 }}>
        {/* Table */}
        <div className="card" style={{ padding: 0, overflow: 'hidden' }}>
          {loading ? (
            <div style={{ padding: 40, textAlign: 'center', color: 'var(--text-muted)' }}>
              <div className="spinner" style={{ margin: '0 auto 16px' }} />
              Fetching REIT/InvIT data from markets…
            </div>
          ) : filtered.length === 0 ? (
            <div className="empty-state">
              <div className="icon">🏢</div>
              <p>No instruments match your filters.</p>
            </div>
          ) : (
            <div className="data-table-container">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Symbol</th>
                    <th>Name</th>
                    <th>Type</th>
                    <th>Price ₹</th>
                    <th>Yield</th>
                    <th>1M Ret</th>
                    <th>1Y Ret</th>
                    <th>Volatility</th>
                    <th>Score</th>
                    <th>Confidence</th>
                    <th>Quality</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {filtered.map(inst => (
                    <tr
                      key={inst.symbol}
                      style={{
                        cursor: 'pointer',
                        background: selectedSymbol === inst.symbol ? 'var(--bg-card-hover)' : undefined,
                      }}
                      onClick={() => setSelectedSymbol(selectedSymbol === inst.symbol ? null : inst.symbol)}
                    >
                      <td>
                        <span style={{ fontWeight: 700, fontFamily: 'var(--font-mono)', color: 'var(--accent-primary)' }}>
                          {inst.symbol.replace('.NS', '')}
                        </span>
                      </td>
                      <td style={{ maxWidth: 180 }}>
                        <span style={{ fontSize: '0.82rem' }}>{inst.name}</span>
                      </td>
                      <td>
                        <span style={{
                          fontSize: '0.72rem', padding: '2px 8px', borderRadius: 999, fontWeight: 600,
                          background: inst.asset_class === 'REIT' ? 'rgba(59,130,246,0.15)' : 'rgba(139,92,246,0.15)',
                          color: inst.asset_class === 'REIT' ? 'var(--accent-primary)' : 'var(--accent-secondary)',
                        }}>
                          {inst.asset_class}
                        </span>
                      </td>
                      <td style={{ fontFamily: 'var(--font-mono)' }}>
                        {inst.price ? `₹${inst.price.toFixed(2)}` : '—'}
                      </td>
                      <td style={{ color: 'var(--color-success)', fontWeight: 600 }}>
                        {fmt(inst.yield_pct)}
                      </td>
                      <td><ReturnBadge value={inst.returns_1m} /></td>
                      <td><ReturnBadge value={inst.returns_1y} /></td>
                      <td style={{ color: 'var(--text-secondary)' }}>
                        {inst.volatility_30d !== null ? `${inst.volatility_30d.toFixed(1)}%` : '—'}
                      </td>
                      <td>
                        {inst.conviction_score !== null ? (
                          <span className={`score-badge ${inst.conviction_score >= 70 ? 'score-high' : inst.conviction_score >= 45 ? 'score-medium' : 'score-low'}`}>
                            {inst.conviction_score.toFixed(0)}
                          </span>
                        ) : <span style={{ color: 'var(--text-muted)' }}>—</span>}
                      </td>
                      <td style={{ color: 'var(--text-secondary)', fontSize: '0.8rem' }}>
                        {inst.confidence_score !== null ? `${inst.confidence_score}%` : '—'}
                      </td>
                      <td>
                        <span style={{
                          fontSize: '0.68rem',
                          color: inst.data_quality === 'complete' ? 'var(--color-success)'
                            : inst.data_quality === 'partial' ? 'var(--color-warning)'
                            : 'var(--color-danger)',
                        }}>
                          {inst.data_quality}
                        </span>
                      </td>
                      <td onClick={e => e.stopPropagation()}>
                        <WatchlistButton
                          symbol={inst.symbol}
                          name={inst.name}
                          assetClass={inst.asset_class}
                        />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        {/* Side panel — conviction detail */}
        {selectedInstrument && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            <div className="card">
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 12 }}>
                <div>
                  <div style={{ fontWeight: 700, fontSize: '1rem', color: 'var(--accent-primary)' }}>
                    {selectedInstrument.symbol.replace('.NS', '')}
                  </div>
                  <div style={{ fontSize: '0.78rem', color: 'var(--text-secondary)' }}>
                    {selectedInstrument.name}
                  </div>
                </div>
                <button
                  className="btn btn-sm btn-secondary"
                  onClick={() => setSelectedSymbol(null)}
                >
                  ✕
                </button>
              </div>

              <ConvictionScoreCard
                score={selectedInstrument.conviction_score}
                confidence={selectedInstrument.confidence_score}
                breakdown={selectedInstrument.score_breakdown}
                riskFlags={selectedInstrument.risk_flags}
                dataQuality={selectedInstrument.data_quality}
              />
            </div>

            {/* Key metrics */}
            <div className="card">
              <h4 className="section-title" style={{ marginBottom: 12 }}>Key Metrics</h4>
              {[
                { label: 'Price', value: selectedInstrument.price ? `₹${selectedInstrument.price.toFixed(2)}` : '—' },
                { label: 'Distribution Yield', value: fmt(selectedInstrument.yield_pct) },
                { label: '1M Return', value: fmt(selectedInstrument.returns_1m) },
                { label: '3M Return', value: fmt(selectedInstrument.returns_3m) },
                { label: '1Y Return', value: fmt(selectedInstrument.returns_1y) },
                { label: '30D Volatility', value: fmt(selectedInstrument.volatility_30d) },
                { label: 'Max Drawdown 1Y', value: fmt(selectedInstrument.max_drawdown_1y) },
                { label: 'Sponsor', value: (selectedInstrument.extras?.sponsor as string) ?? '—' },
                { label: 'NAV Premium', value: selectedInstrument.extras?.nav_premium_pct != null ? `${(selectedInstrument.extras.nav_premium_pct as number).toFixed(1)}%` : '—' },
              ].map(row => (
                <div key={row.label} style={{ display: 'flex', justifyContent: 'space-between', padding: '5px 0', borderBottom: '1px solid var(--border-subtle)', fontSize: '0.8rem' }}>
                  <span style={{ color: 'var(--text-muted)' }}>{row.label}</span>
                  <span style={{ fontWeight: 500 }}>{row.value}</span>
                </div>
              ))}
            </div>

            {/* Watchlist action */}
            <div className="card" style={{ textAlign: 'center' }}>
              <WatchlistButton
                symbol={selectedInstrument.symbol}
                name={selectedInstrument.name}
                assetClass={selectedInstrument.asset_class}
                size="md"
              />
              <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginTop: 6 }}>
                Add to Watchlist
              </div>
            </div>
          </div>
        )}
      </div>
    </>
  );
}
