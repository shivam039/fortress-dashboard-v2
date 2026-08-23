// src/app/history/page.tsx
'use client';

import React, { useState, useEffect, useCallback } from 'react';
import { historyApi, type ScanHistoryEntry } from '@/lib/api';
import DataTable from '@/components/DataTable';

const SECTION_LABELS: Record<string, string> = {
  STOCK: '📈 Stock Screener',
  MF: '🪙 Mutual Funds',
  COMMODITY: '🌍 Commodities',
  OPTIONS: '🧮 Options',
};

function sectionLabel(scanType: string): string {
  return SECTION_LABELS[scanType] || `📄 ${scanType}`;
}

function entryLabel(entry: ScanHistoryEntry): string {
  return `${sectionLabel(entry.scan_type)} · ${entry.universe} · ${entry.timestamp}`;
}

export default function HistoryPage() {
  const [entries, setEntries] = useState<ScanHistoryEntry[]>([]);
  const [selectedScanId, setSelectedScanId] = useState<number | null>(null);
  const [historyData, setHistoryData] = useState<Record<string, unknown>[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadingData, setLoadingData] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);

  const loadEntries = useCallback(() => {
    setLoading(true);
    setLoadError(null);
    historyApi.timestamps()
      .then(list => {
        setEntries(list);
        if (list.length > 0) setSelectedScanId(list[0].scan_id);
      })
      .catch((err: unknown) => {
        setLoadError((err as Error).message || 'Unknown error');
      })
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    loadEntries();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (selectedScanId === null) return;
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setLoadingData(true);
    historyApi.data(selectedScanId)
      .then(setHistoryData)
      .catch(() => setHistoryData([]))
      .finally(() => setLoadingData(false));
  }, [selectedScanId]);

  return (
    <>
      <div className="page-header">
        <h1 className="page-title">🕐 Scan History</h1>
        <p className="page-subtitle">View results from past scans across every section — stock screener, mutual funds, commodities, and options.</p>
      </div>

      <div className="card" style={{ marginBottom: '24px' }}>
        <div className="input-group" style={{ maxWidth: '520px' }}>
          <label>Select Scan (section · universe · time)</label>
          <select
            className="input"
            value={selectedScanId ?? ''}
            onChange={e => setSelectedScanId(e.target.value ? Number(e.target.value) : null)}
            disabled={loading || entries.length === 0}
          >
            {entries.length === 0 && <option value="">No history available</option>}
            {entries.map(entry => (
              <option key={entry.scan_id} value={entry.scan_id}>{entryLabel(entry)}</option>
            ))}
          </select>
        </div>
      </div>

      <div className="section">
        {loading || loadingData ? (
          <div className="loading-overlay">Loading history data...</div>
        ) : loadError ? (
          <div className="empty-state">
            <div className="icon">⚠️</div>
            <p>Couldn&apos;t load scan history: {loadError}</p>
            <button className="btn btn-secondary" style={{ marginTop: 12 }} onClick={loadEntries}>
              Retry
            </button>
          </div>
        ) : (
          <DataTable data={historyData} emptyMessage="Select a scan to view history." />
        )}
      </div>
    </>
  );
}
