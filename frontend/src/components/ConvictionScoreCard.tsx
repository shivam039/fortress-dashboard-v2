// src/components/ConvictionScoreCard.tsx — Circular score gauge + sub-score breakdown
'use client';

import React, { useState } from 'react';
import type { ScoreBreakdown } from '@/lib/types';

interface ConvictionScoreCardProps {
  score: number | null;
  confidence: number | null;
  breakdown: ScoreBreakdown | null;
  riskFlags?: string[];
  dataQuality?: string;
  compact?: boolean;
}

function ScoreArc({ score, size = 80 }: { score: number; size?: number }) {
  const radius = (size - 12) / 2;
  const circumference = 2 * Math.PI * radius;
  const fill = Math.max(0, Math.min(100, score));
  const offset = circumference - (fill / 100) * circumference;
  const color = score >= 70 ? '#10b981' : score >= 45 ? '#f59e0b' : '#f43f5e';

  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} style={{ transform: 'rotate(-90deg)' }}>
      <circle
        cx={size / 2} cy={size / 2} r={radius}
        fill="none" stroke="rgba(148,163,184,0.12)" strokeWidth={8}
      />
      <circle
        cx={size / 2} cy={size / 2} r={radius}
        fill="none" stroke={color} strokeWidth={8}
        strokeDasharray={circumference}
        strokeDashoffset={offset}
        strokeLinecap="round"
        style={{ transition: 'stroke-dashoffset 0.6s ease' }}
      />
    </svg>
  );
}

function SubScoreBar({ label, value }: { label: string; value: number }) {
  const color = value >= 70 ? 'var(--color-success)' : value >= 45 ? 'var(--color-warning)' : 'var(--color-danger)';
  const displayLabel = label
    .replace(/_/g, ' ')
    .replace(/\b\w/g, c => c.toUpperCase());

  return (
    <div style={{ marginBottom: 8 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.75rem', marginBottom: 3 }}>
        <span style={{ color: 'var(--text-secondary)' }}>{displayLabel}</span>
        <span style={{ color, fontWeight: 600 }}>{value.toFixed(0)}</span>
      </div>
      <div style={{ height: 4, borderRadius: 2, background: 'rgba(148,163,184,0.12)', overflow: 'hidden' }}>
        <div
          style={{
            height: '100%',
            width: `${value}%`,
            background: color,
            borderRadius: 2,
            transition: 'width 0.5s ease',
          }}
        />
      </div>
    </div>
  );
}

export default function ConvictionScoreCard({
  score,
  confidence,
  breakdown,
  riskFlags = [],
  dataQuality = 'complete',
  compact = false,
}: ConvictionScoreCardProps) {
  const [expanded, setExpanded] = useState(false);

  if (score === null || score === undefined) {
    return (
      <div style={{ textAlign: 'center', color: 'var(--text-muted)', fontSize: '0.78rem' }}>
        Score unavailable
      </div>
    );
  }

  const scoreColor = score >= 70 ? 'var(--color-success)' : score >= 45 ? 'var(--color-warning)' : 'var(--color-danger)';
  const qualityColor = dataQuality === 'complete' ? 'var(--color-success)' : dataQuality === 'partial' ? 'var(--color-warning)' : 'var(--color-danger)';

  return (
    <div
      style={{
        background: 'var(--bg-card)',
        border: '1px solid var(--border-default)',
        borderRadius: 'var(--radius-md)',
        padding: compact ? '12px' : '16px',
      }}
    >
      {/* Score + Confidence */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
        <div style={{ position: 'relative', flexShrink: 0 }}>
          <ScoreArc score={score} size={compact ? 64 : 80} />
          <div style={{
            position: 'absolute', inset: 0,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            fontSize: compact ? '0.9rem' : '1.1rem',
            fontWeight: 700, color: scoreColor,
          }}>
            {score.toFixed(0)}
          </div>
        </div>

        <div style={{ flex: 1 }}>
          <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)', marginBottom: 2 }}>
            CONVICTION
          </div>
          <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', marginBottom: 4 }}>
            Confidence:{' '}
            <span style={{ color: qualityColor, fontWeight: 600 }}>
              {confidence !== null ? `${confidence}%` : '—'}
            </span>
          </div>
          <div style={{ fontSize: '0.7rem', color: qualityColor }}>
            {dataQuality === 'complete' ? '● Complete data' : dataQuality === 'partial' ? '◐ Partial data' : '○ Stale data'}
          </div>
        </div>

        {!compact && breakdown && Object.keys(breakdown).length > 0 && (
          <button
            onClick={() => setExpanded(v => !v)}
            style={{
              background: 'none', border: '1px solid var(--border-default)',
              borderRadius: 'var(--radius-sm)', color: 'var(--text-muted)',
              cursor: 'pointer', fontSize: '0.72rem', padding: '4px 8px',
            }}
          >
            {expanded ? 'Hide ▲' : 'Breakdown ▼'}
          </button>
        )}
      </div>

      {/* Sub-score breakdown */}
      {(expanded || compact) && breakdown && (
        <div style={{ marginTop: 12, paddingTop: 12, borderTop: '1px solid var(--border-subtle)' }}>
          {Object.entries(breakdown).map(([k, v]) =>
            v !== undefined && v !== null ? (
              <SubScoreBar key={k} label={k} value={v} />
            ) : null
          )}
        </div>
      )}

      {/* Risk flags */}
      {riskFlags.length > 0 && (
        <div style={{ marginTop: 8, display: 'flex', flexWrap: 'wrap', gap: 4 }}>
          {riskFlags.slice(0, 4).map(flag => (
            <span
              key={flag}
              style={{
                fontSize: '0.65rem', padding: '2px 6px', borderRadius: 999,
                background: 'var(--color-warning-bg)', color: 'var(--color-warning)',
                border: '1px solid rgba(245,158,11,0.3)',
              }}
            >
              ⚠ {flag.replace(/_/g, ' ')}
            </span>
          ))}
          {riskFlags.length > 4 && (
            <span style={{ fontSize: '0.65rem', color: 'var(--text-muted)' }}>
              +{riskFlags.length - 4} more
            </span>
          )}
        </div>
      )}
    </div>
  );
}
