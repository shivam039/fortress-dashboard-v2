// src/components/HistoricalGenericScan.tsx — FORTRESS-UX1: read-only
// historical detail for sections without a dedicated live-scanner
// presentation to mirror (e.g. Mutual Funds, Commodities, Options — see
// docs/FORTRESS_UX1_SCAN_HISTORY.md "Limitations"). Still section-specific,
// still read-only, still keeps the raw table behind a collapsed section
// rather than making it the primary view.
'use client';

import React, { useState } from 'react';
import type { ScanHistoryEntry } from '@/lib/api';
import { describeUniverseCoverage, sectionMeta } from '@/lib/scan-history';
import DataTable from '@/components/DataTable';

interface HistoricalGenericScanProps {
  entry: ScanHistoryEntry;
  rows: Record<string, unknown>[];
  onBack: () => void;
}

export default function HistoricalGenericScan({ entry, rows, onBack }: HistoricalGenericScanProps) {
  const [expanded, setExpanded] = useState(true);
  const meta = sectionMeta(entry.scan_type);

  return (
    <>
      <div className="card" style={{ marginBottom: '24px', display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 12 }}>
        <div>
          <span className="badge" style={{ marginBottom: 6, display: 'inline-block' }}>🔒 Read-only — Historical Scan</span>
          <h2 className="page-title" style={{ fontSize: '1.3rem', margin: 0 }}>
            {meta.icon} Historical {meta.label} Scan — {entry.timestamp}
          </h2>
        </div>
        <button className="btn btn-secondary" onClick={onBack}>← Back to Scan History</button>
      </div>

      <div className="card" style={{ marginBottom: '24px' }}>
        <div className="grid-4">
          <div><div className="metric-label">Coverage</div><div className="metric-value">{describeUniverseCoverage(entry.universe)}</div></div>
          <div><div className="metric-label">Items analysed</div><div className="metric-value">{rows.length}</div></div>
          <div><div className="metric-label">Status</div><div className="metric-value">✅ Complete</div></div>
        </div>
      </div>

      <div className="section">
        <div className="expander">
          <div className="expander-header" onClick={() => setExpanded(!expanded)}>
            Scan details
            <span>{expanded ? '▼' : '▶'}</span>
          </div>
          {expanded && (
            rows.length === 0
              ? <div className="expander-body"><p>No rows were stored for this run.</p></div>
              : <div className="expander-body"><DataTable data={rows} /></div>
          )}
        </div>
      </div>
    </>
  );
}
