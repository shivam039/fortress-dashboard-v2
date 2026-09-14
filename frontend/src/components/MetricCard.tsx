// src/components/MetricCard.tsx — Glassmorphic metric display card
'use client';

import React from 'react';
import ContextHelp from './ContextHelp';
import { findHelpKey, type HelpKey } from '@/lib/help-definitions';

interface MetricCardProps {
  label: string;
  value: string | number;
  delta?: string;
  deltaType?: 'positive' | 'negative' | 'neutral';
  helpKey?: HelpKey;
}

export default function MetricCard({ label, value, delta, deltaType, helpKey }: MetricCardProps) {
  const resolvedHelpKey = helpKey ?? findHelpKey(label);
  return (
    <div className="metric-card">
      <span className="metric-label">{label} {resolvedHelpKey && <ContextHelp helpKey={resolvedHelpKey} />}</span>
      <span className="metric-value">{value}</span>
      {delta && (
        <span className={`metric-delta ${deltaType || ''}`}>{delta}</span>
      )}
    </div>
  );
}
