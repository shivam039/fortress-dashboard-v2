// src/components/SystemStatus.tsx — API health + status indicators
'use client';

import React, { useState, useEffect } from 'react';
import { healthApi } from '@/lib/api';

export default function SystemStatus() {
  const [apiOnline, setApiOnline] = useState<boolean | null>(null);

  useEffect(() => {
    healthApi.check().then(setApiOnline);
    const interval = setInterval(() => {
      healthApi.check().then(setApiOnline);
    }, 30000); // check every 30s
    return () => clearInterval(interval);
  }, []);

  return (
    <div className="status-bar">
      <span className="status-label">
        <span className={`status-dot ${apiOnline ? 'online' : apiOnline === false ? 'offline' : ''}`} />
        {apiOnline === null ? 'Checking…' : apiOnline ? 'API' : 'API offline'}
      </span>
    </div>
  );
}
