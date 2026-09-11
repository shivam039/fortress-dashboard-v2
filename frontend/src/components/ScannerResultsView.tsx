// src/components/ScannerResultsView.tsx — FORTRESS-UX1: the Stock Screener's
// results presentation (metrics, momentum/long-term picks, full results,
// filtered-out), extracted so the live screener and the read-only
// Historical Stock Screener render results identically instead of the
// historical view forking its own copy. `mode` exists only for callers that
// want to react to it later (e.g. analytics) — the JSX itself never
// branches on it, which is what keeps the two views from drifting.
'use client';

import React from 'react';
import DataTable from '@/components/DataTable';
import MetricCard from '@/components/MetricCard';
import { splitStockResults } from '@/lib/scan-history';

interface ScannerResultsViewProps {
  results: Record<string, unknown>[];
  mode: 'live' | 'historical';
}

const PICK_COLUMNS = ['Symbol', 'Company', 'Price', 'Score', 'Strategy', 'Velocity', 'Target_10D', 'Stop_Loss', 'Position_Qty'];

export default function ScannerResultsView({ results }: ScannerResultsViewProps) {
  const { actionable, filtered, momentum, longTerm } = splitStockResults(results);

  if (results.length === 0) return null;

  return (
    <>
      <div className="grid-4" style={{ marginBottom: '24px' }}>
        <MetricCard label="Total Results" value={results.length} />
        <MetricCard label="Actionable" value={actionable.length} deltaType="positive" />
        <MetricCard label="Momentum Picks" value={momentum.length} />
        <MetricCard label="Long-Term Picks" value={longTerm.length} />
      </div>

      {momentum.length > 0 && (
        <div className="section">
          <h3 className="section-title">🚀 Momentum Picks ({momentum.length})</h3>
          <DataTable data={momentum} columns={PICK_COLUMNS} />
        </div>
      )}

      {longTerm.length > 0 && (
        <div className="section">
          <h3 className="section-title">💎 Long-Term Picks ({longTerm.length})</h3>
          <DataTable data={longTerm} columns={PICK_COLUMNS} />
        </div>
      )}

      <div className="section">
        <h3 className="section-title">📋 All Scan Results</h3>
        <DataTable data={results} />
      </div>

      {filtered.length > 0 && (
        <div className="section">
          <div className="expander">
            <div className="expander-header">
              Filtered Out ({filtered.length}) — Hard Quality Gates
            </div>
            <div className="expander-body">
              <DataTable data={filtered} />
            </div>
          </div>
        </div>
      )}
    </>
  );
}
