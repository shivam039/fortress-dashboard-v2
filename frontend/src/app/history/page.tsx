// src/app/history/page.tsx — FORTRESS-UX1: section-first Scan History.
// SCAN HISTORY -> SELECT SECTION -> THAT SECTION'S HISTORY -> SELECT RUN ->
// READ-ONLY HISTORICAL VERSION OF THAT SCANNER. Chronology lives inside a
// section; sections never mix.
'use client';

import React, { useState, useEffect, useCallback, useMemo } from 'react';
import { useRouter } from 'next/navigation';
import { historyApi, type ScanHistoryEntry } from '@/lib/api';
import {
  STOCK_SECTION, sectionsFromEntries, filterEntriesBySection,
  describeUniverseCoverage, resolveInitialSection, setStoredSection,
} from '@/lib/scan-history';
import HistoricalStockScreener from '@/components/HistoricalStockScreener';
import HistoricalGenericScan from '@/components/HistoricalGenericScan';

function urlSection(): string | null {
  if (typeof window === 'undefined') return null;
  return new URLSearchParams(window.location.search).get('section');
}

export default function HistoryPage() {
  const router = useRouter();
  const [entries, setEntries] = useState<ScanHistoryEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [section, setSection] = useState(STOCK_SECTION);
  const [selectedScanId, setSelectedScanId] = useState<number | null>(null);
  const [historyData, setHistoryData] = useState<Record<string, unknown>[] | null>(null);
  const [loadingData, setLoadingData] = useState(false);
  const [dataError, setDataError] = useState<string | null>(null);

  const loadEntries = useCallback(() => {
    setLoading(true);
    setLoadError(null);
    historyApi.timestamps()
      .then(list => {
        setEntries(list);
        const sections = sectionsFromEntries(list);
        setSection(resolveInitialSection(urlSection(), sections));
      })
      .catch((err: unknown) => setLoadError((err as Error).message || 'Unknown error'))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    loadEntries();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const sections = useMemo(() => sectionsFromEntries(entries), [entries]);
  const sectionEntries = useMemo(() => filterEntriesBySection(entries, section), [entries, section]);

  const selectSection = useCallback((scanType: string) => {
    setSection(scanType);
    setSelectedScanId(null);
    setHistoryData(null);
    setStoredSection(scanType);
    const params = new URLSearchParams(window.location.search);
    params.set('section', scanType);
    router.replace(`/history?${params.toString()}`);
  }, [router]);

  const openRun = useCallback((scanId: number) => {
    setSelectedScanId(scanId);
    setHistoryData(null);
    setDataError(null);
    setLoadingData(true);
    historyApi.data(scanId)
      .then(setHistoryData)
      .catch((err: unknown) => setDataError((err as Error).message || 'Unknown error'))
      .finally(() => setLoadingData(false));
  }, []);

  const closeRun = useCallback(() => {
    setSelectedScanId(null);
    setHistoryData(null);
    setDataError(null);
  }, []);

  const activeMeta = sections.find(s => s.scanType === section);
  const selectedEntry = sectionEntries.find(e => e.scan_id === selectedScanId) || null;

  return (
    <>
      <div className="page-header">
        <h1 className="page-title">🕐 Scan History</h1>
        <p className="page-subtitle">Pick a scanner to see its history, then open a run for a read-only replay of that scanner.</p>
      </div>

      {!selectedEntry && (
        <div className="tabs" style={{ overflowX: 'auto', flexWrap: 'nowrap' }}>
          {sections.map(s => (
            <button
              key={s.scanType}
              className={`tab ${section === s.scanType ? 'active' : ''}`}
              onClick={() => selectSection(s.scanType)}
              style={{ whiteSpace: 'nowrap' }}
            >
              {s.icon} {s.label}
            </button>
          ))}
        </div>
      )}

      {selectedEntry ? (
        loadingData ? (
          <div className="loading-overlay">{activeMeta?.loadingMessage}</div>
        ) : dataError ? (
          <div className="empty-state">
            <div className="icon">⚠️</div>
            <p>{activeMeta?.errorMessage}: {dataError}</p>
            <button className="btn btn-secondary" style={{ marginTop: 12 }} onClick={() => openRun(selectedEntry.scan_id)}>Retry</button>
          </div>
        ) : section === STOCK_SECTION ? (
          <HistoricalStockScreener entry={selectedEntry} rows={historyData || []} onBack={closeRun} />
        ) : (
          <HistoricalGenericScan entry={selectedEntry} rows={historyData || []} onBack={closeRun} />
        )
      ) : loading ? (
        <div className="loading-overlay">{activeMeta?.loadingMessage || 'Loading scan history…'}</div>
      ) : loadError ? (
        <div className="empty-state">
          <div className="icon">⚠️</div>
          <p>{activeMeta?.errorMessage || "Scan history couldn't be loaded."}: {loadError}</p>
          <button className="btn btn-secondary" style={{ marginTop: 12 }} onClick={loadEntries}>Retry</button>
        </div>
      ) : sectionEntries.length === 0 ? (
        <div className="empty-state">
          <div className="icon">🗂️</div>
          <p>{activeMeta?.emptyMessage || 'No scans yet.'}</p>
        </div>
      ) : (
        <div className="section">
          {sectionEntries.map(entry => {
            const [datePart, timePart] = entry.timestamp.split(' ');
            return (
              <div
                key={entry.scan_id}
                className="card"
                style={{ marginBottom: 12, cursor: 'pointer' }}
                onClick={() => openRun(entry.scan_id)}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', flexWrap: 'wrap', gap: 8 }}>
                  <strong>{datePart} • {timePart || ''}</strong>
                  <span className="badge">COMPLETE</span>
                </div>
                <p style={{ margin: '6px 0 0', color: 'var(--text-muted)' }}>
                  {describeUniverseCoverage(entry.universe)}
                  {typeof entry.num_scanned === 'number' && ` • ${entry.num_scanned} analysed`}
                </p>
              </div>
            );
          })}
        </div>
      )}
    </>
  );
}
