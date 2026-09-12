const test = require('node:test');
const assert = require('node:assert/strict');
const { buildIssue, fingerprint, syncFinding } = require('./github-issue-sync');

const finding = (extra = {}) => ({ finding_id: 'F-1', run_id: 'R-1', surface: 'Scan History', scenario: 'API failure state', route: '/history', error_signature: 'HTTP 500', classification: 'AUTO_TRIAGE_ELIGIBLE', severity: 'QA2', observed: 'spinner remains', expected: 'clear error', specialist: 'frontend', evidence: { Authorization: 'Bearer secret' }, ...extra });

test('actionable finding creates one sanitized issue', async () => {
  let created;
  const result = await syncFinding(finding(), { client: { findOpenByFingerprint: async () => null, create: async (issue) => { created = issue; return { number: 9 }; } } });
  assert.equal(result.status, 'CREATED');
  assert.equal(created.number, undefined);
  assert.match(created.body, /REDACTED/);
});
test('duplicate finding updates the canonical issue', async () => {
  let updated = false;
  const result = await syncFinding(finding({ finding_id: 'F-2' }), { client: { findOpenByFingerprint: async (id) => ({ number: 4, fingerprint: id }), update: async () => { updated = true; } }, state: 'TESTING' });
  assert.equal(result.status, 'UPDATED'); assert.equal(updated, true); assert.equal(result.issue_number, 4);
});
test('same safe fields produce same fingerprint', () => assert.equal(fingerprint(finding()), fingerprint(finding({ finding_id: 'different' }))));
test('product decisions are tracked but explicitly blocked', () => assert.match(buildIssue(finding({ classification: 'REQUIRES_PRODUCT_DECISION' })).body, /blocked pending product decision/));
test('auth failure fails closed', async () => assert.equal((await syncFinding(finding())).status, 'GITHUB_SYNC_BLOCKED_AUTH'));
test('observation-only findings cannot create issues', async () => await assert.rejects(() => syncFinding(finding({ classification: 'OBSERVATION_ONLY' }))));
test('documentation category is labeled', () => assert.ok(buildIssue(finding({ category: 'documentation' })).labels.includes('documentation')));
test('lifecycle state is updated on the same issue', () => assert.match(buildIssue(finding(), 'QA_REVERIFY').body, /QA_REVERIFY/));
test('issue content includes specialist and severity', () => { const issue = buildIssue(finding()); assert.match(issue.body, /frontend/); assert.match(issue.body, /QA2/); });
test('issue content truncates title safely', () => assert.ok(buildIssue(finding({ surface: 'x'.repeat(500) })).title.length <= 240));
