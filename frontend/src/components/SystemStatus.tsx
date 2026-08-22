// src/components/SystemStatus.tsx — API health + market data source indicators
'use client';

import React, { useState, useEffect, useCallback } from 'react';
import { healthApi, marketDataApi, MarketDataStatus, OhlcvProvider } from '@/lib/api';

export default function SystemStatus() {
  const [apiOnline, setApiOnline] = useState<boolean | null>(null);
  const [dataStatus, setDataStatus] = useState<MarketDataStatus | null>(null);
  const [switching, setSwitching] = useState(false);

  const poll = useCallback(() => {
    healthApi.check().then(setApiOnline);
    marketDataApi
      .status()
      .then(setDataStatus)
      .catch(() => setDataStatus(null));
  }, []);

  useEffect(() => {
    poll();
    const interval = setInterval(poll, 30000); // check every 30s
    return () => clearInterval(interval);
  }, [poll]);

  const isPrimary = dataStatus?.primary === 'indstocks';
  const liveLabel = dataStatus?.primary_label ?? (dataStatus ? 'Yahoo Finance' : null);
  // ohlcv_source/ohlcv_source_label are additive fields — default to the
  // documented "bhavcopy" default so the toggle still renders sensibly if
  // it's ever hit against a backend that hasn't picked up this change yet.
  const ohlcvSource: OhlcvProvider = (dataStatus?.ohlcv_source as OhlcvProvider) ?? 'bhavcopy';

  const switchProvider = async (provider: OhlcvProvider) => {
    if (switching || provider === ohlcvSource) return;
    setSwitching(true);
    try {
      await marketDataApi.setProvider(provider);
      poll(); // re-fetch immediately rather than waiting for the next 30s tick
    } catch {
      // Leave the UI as-is — the next poll reflects whatever the backend
      // actually has, and the click can just be retried.
    } finally {
      setSwitching(false);
    }
  };

  return (
    <div className="status-bar">
      <div className="status-bar-row">
        <span className="status-label">
          <span className={`status-dot ${apiOnline ? 'online' : apiOnline === false ? 'offline' : ''}`} />
          {apiOnline === null ? 'Checking…' : apiOnline ? 'API' : 'API offline'}
        </span>
      </div>
      <div className="status-bar-row">
        <span
          className="status-label"
          title={liveLabel ? `Live price source: ${liveLabel} (fallback: ${dataStatus?.fallback})` : undefined}
        >
          <span className={`status-dot ${liveLabel ? (isPrimary ? 'indmoney' : 'fallback') : ''}`} />
          {liveLabel ? `Live price: ${liveLabel}` : 'Live price: —'}
        </span>
      </div>
      <div className="status-bar-row provider-toggle-row">
        <span
          className="status-label"
          title="Which source scans/screening pull historical OHLCV from. Doesn't affect the live price above."
        >
          Scan data: {dataStatus?.ohlcv_source_label ?? '—'}
        </span>
        <span className="provider-toggle">
          <button
            type="button"
            className={`provider-toggle-btn ${ohlcvSource === 'bhavcopy' ? 'active' : ''}`}
            disabled={switching}
            onClick={() => switchProvider('bhavcopy')}
            title="Use NSE Bhav Copy (default) for scan/screening OHLCV data"
          >
            Bhav Copy
          </button>
          <button
            type="button"
            className={`provider-toggle-btn ${ohlcvSource === 'indstocks' ? 'active' : ''}`}
            disabled={switching}
            onClick={() => switchProvider('indstocks')}
            title="Use IndMoney/INDstocks for scan/screening OHLCV data"
          >
            IndMoney
          </button>
        </span>
      </div>
    </div>
  );
}
