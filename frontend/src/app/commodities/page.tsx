// src/app/commodities/page.tsx
'use client';

import React, { useState, useEffect, useCallback, useMemo } from 'react';
import { commoditiesApi } from '@/lib/api';
import { useToast } from '@/contexts/ToastContext';
import DataTable from '@/components/DataTable';
import MetricCard from '@/components/MetricCard';

export default function CommoditiesPage() {
  const { error } = useToast();
  const [data, setData] = useState<Record<string, unknown>[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  // Distinguishes "the fetch actually failed" from a genuinely empty
  // result — a plain `.catch(() => {})` here previously discarded any
  // error silently, so a live yfinance failure looked identical to
  // "no commodity data available," with no way to tell the two apart or
  // retry without a full page reload.
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
        ) : (
          <DataTable data={data} emptyMessage="No commodity data available." />
        )}
      </div>
    </>
  );
}
