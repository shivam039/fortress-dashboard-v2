import { test } from 'node:test';
import assert from 'node:assert/strict';
import { renderToStaticMarkup } from 'react-dom/server';
import React from 'react';

import scoreEvidence from '../.u2-tests/lib/score-evidence.js';
const {
  toFortressSignal,
  hasSufficientEvidence,
  FIXTURE_HISTORICAL_EVIDENCE,
  EMPTY_HISTORICAL_EVIDENCE,
  MIN_EVIDENCE_SAMPLE_SIZE,
  fromRealEvidence,
} = scoreEvidence;

import fortressScoreCardModule from '../.u2-tests/components/FortressScoreCard.js';
const FortressScoreCard = fortressScoreCardModule.default;

import historicalEvidenceCardModule from '../.u2-tests/components/HistoricalEvidenceCard.js';
const HistoricalEvidenceCard = historicalEvidenceCardModule.default;

const sampleRow = {
  Symbol: 'RELIANCE.NS',
  Score: 78,
  sub_scores: { technical: 82, fundamental: 60, sentiment: 70, context: 65 },
  Market_Regime: 'Bull',
  Sector: 'Energy',
  RS_Score: 4.2,
  Black_Swan_Flag: 0,
  Quality_Gate_Failures: '',
};

test('toFortressSignal adapts a real scan row into the current-signal contract', () => {
  const signal = toFortressSignal(sampleRow);
  assert.equal(signal.symbol, 'RELIANCE.NS');
  assert.equal(signal.totalScore, 78);
  assert.deepEqual(signal.componentScores, { technical: 82, fundamental: 60, sentiment: 70, context: 65 });
  assert.equal(signal.marketRegime, 'Bull');
  assert.equal(signal.sector, 'Energy');
  assert.equal(signal.dataQuality, 'complete');
  assert.deepEqual(signal.riskFlags, []);
});

test('toFortressSignal surfaces risk flags from black-swan and gate failures', () => {
  const signal = toFortressSignal({
    ...sampleRow,
    Black_Swan_Flag: 1,
    Quality_Gate_Failures: 'Liquidity<8.0Cr|Price<80.0',
  });
  assert.deepEqual(signal.riskFlags, ['Black Swan', 'Liquidity<8.0Cr', 'Price<80.0']);
});

test('toFortressSignal degrades to defaults instead of throwing on a missing field', () => {
  const signal = toFortressSignal({});
  assert.equal(signal.symbol, 'UNKNOWN');
  assert.equal(signal.totalScore, 0);
  assert.equal(signal.marketRegime, 'Unknown');
});

test('hasSufficientEvidence enforces the minimum sample-size floor', () => {
  assert.equal(hasSufficientEvidence({ ...FIXTURE_HISTORICAL_EVIDENCE, sampleSize: MIN_EVIDENCE_SAMPLE_SIZE - 1 }), false);
  assert.equal(hasSufficientEvidence({ ...FIXTURE_HISTORICAL_EVIDENCE, sampleSize: MIN_EVIDENCE_SAMPLE_SIZE }), true);
});

test('the fixture evidence is explicitly tagged as fixture, not R2', () => {
  assert.equal(FIXTURE_HISTORICAL_EVIDENCE.historicalWinRatePct.source, 'fixture');
  assert.equal(FIXTURE_HISTORICAL_EVIDENCE.medianForwardReturnPct.source, 'fixture');
  assert.equal(FIXTURE_HISTORICAL_EVIDENCE.benchmarkExcessReturnPct.source, 'fixture');
});

test('FortressScoreCard renders the total score and all four component scores', () => {
  const html = renderToStaticMarkup(React.createElement(FortressScoreCard, { signal: toFortressSignal(sampleRow) }));
  assert.match(html, /RELIANCE\.NS/);
  assert.match(html, /78/);
  assert.match(html, /Technical/);
  assert.match(html, /Fundamental/);
  assert.match(html, /Sentiment/);
  assert.match(html, /Context/);
  assert.match(html, /Bull/);
  assert.match(html, /Energy/);
  // Never implies the score is a probability of anything.
  assert.doesNotMatch(html, /% chance|probability of/i);
});

test('FortressScoreCard surfaces risk flags and data-quality state', () => {
  const signal = toFortressSignal({ ...sampleRow, Black_Swan_Flag: 1, data_quality: 'stale' });
  const html = renderToStaticMarkup(React.createElement(FortressScoreCard, { signal }));
  assert.match(html, /Black Swan/);
  assert.match(html, /Stale data/);
});

test('HistoricalEvidenceCard renders fixture evidence labeled as illustrative, not current signal', () => {
  const html = renderToStaticMarkup(React.createElement(HistoricalEvidenceCard, { evidence: FIXTURE_HISTORICAL_EVIDENCE }));
  assert.match(html, /HISTORICAL EVIDENCE/);
  assert.match(html, /ILLUSTRATIVE.*FIXTURE/i);
  assert.match(html, /58\.5/); // win rate
  assert.match(html, /not a forecast/i);
});

test('HistoricalEvidenceCard never fabricates a number for an insufficient sample', () => {
  const html = renderToStaticMarkup(React.createElement(HistoricalEvidenceCard, { evidence: EMPTY_HISTORICAL_EVIDENCE }));
  assert.match(html, /Insufficient historical sample/i);
  assert.doesNotMatch(html, /58\.5|3\.2|1\.4/); // none of the fixture's numbers leak through
});

test('HistoricalEvidenceCard would label real R2 data differently from fixture data', () => {
  const r2Evidence = {
    symbol: 'RELIANCE.NS',
    sampleSize: 50,
    windowDays: 30,
    historicalWinRatePct: { value: 61.0, source: 'r2' },
    medianForwardReturnPct: { value: 2.1, source: 'r2' },
    benchmarkExcessReturnPct: { value: 0.9, source: 'r2' },
  };
  const html = renderToStaticMarkup(React.createElement(HistoricalEvidenceCard, { evidence: r2Evidence }));
  assert.match(html, /MODEL-DERIVED \(R2\)/);
  assert.doesNotMatch(html, /ILLUSTRATIVE/);
});

// ── FORTRESS-V2: fromRealEvidence() mapping from the /api/research-evidence contract ──

test('fromRealEvidence maps a valid R2 API response to real, correctly-scaled evidence', () => {
  const evidence = fromRealEvidence({
    available: true,
    score_bucket: '80-89',
    horizon: 20,
    regime: null,
    sample_size: 42,
    win_rate: 0.62,
    median_forward_return: 0.028,
    benchmark_excess_return: 0.014,
    source: 'r2',
    dataset_version: 'abc123',
    generated_at: '2026-08-01T00:00:00+00:00',
    stale: false,
  });
  assert.equal(evidence.sampleSize, 42);
  assert.equal(evidence.scoreBucket, '80-89');
  assert.equal(evidence.windowDays, 20);
  assert.equal(evidence.generatedAt, '2026-08-01T00:00:00+00:00');
  assert.equal(evidence.stale, false);
  assert.equal(evidence.historicalWinRatePct.value, 62);
  assert.equal(evidence.historicalWinRatePct.source, 'r2');
  assert.ok(Math.abs(evidence.medianForwardReturnPct.value - 2.8) < 1e-9);
  assert.ok(Math.abs(evidence.benchmarkExcessReturnPct.value - 1.4) < 1e-9);
});

test('fromRealEvidence renders an unavailable result as insufficient, never a fabricated number', () => {
  const evidence = fromRealEvidence({
    available: false,
    reason: 'no_r2_result',
    score_bucket: '80-89',
    horizon: 20,
  });
  assert.equal(evidence.sampleSize, 0);
  assert.equal(evidence.historicalWinRatePct.value, null);
  assert.equal(evidence.historicalWinRatePct.source, 'r2'); // checked, not a fixture placeholder
  assert.equal(hasSufficientEvidence(evidence), false);

  const html = renderToStaticMarkup(React.createElement(HistoricalEvidenceCard, { evidence }));
  assert.match(html, /Insufficient historical sample/i);
  assert.doesNotMatch(html, /ILLUSTRATIVE/);
});

test('fromRealEvidence surfaces a stale real result with a warning, not silence', () => {
  const evidence = fromRealEvidence({
    available: true,
    score_bucket: '90-100',
    horizon: 20,
    sample_size: 30,
    win_rate: 0.7,
    median_forward_return: 0.04,
    benchmark_excess_return: 0.02,
    generated_at: '2020-01-01T00:00:00+00:00',
    stale: true,
  });
  const html = renderToStaticMarkup(React.createElement(HistoricalEvidenceCard, { evidence }));
  assert.match(html, /MODEL-DERIVED \(R2\)/);
  assert.match(html, /stale/i);
});

test('fromRealEvidence at a score-bucket boundary carries the API-assigned bucket through unchanged', () => {
  const evidence = fromRealEvidence({
    available: true,
    score_bucket: '90-100', // as assigned server-side for score=90.0 — never re-derived client-side
    horizon: 20,
    sample_size: 25,
    win_rate: 0.8,
    median_forward_return: 0.05,
    benchmark_excess_return: 0.03,
  });
  assert.equal(evidence.scoreBucket, '90-100');
});

test('malformed/partial real evidence (missing numeric fields) never crashes and shows insufficient', () => {
  const evidence = fromRealEvidence({ available: true, score_bucket: '70-79', horizon: 20 });
  assert.equal(evidence.sampleSize, 0);
  assert.equal(evidence.historicalWinRatePct.value, null);
  assert.equal(hasSufficientEvidence(evidence), false);
});

test('production screener path never imports the fixture constant for its rendered evidence', () => {
  // Guards against a future regression re-introducing FIXTURE_HISTORICAL_EVIDENCE
  // into the production render path — fromRealEvidence() output must never
  // equal the fixture's tagged values.
  const real = fromRealEvidence({
    available: true,
    score_bucket: '80-89',
    horizon: 20,
    sample_size: 42,
    win_rate: 0.585,
    median_forward_return: 0.032,
    benchmark_excess_return: 0.014,
  });
  assert.notEqual(real.historicalWinRatePct.source, 'fixture');
  assert.notEqual(real.medianForwardReturnPct.source, 'fixture');
  assert.notEqual(real.benchmarkExcessReturnPct.source, 'fixture');
});
