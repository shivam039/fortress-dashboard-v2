// src/app/mf-lab/page.tsx
'use client';

import React, { useState, useEffect, useMemo } from 'react';
import { mfApi } from '@/lib/api';
import { useToast } from '@/contexts/ToastContext';
import DataTable from '@/components/DataTable';
import ConvictionScoreCard from '@/components/ConvictionScoreCard';
import DataFreshnessBadge from '@/components/DataFreshnessBadge';

export default function MfLabPage() {
  const { success, error } = useToast();
  const [data, setData] = useState<Record<string, unknown>[]>([]);
  const [loading, setLoading] = useState(true);
  const [jobType, setJobType] = useState('refresh_nav');
  const [forceRefresh, setForceRefresh] = useState(false);
  const [schemeCodes, setSchemeCodes] = useState('');
  const [triggerLoading, setTriggerLoading] = useState(false);
  const [selectedIdx, setSelectedIdx] = useState<number | null>(null);
  const [viewMode, setViewMode] = useState<'table' | 'scores'>('table');

  useEffect(() => {
    mfApi.getAnalysis()
      .then(setData)
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  const handleTrigger = async () => {
    setTriggerLoading(true);
    try {
      const payload = {
        job_type: jobType,
        force_refresh: forceRefresh,
        scheme_codes: schemeCodes.split(',').map(s => s.trim()).filter(Boolean),
      };
      const res = await mfApi.triggerJob(payload);
      success(`Job queued: ${res.message}`);
    } catch (err: unknown) {
      error(`Failed: ${(err as Error).message}`);
    } finally {
      setTriggerLoading(false);
    }
  };

  const stats = useMemo(() => {
    if (!data.length) return { count: 0, avg: 0, highConviction: 0, stale: 0 };
    const scored = data.filter(r => r.conviction_score_v2 != null);
    return {
      count: data.length,
      avg: scored.length ? scored.reduce((s, r) => s + (r.conviction_score_v2 as number), 0) / scored.length : 0,
      highConviction: scored.filter(r => (r.conviction_score_v2 as number) >= 65).length,
      stale: data.filter(r => r.data_quality === 'stale').length,
    };
  }, [data]);

  const selectedFund = selectedIdx !== null ? data[selectedIdx] : null;
  const lastUpdated = data.length > 0 && data[0].last_updated ? data[0].last_updated as string : null;

  return (
    <>
      <div className="page-header">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: 12 }}>
          <div>
            <h1 className="page-title">📈 Mutual Fund Lab</h1>
            <p className="page-subtitle">Analyze MF performance, alpha/beta, and track scheme NAVs.</p>
          </div>
          {lastUpdated && <DataFreshnessBadge isoTimestamp={lastUpdated} />}
        </div>
      </div>

      {!loading && data.length > 0 && (
        <div className="metrics-row" style={{ marginBottom: 20 }}>
          {[
            { label: 'Funds Analyzed', value: stats.count.toString(), icon: '📈', warn: false },
            { label: 'Avg Conviction', value: stats.avg > 0 ? stats.avg.toFixed(0) : '—', icon: '📊', warn: false },
            { label: 'High Conviction (≥65)', value: stats.highConviction.toString(), icon: '🏆', warn: false },
            { label: 'Stale Data', value: stats.stale.toString(), icon: '⚠', warn: stats.stale > 0 },
          ].map(m => (
            <div key={m.label} className="metric-card">
              <span className="metric-label">{m.icon} {m.label}</span>
              <span className="metric-value" style={m.warn ? { color: 'var(--color-warning)' } : undefined}>
                {m.value}
              </span>
            </div>
          ))}
        </div>
      )}

      <div className="grid-2" style={{ marginBottom: '24px' }}>
        {/* Existing job controls — UNCHANGED */}
        <div className="card">
          <h3 className="section-title">Job Controls</h3>
          <div className="input-group" style={{ marginBottom: '12px' }}>
            <label>Job Type</label>
            <select className="input" value={jobType} onChange={e => setJobType(e.target.value)}>
              <option value="refresh_nav">Daily NAV Sync</option>
              <option value="full_refresh">Full Recalculation</option>
              <option value="recalculate_rankings">Scheme Discovery</option>
              <option value="update_metrics">Update Metrics</option>
            </select>
          </div>
          <div className="input-group" style={{ marginBottom: '12px' }}>
            <label>
              <input type="checkbox" checked={forceRefresh} onChange={e => setForceRefresh(e.target.checked)} style={{ marginRight: 6 }} />
              Force Refresh
            </label>
          </div>
          <div className="input-group" style={{ marginBottom: '16px' }}>
            <label>Scheme Codes (optional)</label>
            <input className="input" placeholder="e.g. 120503, 120716" value={schemeCodes} onChange={e => setSchemeCodes(e.target.value)} />
          </div>
          <button className="btn btn-primary btn-block" onClick={handleTrigger} disabled={triggerLoading}>
            {triggerLoading ? 'Triggering...' : '🚀 Trigger Job'}
          </button>
        </div>

        {/* New conviction detail panel — additive */}
        <div className="card">
          <h3 className="section-title">📊 Conviction Detail</h3>
          {selectedFund ? (
            <>
              <div style={{ marginBottom: 12, fontSize: '0.85rem', fontWeight: 600, color: 'var(--text-primary)' }}>
                {String(selectedFund['Scheme'] || selectedFund['scheme_name'] || 'Selected Fund')}
              </div>
              <ConvictionScoreCard
                score={selectedFund.conviction_score_v2 as number | null}
                confidence={selectedFund.confidence_score as number | null}
                breakdown={(selectedFund.score_breakdown as Record<string, number>) || null}
                riskFlags={(selectedFund.risk_flags_v2 as string[]) || []}
                dataQuality={(selectedFund.data_quality as string) || 'partial'}
              />
            </>
          ) : (
            <div style={{ color: 'var(--text-muted)', fontSize: '0.82rem', textAlign: 'center', padding: '20px 0' }}>
              Click a fund row in the table below to see its conviction breakdown.
            </div>
          )}
        </div>
      </div>

      <div className="section">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12, flexWrap: 'wrap', gap: 8 }}>
          <h3 className="section-title" style={{ margin: 0 }}>Fund Analysis</h3>
          <div style={{ display: 'flex', gap: 6 }}>
            <button
              id="mf-view-table"
              className={`btn btn-sm ${viewMode === 'table' ? 'btn-primary' : 'btn-secondary'}`}
              onClick={() => setViewMode('table')}
            >
              Full Table
            </button>
            <button
              id="mf-view-scores"
              className={`btn btn-sm ${viewMode === 'scores' ? 'btn-primary' : 'btn-secondary'}`}
              onClick={() => setViewMode('scores')}
            >
              Conviction Grid
            </button>
          </div>
        </div>

        {loading ? (
          <div className="loading-overlay">Loading data...</div>
        ) : viewMode === 'table' ? (
          <div onClick={e => {
            const tr = (e.target as HTMLElement).closest('tr');
            if (!tr) return;
            const tbody = tr.parentElement;
            if (!tbody || tbody.tagName !== 'TBODY') return;
            const idx = Array.from(tbody.children).indexOf(tr);
            setSelectedIdx(prev => prev === idx ? null : idx);
          }}>
            <DataTable data={data} emptyMessage="No fund data available." />
          </div>
        ) : (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))', gap: 12 }}>
            {data.slice(0, 24).map((fund, idx) => {
              const score = fund.conviction_score_v2 as number | null;
              const name = String(fund['Scheme'] || fund['scheme_name'] || `Fund ${idx + 1}`);
              return (
                <div
                  key={idx}
                  className="card"
                  style={{ cursor: 'pointer', border: selectedIdx === idx ? '1px solid var(--accent-primary)' : undefined }}
                  onClick={() => setSelectedIdx(prev => prev === idx ? null : idx)}
                >
                  <div style={{ marginBottom: 10 }}>
                    <div style={{ fontSize: '0.78rem', fontWeight: 600, color: 'var(--text-primary)', lineHeight: 1.3, maxHeight: '2.6em', overflow: 'hidden' }}>
                      {name.length > 55 ? name.slice(0, 55) + '…' : name}
                    </div>
                    <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)', marginTop: 2 }}>
                      {String(fund['Category'] || fund['category'] || '')}
                    </div>
                  </div>
                  <ConvictionScoreCard
                    score={score}
                    confidence={fund.confidence_score as number | null}
                    breakdown={(fund.score_breakdown as Record<string, number>) || null}
                    riskFlags={(fund.risk_flags_v2 as string[]) || []}
                    dataQuality={(fund.data_quality as string) || 'partial'}
                    compact
                  />
                </div>
              );
            })}
            {data.length > 24 && (
              <div style={{ textAlign: 'center', color: 'var(--text-muted)', padding: 20, gridColumn: '1/-1', fontSize: '0.82rem' }}>
                Showing top 24. Switch to Full Table view to see all {data.length} funds.
              </div>
            )}
          </div>
        )}
      </div>
    </>
  );
}
