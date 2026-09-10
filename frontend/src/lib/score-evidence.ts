// src/lib/score-evidence.ts — Data contracts for FORTRESS-U2's score
// presentation. Two kinds of data, deliberately kept as separate types so a
// component can never accidentally blend them:
//
//   - FortressSignal: today's scan output — what apply_advanced_scoring()
//     actually computed for this symbol, right now. Always real.
//   - HistoricalEvidence: how signals like this one have performed in the
//     past. Until FORTRESS-R2 (the historical backtest/ledger-replay
//     pipeline) exists, this is ALWAYS fixture data — see
//     FIXTURE_HISTORICAL_EVIDENCE below — never computed or guessed here.
//     `source` on every value makes this explicit at the type level, not
//     just in a comment, so a real R2 integration is a matter of
//     constructing an `EvidenceValue` with `source: 'r2'` and passing it
//     in — no component redesign required.

export interface FortressSignal {
  symbol: string;
  totalScore: number; // 0-100, apply_advanced_scoring()'s "Score"
  componentScores: {
    technical: number;
    fundamental: number;
    sentiment: number;
    context: number;
  };
  marketRegime: string; // e.g. "Bull", "Range", "Bear"
  sector: string;
  relativeStrength: number; // RS_Score vs. Nifty
  riskFlags: string[]; // e.g. "Black Swan Flag", "Low Liquidity"
  dataQuality: 'complete' | 'partial' | 'stale';
}

// A single evidence figure, tagged with where it came from — the type
// system's way of enforcing "clearly distinguish current signal / historical
// evidence / model-derived metrics" (FORTRESS-U2's CRITICAL requirement).
export interface EvidenceValue {
  value: number | null; // null = insufficient sample, never fabricated
  source: 'fixture' | 'r2'; // 'fixture' until FORTRESS-R2 ships real data
}

export interface HistoricalEvidence {
  symbol: string;
  sampleSize: number;
  windowDays: number; // forward-return measurement window
  historicalWinRatePct: EvidenceValue;
  medianForwardReturnPct: EvidenceValue;
  benchmarkExcessReturnPct: EvidenceValue;
}

// Minimum sample size below which evidence is presented as "insufficient"
// rather than a number that looks more confident than it is.
export const MIN_EVIDENCE_SAMPLE_SIZE = 20;

export function hasSufficientEvidence(evidence: HistoricalEvidence): boolean {
  return evidence.sampleSize >= MIN_EVIDENCE_SAMPLE_SIZE;
}

// FORTRESS-R2 is not available yet (per the U2 spec: "If R2 is not
// available yet, use fixtures only"). This fixture is illustrative UI
// content, not a claim about any real symbol's performance — every
// consumer must render it through the same "Historical Evidence" section
// used for real R2 data, so it's visibly separate from the current signal
// above it, and the `source: 'fixture'` tag is what a live R2 integration
// flips to `'r2'`.
export const FIXTURE_HISTORICAL_EVIDENCE: HistoricalEvidence = {
  symbol: 'FIXTURE',
  sampleSize: 42,
  windowDays: 30,
  historicalWinRatePct: { value: 58.5, source: 'fixture' },
  medianForwardReturnPct: { value: 3.2, source: 'fixture' },
  benchmarkExcessReturnPct: { value: 1.4, source: 'fixture' },
};

// A symbol with no ledger history yet (FORTRESS-T1) — the honest "no data"
// case, not a hidden zero.
export const EMPTY_HISTORICAL_EVIDENCE: HistoricalEvidence = {
  symbol: '',
  sampleSize: 0,
  windowDays: 30,
  historicalWinRatePct: { value: null, source: 'fixture' },
  medianForwardReturnPct: { value: null, source: 'fixture' },
  benchmarkExcessReturnPct: { value: null, source: 'fixture' },
};

// Adapts one /api/scan result row (see engine/stock_scanner/logic.py's
// apply_advanced_scoring/check_institutional_fortress) into a FortressSignal.
// Kept intentionally tolerant of missing fields — a scan row's shape has
// drifted before and will again — so the UI degrades to 0/"Unknown" instead
// of throwing.
export function toFortressSignal(row: Record<string, unknown>): FortressSignal {
  const sub = (row.sub_scores as Record<string, number>) || {};
  const num = (v: unknown, fallback = 0): number => (typeof v === 'number' && !Number.isNaN(v) ? v : fallback);
  const flags: string[] = [];
  if (row.Black_Swan_Flag) flags.push('Black Swan');
  if (row.Quality_Gate_Failures) {
    String(row.Quality_Gate_Failures)
      .split('|')
      .filter(Boolean)
      .forEach(f => flags.push(f));
  }
  const dataQuality: FortressSignal['dataQuality'] =
    row.data_quality === 'partial' || row.data_quality === 'stale'
      ? (row.data_quality as 'partial' | 'stale')
      : 'complete';

  return {
    symbol: String(row.Symbol ?? 'UNKNOWN'),
    totalScore: num(row.Score),
    componentScores: {
      technical: num(sub.technical ?? row.Technical_Score),
      fundamental: num(sub.fundamental ?? row.Fundamental_Score),
      sentiment: num(sub.sentiment ?? row.Sentiment_Score),
      context: num(sub.context ?? row.Context_Score),
    },
    marketRegime: String(row.Market_Regime ?? row.Regime ?? 'Unknown'),
    sector: String(row.Sector ?? 'Unknown'),
    relativeStrength: num(row.RS_Score),
    riskFlags: flags,
    dataQuality,
  };
}
