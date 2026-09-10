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
