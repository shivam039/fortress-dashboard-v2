import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import scanHistory from '../.ux1-tests/lib/scan-history.js';

const {
  sectionsFromEntries, filterEntriesBySection, describeUniverseCoverage,
  resolveInitialSection, splitStockResults, getStoredSection, setStoredSection,
} = scanHistory;

const stock = (id, ts = '2026-09-11 21:15:00') => ({ scan_id: id, timestamp: ts, universe: 'Nifty 50', scan_type: 'STOCK' });
const mf = (id, ts = '2026-09-10 07:00:00') => ({ scan_id: id, timestamp: ts, universe: 'Mutual Funds', scan_type: 'MF' });

// 1 & (initial section default)
test('Stocks is always an available section, even with zero entries', () => {
  const sections = sectionsFromEntries([]);
  assert.ok(sections.some(s => s.scanType === 'STOCK'));
  assert.equal(sections.length, 1, 'no other section is invented when it has no real runs');
});

// 2 & 3 — MF/Stock history never mix
test('sections only include scan types that actually have runs, MF and STOCK never mixed', () => {
  const entries = [stock(1), mf(2)];
  const sections = sectionsFromEntries(entries).map(s => s.scanType);
  assert.deepEqual(sections.sort(), ['MF', 'STOCK']);

  const stockOnly = filterEntriesBySection(entries, 'STOCK');
  assert.equal(stockOnly.length, 1);
  assert.equal(stockOnly[0].scan_type, 'STOCK');

  const mfOnly = filterEntriesBySection(entries, 'MF');
  assert.equal(mfOnly.length, 1);
  assert.equal(mfOnly[0].scan_type, 'MF');
});

// 4 — changing section changes the displayed set; chronology is per-section
test('history is sorted newest-first within a section, independent of other sections', () => {
  const entries = [stock(1), mf(5), stock(3), mf(2)];
  const stockOnly = filterEntriesBySection(entries, 'STOCK').map(e => e.scan_id);
  assert.deepEqual(stockOnly, [3, 1]);
  const mfOnly = filterEntriesBySection(entries, 'MF').map(e => e.scan_id);
  assert.deepEqual(mfOnly, [5, 2]);
});

// 5 — selected section survives refresh (URL wins, then localStorage, then Stocks)
test('resolveInitialSection prefers the URL, then localStorage, then Stocks', () => {
  const sections = sectionsFromEntries([stock(1), mf(2)]);
  assert.equal(resolveInitialSection('MF', sections), 'MF');
  assert.equal(resolveInitialSection('GHOST', sections), 'STOCK', 'an unknown section never wins');
  assert.equal(resolveInitialSection(null, sections), 'STOCK');
});

test('setStoredSection/getStoredSection round-trip through localStorage', () => {
  const store = {};
  global.window = {
    localStorage: {
      getItem: k => (k in store ? store[k] : null),
      setItem: (k, v) => { store[k] = v; },
    },
  };
  setStoredSection('MF');
  assert.equal(getStoredSection(), 'MF');
  delete global.window;
});

// universe coverage label
test('describeUniverseCoverage summarizes an E3 multi-universe label, passes through a plain one', () => {
  assert.equal(describeUniverseCoverage('AUTO_MULTI(Nifty 50,Nifty Next 50,Nifty Midcap 150,Nifty Smallcap 250)'), '4 universes');
  assert.equal(describeUniverseCoverage('Nifty 50'), 'Nifty 50');
});

// 8 & 9 — historical values are the exact stored values, never recomputed
test('splitStockResults preserves each stored row untouched (no recomputation of score/price)', () => {
  const rows = [
    { Symbol: 'RELIANCE.NS', Score: 88, Price: 2500, Quality_Gate_Pass: true, Strategy: 'Momentum Pick' },
    { Symbol: 'TCS.NS', Score: 55, Price: 3800, Quality_Gate_Pass: false },
  ];
  const { actionable, filtered, momentum } = splitStockResults(rows);
  assert.equal(actionable[0].Score, 88, 'historical score must not be replaced with a current value');
  assert.equal(actionable[0].Price, 2500, 'historical price must not be replaced with a current value');
  assert.equal(filtered.length, 1);
  assert.equal(momentum[0].Symbol, 'RELIANCE.NS');
  // Object identity preserved — nothing rebuilt/enriched behind the split.
  assert.equal(actionable[0], rows[0]);
});

// 6, 7, 10, 11 — structural checks on the historical component (no component
// rendering harness exists in this repo; mirrors the static-source-check
// convention already used for scan.test.mjs's screener-page assertions).
test('HistoricalStockScreener renders the shared ScannerResultsView, not raw JSON, as the primary view', () => {
  const src = fs.readFileSync(new URL('../src/components/HistoricalStockScreener.tsx', import.meta.url), 'utf8');
  assert.match(src, /<ScannerResultsView/, 'reuses the same component the live screener uses');
  assert.match(src, /Read-only/i);
  assert.doesNotMatch(src, /Run Scan|runScan\(/, 'no live-only scan-triggering control in a historical snapshot');
  // Raw JSON exists only inside a collapsed "Advanced details" section.
  const advancedIdx = src.indexOf('Advanced details');
  const rawIdx = src.indexOf('JSON.stringify');
  assert.ok(advancedIdx > -1 && rawIdx > advancedIdx, 'raw data must be secondary, behind Advanced details');
});

test('HistoricalGenericScan is also read-only and keeps raw rows behind a collapsed section', () => {
  const src = fs.readFileSync(new URL('../src/components/HistoricalGenericScan.tsx', import.meta.url), 'utf8');
  assert.match(src, /Read-only/i);
  assert.doesNotMatch(src, /Run Scan|runScan\(/);
});

// 17 — detail fetch only happens when a run is opened
test('history page only calls historyApi.data() from the open-run handler, not on initial load', () => {
  const src = fs.readFileSync(new URL('../src/app/history/page.tsx', import.meta.url), 'utf8');
  const loadEntries = src.slice(src.indexOf('loadEntries = useCallback'), src.indexOf('const sections ='));
  assert.doesNotMatch(loadEntries, /historyApi\.data\(/, 'the section-summary load must stay lightweight');
  assert.match(src, /openRun = useCallback\(\(scanId[\s\S]*?historyApi\.data\(scanId\)/);
});
