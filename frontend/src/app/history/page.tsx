// src/app/history/page.tsx
'use client';

import React, { useState, useEffect } from 'react';
import { api } from '@/lib/api';
import DataTable from '@/components/DataTable';

export default function HistoryPage() {
  const [timestamps, setTimestamps] = useState<string[]>([]);
  const [selectedTimestamp, setSelectedTimestamp] = useState<string>('');
  const [historyData, setHistoryData] = useState<Record<string, unknown>[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadingData, setLoadingData] = useState(false);

  useEffect(() => {
    api.get<string[]>('/api/history/timestamps')
      .then(ts => {
        setTimestamps(ts);
        if (ts.length > 0) setSelectedTimestamp(ts[0]);
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    if (!selectedTimestamp) return;
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setLoadingData(true);
    api.get<Record<string, unknown>[]>(`/api/history/data?timestamp=${encodeURIComponent(selectedTimestamp)}`)
      .then(setHistoryData)
      .catch(() => {})
      .finally(() => setLoadingData(false));
  }, [selectedTimestamp]);

  return (
    <>
      <div className="page-header">
        <h1 className="page-title">🕐 Scan History</h1>
        <p className="page-subtitle">View results from past screener runs.</p>
      </div>

      <div className="card" style={{ marginBottom: '24px' }}>
        <div className="input-group" style={{ maxWidth: '400px' }}>
          <label>Select Scan Time</label>
          <select 
            className="input" 
            value={selectedTimestamp} 
            onChange={e => setSelectedTimestamp(e.target.value)}
            disabled={loading || timestamps.length === 0}
          >
            {timestamps.length === 0 && <option value="">No history available</option>}
            {timestamps.map(t => <option key={t} value={t}>{t}</option>)}
          </select>
        </div>
      </div>

      <div className="section">
        {loadingData ? (
          <div className="loading-overlay">Loading history data...</div>
        ) : (
          <DataTable data={historyData} emptyMessage="Select a timestamp to view history." />
        )}
      </div>
    </>
  );
}
