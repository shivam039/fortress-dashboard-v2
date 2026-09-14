import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import help from '../.ux1-tests/lib/help-definitions.js';

const { helpDefinitions, findHelpKey } = help;

test('canonical help registry has unique glossary anchors and useful descriptions', () => {
  const entries = Object.values(helpDefinitions);
  assert.ok(entries.length >= 30);
  assert.equal(new Set(entries.map(item => item.glossaryKey)).size, entries.length);
  for (const item of entries) {
    assert.ok(item.shortDescription.length >= 60, `${item.label} needs an explanatory definition`);
    assert.notEqual(item.shortDescription.toLowerCase(), item.label.toLowerCase());
  }
});

test('representative cross-product table headings resolve to canonical help', () => {
  for (const label of ['RSI', 'ADX', 'Score', 'Confidence', 'Hit Rate', 'Entry', '1Y Ret', 'NAV', 'Sharpe', 'Yield', 'OI', 'ChangeOI', 'IV', 'Bid', 'Ask']) {
    assert.ok(findHelpKey(label), `${label} should resolve`);
  }
});

test('DataTable keeps help and sorting as separate controls', () => {
  const source = fs.readFileSync(new URL('../src/components/DataTable.tsx', import.meta.url), 'utf8');
  assert.match(source, /<ColumnHeader column=/);
  assert.match(source, /className="column-sort-trigger"/);
  assert.doesNotMatch(source, /<th[\s\S]{0,120}onClick=/);
});

test('tooltip supports focus, tap, escape, and a term deep link', () => {
  const source = fs.readFileSync(new URL('../src/components/ContextHelp.tsx', import.meta.url), 'utf8');
  assert.match(source, /onClick=/);
  assert.match(source, /onFocus=/);
  assert.match(source, /event\.key === 'Escape'/);
  assert.match(source, /help\/glossary#/);
});

test('in-app glossary searches canonical metadata and exposes stable anchors', () => {
  const source = fs.readFileSync(new URL('../src/app/help/glossary/page.tsx', import.meta.url), 'utf8');
  assert.match(source, /type="search"/);
  assert.match(source, /id=\{item\.glossaryKey\}/);
  assert.match(source, /Object\.values\(helpDefinitions\)/);
});
