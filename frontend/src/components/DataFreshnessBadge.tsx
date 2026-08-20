// src/components/DataFreshnessBadge.tsx — Shows data age with color coding
'use client';

import React from 'react';

interface DataFreshnessBadgeProps {
  isoTimestamp: string | null | undefined;
  staleThresholdHours?: number;
  warningThresholdHours?: number;
}

function formatAge(timestamp: string): string {
  try {
    const now = Date.now();
    const then = new Date(timestamp).getTime();
    const diffMs = now - then;
    const mins = Math.floor(diffMs / 60_000);
    const hours = Math.floor(mins / 60);
    const days = Math.floor(hours / 24);
    if (mins < 2) return 'just now';
    if (mins < 60) return `${mins}m ago`;
    if (hours < 24) return `${hours}h ago`;
    return `${days}d ago`;
  } catch {
    return 'unknown';
  }
}

function getAgeHours(timestamp: string): number {
  try {
    return (Date.now() - new Date(timestamp).getTime()) / 3_600_000;
  } catch {
    return 999;
  }
}

export default function DataFreshnessBadge({
  isoTimestamp,
  staleThresholdHours = 24,
  warningThresholdHours = 4,
}: DataFreshnessBadgeProps) {
  if (!isoTimestamp) {
    return (
      <span style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>
        ○ No data
      </span>
    );
  }

  const hours = getAgeHours(isoTimestamp);
  const isStale = hours >= staleThresholdHours;
  const isWarning = hours >= warningThresholdHours && !isStale;
  const color = isStale ? 'var(--color-danger)' : isWarning ? 'var(--color-warning)' : 'var(--color-success)';
  const dot = isStale ? '○' : isWarning ? '◐' : '●';

  return (
    <span
      title={`Last updated: ${new Date(isoTimestamp).toLocaleString()}`}
      style={{
        fontSize: '0.72rem', color,
        display: 'inline-flex', alignItems: 'center', gap: 4,
        padding: '2px 8px', borderRadius: 999,
        background: isStale
          ? 'var(--color-danger-bg)'
          : isWarning
          ? 'var(--color-warning-bg)'
          : 'var(--color-success-bg)',
        border: `1px solid ${color}40`,
      }}
    >
      {dot} Updated {formatAge(isoTimestamp)}
    </span>
  );
}
