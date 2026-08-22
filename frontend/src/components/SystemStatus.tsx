// src/components/SystemStatus.tsx — API health + market data source indicators
'use client';

import React, { useState, useEffect } from 'react';
import { healthApi, marketDataApi, MarketDataStatus } from '@/lib/api';

export default function SystemStatus() {
  const [apiOnline, setApiOnline] = useState<boolean | null>(null);
  const [dataStatus, setDataStatus] = useState<MarketDataStatus | null>(null);

  useEffect(() => {
    const poll = () => {
      healthApi.check().then(setApiOnline);
      marketDataApi
        .status()
        .then(setDataStatus)
        .catch(() => setDataStatus(null));
    };
    poll();
    const interval = setInterval(poll, 30000); // check every 30s
    return () => clearInterval(interval);
  }, []);

  const isPrimary = dataStatus?.primary === 'indstocks';
  const sourceLabel = dataStatus?.primary_label ?? (dataStatus ? 'Yahoo Finance' : null);

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
          title={
            dataStatus
              ? `Market data primary: ${sourceLabel} (fallback: ${dataStatus.fallback})`
              : undefined
          }
        >
          <span className={`status-dot ${sourceLabel ? (isPrimary ? 'indmoney' : 'fallback') : ''}`} />
          {sourceLabel ? `Data: ${sourceLabel}` : 'Data source: —'}
        </span>
      </div>
    </div>
  );
}
