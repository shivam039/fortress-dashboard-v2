// src/components/HistoricalEvidenceCard.tsx — FORTRESS-U2: the "historical
// evidence" half of score presentation, kept as its own component
// (different heading, different visual treatment, an explicit provenance
// badge) so it can never be mistaken for the current signal in
// FortressScoreCard. CRITICAL: never computes or invents a metric — it only
// renders whatever HistoricalEvidence it's given, and shows "insufficient
// data" rather than a number when the sample is too small or a value is
// null. Until FORTRESS-R2 exists, every caller passes fixture data
// (source: 'fixture'), which is labeled as such on screen, not hidden.
'use client';

import React from 'react';
import { hasSufficientEvidence, type EvidenceValue, type HistoricalEvidence } from '../lib/score-evidence';

function EvidenceStat({ label, evidence, suffix = '' }: { label: string; evidence: EvidenceValue; suffix?: string }) {
  return (
    <div>
      <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>{label}</div>
      <div style={{ fontSize: '1.1rem', fontWeight: 600 }}>
        {evidence.value === null ? (
          <span style={{ color: 'var(--text-muted)', fontSize: '0.85rem' }}>Insufficient data</span>
        ) : (
          <>
            {evidence.value > 0 && suffix === '%' ? '+' : ''}
            {evidence.value.toFixed(1)}
            {suffix}
          </>
        )}
      </div>
    </div>
  );
}

export default function HistoricalEvidenceCard({ evidence }: { evidence: HistoricalEvidence }) {
  const sufficient = hasSufficientEvidence(evidence);
  const isFixture =
    evidence.historicalWinRatePct.source === 'fixture' ||
    evidence.medianForwardReturnPct.source === 'fixture' ||
    evidence.benchmarkExcessReturnPct.source === 'fixture';

  return (
    <div
      data-testid="historical-evidence-card"
      style={{
        background: 'var(--bg-card)',
        border: '1px dashed var(--border-default)', // dashed border: visually distinct from the solid current-signal card
        borderRadius: 'var(--radius-md)',
        padding: 16,
      }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 4 }}>
        <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)', letterSpacing: '0.05em' }}>
          HISTORICAL EVIDENCE
        </div>
        <span
          data-testid="evidence-source-badge"
          style={{
            fontSize: '0.62rem',
            padding: '1px 6px',
            borderRadius: 999,
            background: isFixture ? 'rgba(148,163,184,0.15)' : 'var(--color-success-bg)',
            color: isFixture ? 'var(--text-muted)' : 'var(--color-success)',
          }}
        >
          {isFixture ? 'ILLUSTRATIVE — FIXTURE DATA' : 'MODEL-DERIVED (R2)'}
        </span>
      </div>

      <p style={{ fontSize: '0.72rem', color: 'var(--text-muted)', margin: '0 0 4px' }}>
        How signals like this one performed historically — not a forecast for this signal, and
        not part of today&rsquo;s Fortress Score above.
      </p>

      {(evidence.scoreBucket || evidence.generatedAt) && (
        <p style={{ fontSize: '0.68rem', color: 'var(--text-muted)', margin: '0 0 10px' }}>
          {evidence.scoreBucket && <>Score bucket {evidence.scoreBucket} &middot; </>}
          {evidence.windowDays}D horizon
          {evidence.generatedAt && (
            <> &middot; as of {new Date(evidence.generatedAt).toLocaleDateString()}</>
          )}
          {evidence.stale && (
            <span style={{ color: 'var(--color-warning)' }}> &middot; result may be stale</span>
          )}
        </p>
      )}

      {!sufficient ? (
        <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>
          Insufficient historical sample ({evidence.sampleSize} signal{evidence.sampleSize === 1 ? '' : 's'}) to
          report evidence reliably.
        </div>
      ) : (
        <>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 12, marginBottom: 8 }}>
            <EvidenceStat label="Historical win rate" evidence={evidence.historicalWinRatePct} suffix="%" />
            <EvidenceStat label={`Median ${evidence.windowDays}D forward return`} evidence={evidence.medianForwardReturnPct} suffix="%" />
            <EvidenceStat label="Excess return vs. benchmark" evidence={evidence.benchmarkExcessReturnPct} suffix="%" />
          </div>
          <div style={{ fontSize: '0.68rem', color: 'var(--text-muted)' }}>
            Sample size: {evidence.sampleSize} historical signal{evidence.sampleSize === 1 ? '' : 's'}
          </div>
        </>
      )}
    </div>
  );
}
