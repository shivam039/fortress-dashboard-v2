// src/components/MetricCard.tsx — Glassmorphic metric display card
'use client';

import React from 'react';

interface MetricCardProps {
  label: string;
  value: string | number;
  delta?: string;
  deltaType?: 'positive' | 'negative' | 'neutral';
}

export default function MetricCard({ label, value, delta, deltaType }: MetricCardProps) {
  return (
    <div className="metric-card">
      <span className="metric-label">{label}</span>
      <span className="metric-value">{value}</span>
      {delta && (
        <span className={`metric-delta ${deltaType || ''}`}>{delta}</span>
      )}
    </div>
  );
}
