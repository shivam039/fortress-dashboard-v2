// src/app/commodities/page.tsx
'use client';

import React, { useState, useEffect } from 'react';
import { commoditiesApi } from '@/lib/api';
import DataTable from '@/components/DataTable';

export default function CommoditiesPage() {
  const [data, setData] = useState<Record<string, unknown>[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    commoditiesApi.list()
      .then(setData)
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  return (
    <>
      <div className="page-header">
        <h1 className="page-title">🌍 Commodities</h1>
        <p className="page-subtitle">Track global commodity trends and generate trade alerts.</p>
      </div>

      <div className="section">
        {loading ? (
          <div className="loading-overlay">Loading commodities data...</div>
        ) : (
          <DataTable data={data} emptyMessage="No commodity data available." />
        )}
      </div>
    </>
  );
}
