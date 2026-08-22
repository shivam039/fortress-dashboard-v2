// src/app/mf-lab/page.tsx
'use client';

import React, { useState, useEffect, useMemo } from 'react';
import { mfApi } from '@/lib/api';
import { useToast } from '@/contexts/ToastContext';
import DataTable from '@/components/DataTable';
import ConvictionScoreCard from '@/components/ConvictionScoreCard';
import DataFreshnessBadge from '@/components/DataFreshnessBadge';

// Curated column set for the Fund Analysis table — see the `tableData`
// comment below for why this exists instead of letting DataTable render
// every raw field.
const MF_TABLE_COLUMNS = [
  'Scheme',
  'Category',
  'Sub Category',
  'Conviction Score',
  'Conviction Label',
  'Confidence',
  'Data Quality',
  'NAV',
  '1Y Return',
  '3Y Return',
  '5Y Return',
  'Sharpe',
  'Sortino',
  'Alpha',
  'Volatility',
  'Downside Deviation',
];

export default function MfLabPage() {
  const { success, error } = useToast();
  const [data, setData] = useState<Record<string, unknown>[]>([]);
  const [loading, setLoading] = useState(true);
  const [jobType, setJobType] = useState('refresh_nav');
  const [forceRefresh, setForceRefresh] = useState(false);
  const [schemeCodes, setSchemeCodes] = useState('');
  const [triggerLoading, setTriggerLoading] = useState(false);
  // Identifies the selected fund by its unique Scheme Code rather than a
  // positional index. The table below sorts itself internally (click a
  // column header), so a row's on-screen position stops matching its index
  // in `filteredData`/`tableData` the moment a sort is applied — a
  // position-based "selected row" would then resolve to a different fund
  // than the one actually clicked. A stable key doesn't have that problem.
  const [selectedSchemeCode, setSelectedSchemeCode] = useState<string | null>(null);
  const [viewMode, setViewMode] = useState<'table' | 'scores'>('table');
  // The backend already classifies every fund into a Category (Equity/Debt/
  // Hybrid) and a more granular Sub Category (~9 buckets, e.g. Small Cap,
  // Liquid, Balanced Advantage) — see mf_lab/logic.py's classify_category().
  // It just wasn't surfaced anywhere beyond a buried column in the full
  // table. Adding more categories wouldn't make this easier to read; a way
  // to actually filter by the categories that already exist does.
  const [categoryFilter, setCategoryFilter] = useState<string>('All');
  // Sub Category is the finer breakdown (Large Cap, Mid Cap, Small Cap,
  // Flexi Cap, Multi Cap, ELSS, Liquid, Balanced Advantage, Aggressive/
  // Conservative/Balanced Hybrid, Multi Asset, Equity Savings, etc. — see
  // classify_category() in mf_lab/logic.py). It's scoped to whatever
  // Category is currently selected, since e.g. "Large Cap" only makes sense
  // once you're already looking at Equity funds.
  const [subCategoryFilter, setSubCategoryFilter] = useState<string>('All');

  useEffect(() => {
    mfApi.getAnalysis()
      .then(setData)
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  const categoryOf = (fund: Record<string, unknown>): string =>
    String(fund['Category'] || fund['category'] || 'Uncategorized');
  const subCategoryOf = (fund: Record<string, unknown>): string =>
    String(fund['Sub Category'] || fund['sub_category'] || 'Uncategorized');
  const schemeCodeOf = (fund: Record<string, unknown>, idx: number): string =>
    String(fund['Scheme Code'] || fund['scheme_code'] || `idx-${idx}`);

  const categoryCounts = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const fund of data) {
      const cat = categoryOf(fund);
      counts[cat] = (counts[cat] || 0) + 1;
    }
    return counts;
  }, [data]);

  const categoryTabs = useMemo(
    () => ['All', ...Object.keys(categoryCounts).sort()],
    [categoryCounts]
  );

  // Funds filtered by Category only — this is the base for both the Sub
  // Category chip list and its counts, so switching Category always shows
  // the sub-categories that actually exist within it.
  const categoryFilteredData = useMemo(
    () => (categoryFilter === 'All' ? data : data.filter(f => categoryOf(f) === categoryFilter)),
    [data, categoryFilter]
  );

  const subCategoryCounts = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const fund of categoryFilteredData) {
      const sub = subCategoryOf(fund);
      counts[sub] = (counts[sub] || 0) + 1;
    }
    return counts;
  }, [categoryFilteredData]);

  const subCategoryTabs = useMemo(
    () => ['All', ...Object.keys(subCategoryCounts).sort()],
    [subCategoryCounts]
  );

  const filteredData = useMemo(
    () =>
      subCategoryFilter === 'All'
        ? categoryFilteredData
        : categoryFilteredData.filter(f => subCategoryOf(f) === subCategoryFilter),
    [categoryFilteredData, subCategoryFilter]
  );

  // Clear the selection when a filter changes, since the previously
  // selected fund may no longer be in view.
  useEffect(() => {
    setSelectedSchemeCode(null);
  }, [categoryFilter, subCategoryFilter]);

  // Sub Category options change whenever Category changes — drop back to
  // "All" rather than risk pointing at a sub-category that doesn't exist
  // under the newly selected Category.
  useEffect(() => {
    setSubCategoryFilter('All');
  }, [categoryFilter]);

  // Curated columns for the full table: the raw record has 25+ fields
  // (including a couple of JSON blobs like score_breakdown / risk_flags_v2
  // that render as unreadable stringified JSON in a generic table), and
  // whichever conviction score was requested ("table should show conviction
  // scores column as well") was getting buried at the far right since it's
  // one of the last keys added to each record. This mapping surfaces the v2
  // conviction score (the one the rest of this page — cards, stats — already
  // uses) under a plain "Conviction Score" label near the front instead.
  const tableData = useMemo(
    () =>
      filteredData.map(f => ({
        ...f,
        'Conviction Score': (f.conviction_score_v2 as number | null) ?? f['Conviction Score'] ?? null,
        Confidence: f.confidence_score ?? null,
        'Data Quality': f.data_quality ?? null,
      })),
    [filteredData]
  );

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
    if (!filteredData.length) return { count: 0, avg: 0, highConviction: 0, stale: 0 };
    const scored = filteredData.filter(r => r.conviction_score_v2 != null);
    return {
      count: filteredData.length,
      avg: scored.length ? scored.reduce((s, r) => s + (r.conviction_score_v2 as number), 0) / scored.length : 0,
      highConviction: scored.filter(r => (r.conviction_score_v2 as number) >= 65).length,
      stale: filteredData.filter(r => r.data_quality === 'stale').length,
    };
  }, [filteredData]);

  const selectedFund =
    selectedSchemeCode !== null
      ? filteredData.find((f, idx) => schemeCodeOf(f, idx) === selectedSchemeCode) ?? null
      : null;
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

        {/* Category filter — the backend already classifies every fund as
            Equity/Debt/Hybrid (with a finer Sub Category underneath); this
            just makes that classification usable instead of a buried
            column in the full table. */}
        {!loading && data.length > 0 && (
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 8 }}>
            {categoryTabs.map(cat => (
              <button
                key={cat}
                className={`btn btn-sm ${categoryFilter === cat ? 'btn-primary' : 'btn-secondary'}`}
                onClick={() => setCategoryFilter(cat)}
              >
                {cat} {cat === 'All' ? `(${data.length})` : `(${categoryCounts[cat] ?? 0})`}
              </button>
            ))}
          </div>
        )}

        {/* Sub Category filter — Large Cap / Mid Cap / Small Cap / Flexi /
            ELSS / Liquid / Balanced Advantage etc, scoped to whichever
            Category tab is active above. */}
        {!loading && categoryFilteredData.length > 0 && subCategoryTabs.length > 2 && (
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 14 }}>
            {subCategoryTabs.map(sub => (
              <button
                key={sub}
                className={`btn btn-sm ${subCategoryFilter === sub ? 'btn-primary' : 'btn-secondary'}`}
                style={{ fontSize: '0.72rem', padding: '4px 10px', opacity: 0.9 }}
                onClick={() => setSubCategoryFilter(sub)}
              >
                {sub} {sub === 'All' ? `(${categoryFilteredData.length})` : `(${subCategoryCounts[sub] ?? 0})`}
              </button>
            ))}
          </div>
        )}

        {loading ? (
          <div className="loading-overlay">Loading data...</div>
        ) : viewMode === 'table' ? (
          <DataTable
            data={tableData}
            columns={MF_TABLE_COLUMNS}
            emptyMessage="No fund data available."
            rowKey={schemeCodeOf}
            selectedRowKey={selectedSchemeCode}
            onRowClick={(row, idx) => {
              const code = schemeCodeOf(row, idx);
              setSelectedSchemeCode(prev => (prev === code ? null : code));
            }}
          />
        ) : (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))', gap: 12 }}>
            {filteredData.slice(0, 24).map((fund, idx) => {
              const score = fund.conviction_score_v2 as number | null;
              const name = String(fund['Scheme'] || fund['scheme_name'] || `Fund ${idx + 1}`);
              const code = schemeCodeOf(fund, idx);
              const isSelected = selectedSchemeCode === code;
              return (
                <div
                  key={code}
                  className="card"
                  style={{ cursor: 'pointer', border: isSelected ? '1px solid var(--accent-primary)' : undefined }}
                  onClick={() => setSelectedSchemeCode(prev => (prev === code ? null : code))}
                >
                  <div style={{ marginBottom: 10 }}>
                    <div style={{ fontSize: '0.78rem', fontWeight: 600, color: 'var(--text-primary)', lineHeight: 1.3, maxHeight: '2.6em', overflow: 'hidden' }}>
                      {name.length > 55 ? name.slice(0, 55) + '…' : name}
                    </div>
                    <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)', marginTop: 2 }}>
                      {String(fund['Category'] || fund['category'] || '')}
                      {fund['Sub Category'] ? ` · ${String(fund['Sub Category'])}` : ''}
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
            {filteredData.length > 24 && (
              <div style={{ textAlign: 'center', color: 'var(--text-muted)', padding: 20, gridColumn: '1/-1', fontSize: '0.82rem' }}>
                Showing top 24. Switch to Full Table view to see all {filteredData.length} funds.
              </div>
            )}
          </div>
        )}
      </div>
    </>
  );
}
