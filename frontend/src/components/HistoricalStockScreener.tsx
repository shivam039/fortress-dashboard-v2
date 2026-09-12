// src/components/HistoricalStockScreener.tsx — FORTRESS-UX1: "what the Stock
// Screener looked like when this scan ran", not a database-record viewer.
// Reuses ScannerResultsView (the same component the live screener uses) so
// the two presentations can never drift apart — only the data source (a
// persisted scan_history_details payload vs. a live scan result) differs.
// Historical integrity: `rows` is rendered exactly as stored — no field is
// recomputed with today's price/score/regime.
'use client';

import React, { useState } from 'react';
import type { ScanHistoryContext, ScanHistoryEntry } from '@/lib/api';
import { describeUniverseCoverage, splitStockResults } from '@/lib/scan-history';
import ScannerResultsView from '@/components/ScannerResultsView';

interface HistoricalStockScreenerProps {
  entry: ScanHistoryEntry;
  rows: Record<string, unknown>[];
  context: ScanHistoryContext | null;
  onBack: () => void;
}

export default function HistoricalStockScreener({ entry, rows, context, onBack }: HistoricalStockScreenerProps) {
  const [showRaw, setShowRaw] = useState(false);
  const { actionable } = splitStockResults(rows);

  return (
    <>
      <div className="card" style={{ marginBottom: '24px', display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 12 }}>
        <div>
          <span className="badge" style={{ marginBottom: 6, display: 'inline-block' }}>🔒 Read-only — Historical Scan</span>
          <h2 className="page-title" style={{ fontSize: '1.3rem', margin: 0 }}>
            Historical Stock Screener — {entry.timestamp}
          </h2>
        </div>
        <button className="btn btn-secondary" onClick={onBack}>← Back to Scan History</button>
      </div>

      {/* ── Scan Summary — user language, not backend field names ────────── */}
      <div className="card" style={{ marginBottom: '24px' }}>
        <h3 className="section-title" style={{ marginTop: 0 }}>Scan Summary</h3>
        <div className="grid-4">
          <div><div className="metric-label">Universe coverage</div><div className="metric-value">{describeUniverseCoverage(entry.universe)}</div></div>
          <div><div className="metric-label">Stocks analysed</div><div className="metric-value">{rows.length}</div></div>
          <div><div className="metric-label">Candidates</div><div className="metric-value">{actionable.length}</div></div>
          <div><div className="metric-label">Status</div><div className="metric-value">✅ Complete</div></div>
        </div>
      </div>

      <div className="card" style={{ marginBottom: '24px' }}>
        <h3 className="section-title" style={{ marginTop: 0 }}>Historical Evidence Context</h3>
        {context?.signals.length ? context.signals.slice(0, 10).map((signal) => (
          <div key={String(signal.id)} style={{ marginBottom: 8 }}>
            <strong>{String(signal.symbol || 'Signal')}</strong> · score {String(signal.score ?? 'not recorded')} · generated {String(signal.generated_at ?? 'not recorded')}
            {(() => { const trade = context.paper_trades.find(t => t.signal_id === signal.id); return <div style={{ color: 'var(--text-muted)' }}>Oracle: {trade?.oracle_decision ?? 'not recorded'}{trade?.oracle_version ? ` (${trade.oracle_version})` : ''} · Paper trade: {trade ? 'linked' : 'none linked'}</div>; })()}
          </div>
        )) : <p style={{ color: 'var(--text-muted)' }}>Historical signal context not recorded for this run.</p>}
      </div>

      {rows.length === 0 ? (
        <div className="empty-state">
          <div className="icon">📭</div>
          <p>No stock rows were stored for this run.</p>
        </div>
      ) : (
        <ScannerResultsView results={rows} mode="historical" />
      )}

      {/* ── Raw data is secondary, never the primary interface ────────────── */}
      <div className="section">
        <div className="expander">
          <div className="expander-header" onClick={() => setShowRaw(!showRaw)}>
            🛠️ Advanced details — raw scan data
            <span>{showRaw ? '▼' : '▶'}</span>
          </div>
          {showRaw && (
            <div className="expander-body">
              <pre style={{ maxHeight: 400, overflow: 'auto', fontSize: '0.75rem' }}>
                {JSON.stringify(rows, null, 2)}
              </pre>
            </div>
          )}
        </div>
      </div>
    </>
  );
}
