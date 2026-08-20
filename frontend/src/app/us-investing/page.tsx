// src/app/us-investing/page.tsx — US Stocks & ETFs investment section
'use client';

import React, { useState, useEffect, useMemo, useCallback, useRef } from 'react';
import { usInvestingApi } from '@/lib/api';
import { useToast } from '@/contexts/ToastContext';
import type { InvestmentInstrument } from '@/lib/types';
import ConvictionScoreCard from '@/components/ConvictionScoreCard';
import DataFreshnessBadge from '@/components/DataFreshnessBadge';
import WatchlistButton from '@/components/WatchlistButton';

const SECTORS = ['All Sectors', 'Technology', 'Financials', 'Healthcare', 'Consumer Disc.', 'Consumer Staples', 'Energy', 'Broad Market', 'Innovation', 'Real Estate', 'Fixed Income', 'Commodities', 'Emerging Markets', 'Small Cap'];
const SORT_OPTIONS = [
  { value: 'conviction_score', label: 'Conviction' },
  { value: 'returns_1y', label: '1Y Return' },
  { value: 'returns_1m', label: '1M Return' },
  { value: 'volatility_30d', label: 'Volatility' },
  { value: 'confidence_score', label: 'Confidence' },
];

function ReturnBadge({ value }: { value: number | null | undefined }) {
  if (value === null || value === undefined) return <span style={{ color: 'var(--text-muted)' }}>—</span>;
  const color = value >= 0 ? 'var(--color-success)' : 'var(--color-danger)';
  return <span style={{ color, fontWeight: 600 }}>{value >= 0 ? '+' : ''}{value.toFixed(1)}%</span>;
}

function fmt(v: number | null | undefined, prefix = '', suffix = '%', decimals = 1): string {
  if (v === null || v === undefined) return '—';
  return `${prefix}${v.toFixed(decimals)}${suffix}`;
}

export default function USInvestingPage() {
  const { success, error } = useToast();
  const [instruments, setInstruments] = useState<InvestmentInstrument[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [assetType, setAssetType] = useState<'all' | 'stock' | 'etf'>('all');
  const [sector, setSector] = useState('All Sectors');
  const [includeInr, setIncludeInr] = useState(true);
  const [sortBy, setSortBy] = useState('conviction_score');
  const [sortDesc, setSortDesc] = useState(true);
  const [search, setSearch] = useState('');
  const [selectedSymbol, setSelectedSymbol] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState<string | null>(null);
  const searchRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const data = await usInvestingApi.list({
        asset_type: assetType === 'all' ? undefined : assetType,
        sector: sector === 'All Sectors' ? undefined : sector,
        include_inr: includeInr,
        sort_by: sortBy,
        desc: sortDesc,
      });
      setInstruments(data);
      if (data.length > 0) setLastUpdated(data[0].last_updated);
    } catch (err: unknown) {
      error(`Failed to load US data: ${(err as Error).message}`);
    } finally {
      setLoading(false);
    }
  }, [assetType, sector, includeInr, sortBy, sortDesc, error]);

  useEffect(() => { loadData(); }, [loadData]);

  const handleRefresh = async () => {
    setRefreshing(true);
    try {
      await usInvestingApi.refresh(true, includeInr);
      success('Refresh started — data updates in ~60 seconds');
      setTimeout(() => loadData(), 60_000);
    } catch (err: unknown) {
      error(`Refresh failed: ${(err as Error).message}`);
    } finally {
      setRefreshing(false);
    }
  };

  // Search filter
  const filtered = useMemo(() => {
    if (!search.trim()) return instruments;
    const q = search.toLowerCase();
    return instruments.filter(i =>
      i.symbol.toLowerCase().includes(q) || i.name.toLowerCase().includes(q)
    );
  }, [instruments, search]);

  const summary = useMemo(() => ({
    count: filtered.length,
    winners: filtered.filter(i => (i.conviction_score ?? 0) >= 60).length,
    avgScore: filtered.filter(i => i.conviction_score !== null).length
      ? filtered.reduce((s, i) => s + (i.conviction_score ?? 0), 0) / filtered.filter(i => i.conviction_score !== null).length
      : 0,
    usdInrRate: instruments.find(i => i.extras?.usd_inr_rate != null)?.extras?.usd_inr_rate ?? null,
  }), [filtered, instruments]);

  const selectedInstrument = instruments.find(i => i.symbol === selectedSymbol) ?? null;
  const extras = selectedInstrument?.extras ?? {};

  return (
    <>
      {/* ── Header ── */}
      <div className="page-header">
        <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', flexWrap: 'wrap', gap: 12 }}>
          <div>
            <h1 className="page-title">🇺🇸 US Investing</h1>
            <p className="page-subtitle">
              US stocks and ETFs with conviction scores, valuation metrics, and real-time INR conversion.
            </p>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
            {summary.usdInrRate && (
              <span style={{ fontSize: '0.78rem', color: 'var(--text-secondary)', background: 'var(--bg-card)', padding: '4px 10px', borderRadius: 999, border: '1px solid var(--border-default)' }}>
                💱 USD/INR: ₹{(summary.usdInrRate as number).toFixed(2)}
              </span>
            )}
            <DataFreshnessBadge isoTimestamp={lastUpdated} />
            <button
              id="us-refresh-btn"
              className="btn btn-secondary btn-sm"
              onClick={handleRefresh}
              disabled={refreshing || loading}
            >
              {refreshing ? '⟳ Refreshing…' : '⟳ Refresh'}
            </button>
          </div>
        </div>
      </div>

      {/* ── Summary cards ── */}
      <div className="metrics-row" style={{ marginBottom: 24 }}>
        {[
          { label: 'Instruments', value: summary.count.toString(), icon: '📈' },
          { label: 'High Conviction (≥60)', value: summary.winners.toString(), icon: '🏆' },
          { label: 'Avg Score', value: isNaN(summary.avgScore) ? '—' : summary.avgScore.toFixed(0), icon: '📊' },
          { label: 'Currency', value: includeInr ? 'USD + INR' : 'USD only', icon: '💱' },
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
            id="us-search"
            className="input"
            placeholder="Search symbol or name…"
            value={search}
            onChange={e => setSearch(e.target.value)}
            style={{ minWidth: 200, flex: 1 }}
          />
          <div style={{ display: 'flex', gap: 6 }}>
            {(['all', 'stock', 'etf'] as const).map(t => (
              <button
                key={t}
                id={`us-filter-${t}`}
                className={`btn btn-sm ${assetType === t ? 'btn-primary' : 'btn-secondary'}`}
                onClick={() => setAssetType(t)}
              >
                {t === 'all' ? 'All' : t === 'etf' ? 'ETFs' : 'Stocks'}
              </button>
            ))}
          </div>
          <select
            id="us-sector-filter"
            className="input"
            value={sector}
            onChange={e => setSector(e.target.value)}
            style={{ minWidth: 160 }}
          >
            {SECTORS.map(s => <option key={s} value={s}>{s}</option>)}
          </select>
          <select
            id="us-sort"
            className="input"
            value={sortBy}
            onChange={e => setSortBy(e.target.value)}
            style={{ minWidth: 150 }}
          >
            {SORT_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
          </select>
          <button className="btn btn-sm btn-secondary" onClick={() => setSortDesc(v => !v)}>
            {sortDesc ? '↓ Desc' : '↑ Asc'}
          </button>
          <label style={{ fontSize: '0.78rem', color: 'var(--text-secondary)', display: 'flex', alignItems: 'center', gap: 6, cursor: 'pointer', userSelect: 'none' }}>
            <input
              type="checkbox"
              checked={includeInr}
              onChange={e => setIncludeInr(e.target.checked)}
            />
            Show INR prices
          </label>
        </div>
      </div>

      {/* ── Main content ── */}
      <div style={{ display: 'grid', gridTemplateColumns: selectedSymbol ? '1fr 340px' : '1fr', gap: 20 }}>
        {/* Table */}
        <div className="card" style={{ padding: 0, overflow: 'hidden' }}>
          {loading ? (
            <div style={{ padding: 40, textAlign: 'center', color: 'var(--text-muted)' }}>
              <div className="spinner" style={{ margin: '0 auto 16px' }} />
              Fetching US market data… (this takes ~30s on first load)
            </div>
          ) : filtered.length === 0 ? (
            <div className="empty-state">
              <div className="icon">🇺🇸</div>
              <p>No instruments match your filters.</p>
            </div>
          ) : (
            <div className="data-table-container">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Symbol</th>
                    <th>Name</th>
                    <th>Sector</th>
                    <th>Price USD</th>
                    {includeInr && <th>Price INR</th>}
                    <th>1M Ret</th>
                    <th>1Y Ret</th>
                    <th>P/E</th>
                    <th>Score</th>
                    <th>Confidence</th>
                    <th>Flags</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {filtered.map(inst => {
                    const exts = inst.extras ?? {};
                    return (
                      <tr
                        key={inst.symbol}
                        style={{
                          cursor: 'pointer',
                          background: selectedSymbol === inst.symbol ? 'var(--bg-card-hover)' : undefined,
                        }}
                        onClick={() => setSelectedSymbol(selectedSymbol === inst.symbol ? null : inst.symbol)}
                      >
                        <td>
                          <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                            <span style={{
                              fontWeight: 700, fontFamily: 'var(--font-mono)',
                              color: 'var(--accent-primary)', fontSize: '0.85rem',
                            }}>
                              {inst.symbol}
                            </span>
                            <span style={{
                              fontSize: '0.65rem', padding: '1px 5px', borderRadius: 3,
                              background: inst.asset_class === 'US_ETF' ? 'rgba(16,185,129,0.15)' : 'rgba(59,130,246,0.15)',
                              color: inst.asset_class === 'US_ETF' ? 'var(--color-success)' : 'var(--accent-primary)',
                            }}>
                              {inst.asset_class === 'US_ETF' ? 'ETF' : 'Stock'}
                            </span>
                          </div>
                        </td>
                        <td style={{ maxWidth: 180, fontSize: '0.8rem' }}>{inst.name}</td>
                        <td style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>{inst.sector}</td>
                        <td style={{ fontFamily: 'var(--font-mono)' }}>
                          {inst.price ? `$${inst.price.toFixed(2)}` : '—'}
                        </td>
                        {includeInr && (
                          <td style={{ fontFamily: 'var(--font-mono)', color: 'var(--text-secondary)', fontSize: '0.78rem' }}>
                            {inst.price_inr ? `₹${inst.price_inr.toFixed(0)}` : '—'}
                          </td>
                        )}
                        <td><ReturnBadge value={inst.returns_1m} /></td>
                        <td><ReturnBadge value={inst.returns_1y} /></td>
                        <td style={{ color: 'var(--text-secondary)', fontSize: '0.8rem' }}>
                          {exts.pe_ratio != null ? (exts.pe_ratio as number).toFixed(1) : '—'}
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
                          {inst.risk_flags.length > 0 ? (
                            <span
                              title={inst.risk_flags.join(', ')}
                              style={{ fontSize: '0.72rem', color: 'var(--color-warning)', cursor: 'help' }}
                            >
                              ⚠ {inst.risk_flags.length}
                            </span>
                          ) : (
                            <span style={{ color: 'var(--color-success)', fontSize: '0.72rem' }}>✓</span>
                          )}
                        </td>
                        <td onClick={e => e.stopPropagation()}>
                          <WatchlistButton
                            symbol={inst.symbol}
                            name={inst.name}
                            assetClass={inst.asset_class}
                          />
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>

        {/* Side panel */}
        {selectedInstrument && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            <div className="card">
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 12 }}>
                <div>
                  <div style={{ fontWeight: 700, fontSize: '1.1rem', color: 'var(--accent-primary)' }}>
                    {selectedInstrument.symbol}
                  </div>
                  <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>
                    {selectedInstrument.name}
                  </div>
                  <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)', marginTop: 2 }}>
                    {selectedInstrument.sector}
                  </div>
                </div>
                <button className="btn btn-sm btn-secondary" onClick={() => setSelectedSymbol(null)}>✕</button>
              </div>

              <ConvictionScoreCard
                score={selectedInstrument.conviction_score}
                confidence={selectedInstrument.confidence_score}
                breakdown={selectedInstrument.score_breakdown}
                riskFlags={selectedInstrument.risk_flags}
                dataQuality={selectedInstrument.data_quality}
              />
            </div>

            {/* Metrics */}
            <div className="card">
              <h4 className="section-title" style={{ marginBottom: 12 }}>Fundamentals</h4>
              {[
                { label: 'Price (USD)', value: selectedInstrument.price ? `$${selectedInstrument.price.toFixed(2)}` : '—' },
                ...(includeInr ? [{ label: 'Price (INR)', value: selectedInstrument.price_inr ? `₹${selectedInstrument.price_inr.toFixed(0)}` : '—' }] : []),
                { label: '1M Return', value: fmt(selectedInstrument.returns_1m) },
                { label: '3M Return', value: fmt(selectedInstrument.returns_3m) },
                { label: '1Y Return', value: fmt(selectedInstrument.returns_1y) },
                { label: '30D Volatility', value: fmt(selectedInstrument.volatility_30d) },
                { label: 'Max Drawdown 1Y', value: fmt(selectedInstrument.max_drawdown_1y) },
                { label: 'P/E Ratio', value: extras.pe_ratio != null ? (extras.pe_ratio as number).toFixed(1) : '—' },
                { label: 'P/B Ratio', value: extras.pb_ratio != null ? (extras.pb_ratio as number).toFixed(2) : '—' },
                { label: 'Dividend Yield', value: extras.dividend_yield != null ? `${((extras.dividend_yield as number) * 100).toFixed(2)}%` : '—' },
                { label: 'Beta', value: extras.beta != null ? (extras.beta as number).toFixed(2) : '—' },
                { label: 'Avg Volume', value: extras.avg_volume != null ? (extras.avg_volume as number).toLocaleString() : '—' },
                ...(selectedInstrument.asset_class === 'US_ETF' ? [
                  { label: 'Expense Ratio', value: extras.expense_ratio != null ? `${((extras.expense_ratio as number) * 100).toFixed(2)}%` : '—' },
                  { label: 'AUM', value: extras.aum_usd != null ? `$${((extras.aum_usd as number) / 1e9).toFixed(1)}B` : '—' },
                ] : [
                  { label: 'Market Cap', value: extras.market_cap_usd != null ? `$${((extras.market_cap_usd as number) / 1e9).toFixed(1)}B` : '—' },
                ]),
              ].map(row => (
                <div key={row.label} style={{ display: 'flex', justifyContent: 'space-between', padding: '5px 0', borderBottom: '1px solid var(--border-subtle)', fontSize: '0.8rem' }}>
                  <span style={{ color: 'var(--text-muted)' }}>{row.label}</span>
                  <span style={{ fontWeight: 500 }}>{row.value}</span>
                </div>
              ))}
            </div>

            {/* Watchlist */}
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
