// src/components/FortressScoreCard.tsx — FORTRESS-U2: the "current signal"
// half of score presentation. Renders exactly what apply_advanced_scoring()
// computed for this symbol right now — total score, the four component
// scores, regime, sector, relative strength, risk flags, and data quality.
// Deliberately contains NO historical/backtest numbers — see
// HistoricalEvidenceCard for that, kept as a visually separate component so
// "today's model output" and "how signals like this did historically" can
// never be mistaken for each other.
'use client';

import React from 'react';
import type { FortressSignal } from '../lib/score-evidence';

function scoreColor(score: number): string {
  return score >= 70 ? 'var(--color-success)' : score >= 45 ? 'var(--color-warning)' : 'var(--color-danger)';
}

function ComponentBar({ label, value }: { label: string; value: number }) {
  const color = scoreColor(value);
  return (
    <div style={{ marginBottom: 8 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.75rem', marginBottom: 3 }}>
        <span style={{ color: 'var(--text-secondary)' }}>{label}</span>
        <span style={{ color, fontWeight: 600 }}>{value.toFixed(0)}</span>
      </div>
      <div style={{ height: 4, borderRadius: 2, background: 'rgba(148,163,184,0.12)', overflow: 'hidden' }}>
        <div style={{ height: '100%', width: `${Math.max(0, Math.min(100, value))}%`, background: color, borderRadius: 2 }} />
      </div>
    </div>
  );
}

const DATA_QUALITY_LABEL: Record<FortressSignal['dataQuality'], string> = {
  complete: '● Complete data',
  partial: '◐ Partial data',
  stale: '○ Stale data — treat with caution',
};

export default function FortressScoreCard({ signal }: { signal: FortressSignal }) {
  const color = scoreColor(signal.totalScore);
  return (
    <div
      data-testid="fortress-score-card"
      style={{ background: 'var(--bg-card)', border: '1px solid var(--border-default)', borderRadius: 'var(--radius-md)', padding: 16 }}
    >
      <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)', letterSpacing: '0.05em', marginBottom: 4 }}>
        CURRENT SIGNAL — {signal.symbol}
      </div>

      <div style={{ display: 'flex', alignItems: 'baseline', gap: 10 }}>
        <span data-testid="total-score" style={{ fontSize: '2rem', fontWeight: 700, color }}>
          {signal.totalScore.toFixed(0)}
        </span>
        <span style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>/ 100 Fortress Score</span>
      </div>
      {/* This is a rule-based conviction score, not a probability of any
          outcome — deliberately never phrased as "% chance" anywhere here. */}
      <p style={{ fontSize: '0.7rem', color: 'var(--text-muted)', margin: '2px 0 12px' }}>
        A rule-based conviction score (0–100) — not a probability or a return forecast.
      </p>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '4px 16px', fontSize: '0.75rem', marginBottom: 12 }}>
        <div><span style={{ color: 'var(--text-muted)' }}>Regime:</span> {signal.marketRegime}</div>
        <div><span style={{ color: 'var(--text-muted)' }}>Sector:</span> {signal.sector}</div>
        <div><span style={{ color: 'var(--text-muted)' }}>Relative strength:</span> {signal.relativeStrength.toFixed(1)}</div>
        <div style={{ color: signal.dataQuality === 'complete' ? 'var(--color-success)' : 'var(--color-warning)' }}>
          {DATA_QUALITY_LABEL[signal.dataQuality]}
        </div>
      </div>

      <div style={{ paddingTop: 8, borderTop: '1px solid var(--border-subtle)' }}>
        <ComponentBar label="Technical" value={signal.componentScores.technical} />
        <ComponentBar label="Fundamental" value={signal.componentScores.fundamental} />
        <ComponentBar label="Sentiment" value={signal.componentScores.sentiment} />
        <ComponentBar label="Context" value={signal.componentScores.context} />
      </div>

      {signal.riskFlags.length > 0 && (
        <div style={{ marginTop: 10, display: 'flex', flexWrap: 'wrap', gap: 4 }}>
          {signal.riskFlags.map(flag => (
            <span
              key={flag}
              style={{ fontSize: '0.65rem', padding: '2px 6px', borderRadius: 999, background: 'var(--color-warning-bg)', color: 'var(--color-warning)', border: '1px solid rgba(245,158,11,0.3)' }}
            >
              ⚠ {flag}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
