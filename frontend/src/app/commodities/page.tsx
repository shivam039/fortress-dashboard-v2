// src/app/commodities/page.tsx
'use client';

import React, { useState, useEffect, useCallback, useMemo } from 'react';
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer } from 'recharts';
import { commoditiesApi } from '@/lib/api';
import { useToast } from '@/contexts/ToastContext';
import DataTable from '@/components/DataTable';
import MetricCard from '@/components/MetricCard';

const LABEL_COLOR: Record<string, string> = {
  'STRONG BUY': '#00c853',
  'BUY': '#64dd17',
  'HOLD': '#ffd600',
  'UNDERPERFORMER': '#ff6d00',
  'AVOID': '#d50000',
};

const HEATMAP_ROWS = ['Conviction Score', 'Spread %', '1M Return %', '3M Return %'];
const RETURN_COLS = ['1M Return %', '3M Return %', '6M Return %'];

function num(v: unknown): number | null {
  return typeof v === 'number' && !Number.isNaN(v) ? v : null;
}

function heatColor(value: number, min: number, max: number): string {
  if (max === min) return 'rgba(148,163,184,0.15)';
  const t = Math.max(0, Math.min(1, (value - min) / (max - min)));
  const r = t < 0.5 ? 255 : Math.round(255 - (t - 0.5) * 2 * 255);
  const g = t < 0.5 ? Math.round(t * 2 * 255) : 255;
  return `rgba(${r}, ${g}, 40, 0.55)`;
}

function DecisionCard({ row }: { row: Record<string, unknown> }) {
  const label = String(row['Conviction Label'] || 'HOLD');
  const emoji = String(row['Conviction Emoji'] || '🟡');
  const score = num(row['Conviction Score']) ?? 50;
  const color = LABEL_COLOR[label] || '#ffd600';
  const decision = String(row['Decision'] || '');
  const price = num(row['Price (₹)']);
  const trend = String(row['Trend'] || '—');
  const oneMonth = num(row['1M Return %']);
  const atrRegime = String(row['ATR Regime'] || '—');
  const spread = num(row['Spread %']);

  return (
    <div
      className="card"
      style={{ borderLeft: `4px solid ${color}`, marginBottom: 12 }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 8 }}>
        <h3 style={{ margin: 0, fontSize: '1.05rem' }}>{emoji} {String(row['Commodity'] || '—')}</h3>
        <span style={{ background: color, color: '#000', fontWeight: 700, padding: '4px 12px', borderRadius: 20, fontSize: '0.85rem' }}>
          {label} · {score}/100
        </span>
      </div>
      {decision && (
        <p style={{ margin: '8px 0', color: 'var(--text-secondary)', fontSize: '0.85rem' }}>{decision}</p>
      )}
      <div style={{ display: 'flex', gap: 20, flexWrap: 'wrap', marginTop: 8, fontSize: '0.8rem' }}>
        <div><span style={{ color: 'var(--text-muted)' }}>Price</span><br /><b>₹{price !== null ? price.toLocaleString('en-IN', { maximumFractionDigits: 2 }) : '—'}</b></div>
        <div><span style={{ color: 'var(--text-muted)' }}>Trend</span><br /><b>{trend}</b></div>
        <div><span style={{ color: 'var(--text-muted)' }}>1M Return</span><br /><b>{oneMonth !== null ? `${oneMonth >= 0 ? '+' : ''}${oneMonth.toFixed(2)}%` : '—'}</b></div>
        <div><span style={{ color: 'var(--text-muted)' }}>ATR Regime</span><br /><b>{atrRegime}</b></div>
        <div><span style={{ color: 'var(--text-muted)' }}>Spread</span><br /><b>{spread !== null ? `${spread >= 0 ? '+' : ''}${spread.toFixed(2)}%` : '—'}</b></div>
      </div>
    </div>
  );
}

export default function CommoditiesPage() {
  const { error } = useToast();
  const [data, setData] = useState<Record<string, unknown>[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);

  const loadData = useCallback((forceRefresh = false) => {
    (forceRefresh ? setRefreshing : setLoading)(true);
    setLoadError(null);
    commoditiesApi.list(forceRefresh)
      .then(setData)
      .catch((err: unknown) => {
        const message = (err as Error).message || 'Unknown error';
        setLoadError(message);
        error(`Failed to load commodities data: ${message}`);
      })
      .finally(() => {
        setLoading(false);
        setRefreshing(false);
      });
  }, [error]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    loadData(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const stats = useMemo(() => {
    if (!data.length) return { count: 0, avgConviction: 0, buys: 0 };
    const scores = data
      .map(r => r['Conviction Score'])
      .filter((v): v is number => typeof v === 'number');
    const buys = data.filter(r => {
      const label = String(r['Conviction Label'] || '');
      return label === 'STRONG BUY' || label === 'BUY';
    }).length;
    return {
      count: data.length,
      avgConviction: scores.length ? scores.reduce((s, v) => s + v, 0) / scores.length : 0,
      buys,
    };
  }, [data]);

  const returnChartData = useMemo(() => {
    return data.map(row => {
      const entry: Record<string, string | number> = { Commodity: String(row['Commodity'] || '—') };
      RETURN_COLS.forEach(col => {
        const v = num(row[col]);
        if (v !== null) entry[col] = v;
      });
      return entry;
    });
  }, [data]);

  const heatmapRanges = useMemo(() => {
    const ranges: Record<string, { min: number; max: number }> = {};
    HEATMAP_ROWS.forEach(metric => {
      const values = data.map(r => num(r[metric])).filter((v): v is number => v !== null);
      if (values.length) {
        ranges[metric] = { min: Math.min(...values), max: Math.max(...values) };
      }
    });
    return ranges;
  }, [data]);

  return (
    <>
      <div className="page-header">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: 12 }}>
          <div>
            <h1 className="page-title">🌍 Commodities</h1>
            <p className="page-subtitle">Track global commodity trends and generate trade alerts.</p>
          </div>
          <button
            className="btn btn-secondary"
            onClick={() => loadData(true)}
            disabled={loading || refreshing}
          >
            {refreshing ? 'Refreshing…' : '🔄 Refresh'}
          </button>
        </div>
      </div>

      {!loading && data.length > 0 && (
        <div className="grid-3" style={{ marginBottom: 20 }}>
          <MetricCard label="Commodities Tracked" value={stats.count} />
          <MetricCard label="Avg Conviction" value={stats.avgConviction.toFixed(0)} />
          <MetricCard label="Buy-Rated" value={stats.buys} deltaType="positive" />
        </div>
      )}

      <div className="section">
        {loading ? (
          <div className="loading-overlay">Loading commodities data...</div>
        ) : loadError ? (
          <div className="empty-state">
            <div className="icon">⚠️</div>
            <p>Couldn&apos;t load commodities data: {loadError}</p>
            <button className="btn btn-secondary" style={{ marginTop: 12 }} onClick={() => loadData(false)}>
              Retry
            </button>
          </div>
        ) : data.length === 0 ? (
          <DataTable data={data} emptyMessage="No commodity data available." />
        ) : (
          <>
            <h3 className="section-title">🎯 Decision Cards</h3>
            {data.map((row, i) => <DecisionCard key={String(row['Commodity']) || i} row={row} />)}

            <h3 className="section-title" style={{ marginTop: 24 }}>📈 Return Comparison</h3>
            <div className="card" style={{ marginBottom: 24 }}>
              <div style={{ width: '100%', height: 320 }}>
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={returnChartData} margin={{ top: 10, right: 20, bottom: 10, left: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="var(--border-default)" />
                    <XAxis dataKey="Commodity" stroke="var(--text-muted)" />
                    <YAxis stroke="var(--text-muted)" />
                    <Tooltip
                      contentStyle={{ backgroundColor: 'var(--bg-card)', borderColor: 'var(--border-default)', borderRadius: 'var(--radius-md)', color: 'var(--text-primary)' }}
                    />
                    <Legend />
                    <Bar dataKey="1M Return %" fill="#00c853" />
                    <Bar dataKey="3M Return %" fill="#2979ff" />
                    <Bar dataKey="6M Return %" fill="#aa00ff" />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </div>

            <h3 className="section-title">🔥 Conviction &amp; Spread Heatmap</h3>
            <div className="card" style={{ marginBottom: 24, overflowX: 'auto' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', minWidth: 480 }}>
                <thead>
                  <tr>
                    <th style={{ textAlign: 'left', padding: 8, fontSize: '0.78rem', color: 'var(--text-muted)' }}>Metric</th>
                    {data.map(row => (
                      <th key={String(row['Commodity'])} style={{ padding: 8, fontSize: '0.78rem', color: 'var(--text-muted)' }}>{String(row['Commodity'])}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {HEATMAP_ROWS.filter(metric => heatmapRanges[metric]).map(metric => (
                    <tr key={metric}>
                      <td style={{ padding: 8, fontSize: '0.8rem', color: 'var(--text-secondary)' }}>{metric}</td>
                      {data.map(row => {
                        const v = num(row[metric]);
                        const range = heatmapRanges[metric];
                        return (
                          <td
                            key={String(row['Commodity']) + metric}
                            style={{
                              padding: 8,
                              textAlign: 'center',
                              fontSize: '0.82rem',
                              fontWeight: 600,
                              background: v !== null ? heatColor(v, range.min, range.max) : 'transparent',
                              borderRadius: 4,
                            }}
                          >
                            {v !== null ? v.toFixed(2) : '—'}
                          </td>
                        );
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <h3 className="section-title">📋 Full Data Table</h3>
            <DataTable data={data} emptyMessage="No commodity data available." />
          </>
        )}
      </div>
    </>
  );
}
