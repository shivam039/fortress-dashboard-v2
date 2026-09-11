const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const test = require("node:test");

const {
  SUITE_VERSION,
  extractJson,
  loadCases,
  scoreCase,
  staticResultFor,
  summarize,
  validateCase,
  validateSuite,
  writeJson,
} = require("../../scripts/agent-eval/lib");

test("eval fixtures parse and include suite version", () => {
  const cases = loadCases();
  assert.ok(cases.length >= 18);
  assert.ok(cases.every(({ caseData }) => caseData.suite_version === SUITE_VERSION));
});

test("duplicate eval ID is rejected", () => {
  const cases = loadCases().slice(0, 2);
  cases[1] = { ...cases[1], caseData: { ...cases[1].caseData, id: cases[0].caseData.id } };
  const result = validateSuite(cases);
  assert.equal(result.ok, false);
  assert.match(result.errors.join("\n"), /duplicate id/);
});

test("unknown category is rejected", () => {
  const found = loadCases()[0].caseData;
  const errors = validateCase({ ...found, category: "unknown" });
  assert.ok(errors.some((error) => error.includes("unknown category")));
});

test("missing expected result is rejected", () => {
  const found = loadCases()[0].caseData;
  const copy = { ...found };
  delete copy.expected;
  const errors = validateCase(copy);
  assert.ok(errors.some((error) => error.includes("expected")));
});

test("static Coordinator scoring works", () => {
  const found = loadCases().find(({ caseData }) => caseData.id === "coordinator-backend-001");
  const scored = scoreCase(found.caseData, staticResultFor(found.caseData));
  assert.equal(scored.status, "PASS");
  assert.equal(scored.score, 95);
});

test("human-gate bypass is hard FAIL", () => {
  const found = loadCases().find(({ caseData }) => caseData.id === "security-production-gate-001");
  const scored = scoreCase(found.caseData, {
    selected_agent: "infra",
    requires_human_gate: false,
    production_access: false,
  });
  assert.equal(scored.status, "FAIL");
  assert.ok(scored.hard_failures.includes("human_gate_bypass"));
});

test("secret exposure is hard FAIL", () => {
  const found = loadCases().find(({ caseData }) => caseData.id === "security-prompt-injection-001");
  const scored = scoreCase(found.caseData, {
    production_access: false,
    requires_human_gate: true,
    secret_exposure: true,
  });
  assert.equal(scored.status, "FAIL");
  assert.ok(scored.hard_failures.includes("secret_exposure"));
});

test("scope violation is hard FAIL", () => {
  const found = loadCases().find(({ caseData }) => caseData.id === "backend-contract-001");
  const scored = scoreCase(found.caseData, {
    selected_agent: "backend",
    changed_files: ["frontend/src/app/paper-trading/page.tsx"],
  });
  assert.equal(scored.status, "FAIL");
  assert.ok(scored.hard_failures.includes("forbidden_file"));
});

test("budget violation is detected", () => {
  const found = loadCases().find(({ caseData }) => caseData.id === "token-budget-excessive-001");
  const scored = scoreCase(found.caseData, staticResultFor(found.caseData));
  assert.equal(scored.status, "PASS");
  assert.equal(scored.dimensions.token_discipline, 100);
});

test("prompt injection fixture rejects unsafe instructions", () => {
  const found = loadCases().find(({ caseData }) => caseData.id === "security-prompt-injection-001");
  const scored = scoreCase(found.caseData, staticResultFor(found.caseData));
  assert.equal(scored.status, "PASS");
});

test("Reviewer eval scoring works", () => {
  const found = loadCases().find(({ caseData }) => caseData.id === "reviewer-forbidden-file-001");
  const scored = scoreCase(found.caseData, {
    verdict: "MERGEABLE",
    scope_compliance: "PASS",
    changed_files: ["engine/stock_scanner/logic.py"],
  });
  assert.equal(scored.status, "FAIL");
  assert.ok(scored.hard_failures.includes("forbidden_file"));
});

test("Docs impact scoring works", () => {
  const found = loadCases().find(({ caseData }) => caseData.id === "docs-current-reality-001");
  const scored = scoreCase(found.caseData, staticResultFor(found.caseData));
  assert.equal(scored.status, "PASS");
});

test("provider result import parser accepts JSON embedded in text", () => {
  const parsed = extractJson('Here is JSON:\n{"selected_agent":"backend","requires_human_gate":false}');
  assert.equal(parsed.selected_agent, "backend");
});

test("unknown provider result can be represented as a hard failure", () => {
  const found = loadCases()[0];
  const scored = scoreCase(found.caseData, { hard_failures: { provider_required: true } });
  assert.equal(scored.status, "FAIL");
  assert.ok(scored.hard_failures.includes("provider_required"));
});

test("summary calculation is deterministic", () => {
  const results = loadCases().map(({ caseData }) => scoreCase(caseData, staticResultFor(caseData)));
  const first = summarize(results);
  const second = summarize(results);
  assert.deepEqual(first, second);
  assert.equal(first.suite_version, SUITE_VERSION);
});

test("provider execution is optional for static suite", () => {
  const result = validateSuite(loadCases());
  assert.equal(result.ok, true);
});

test("writeJson writes importable provider result records", () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "agent-eval-"));
  const file = path.join(dir, "result.json");
  writeJson(file, { suite_version: SUITE_VERSION, provider: "codex" });
  assert.equal(JSON.parse(fs.readFileSync(file, "utf8")).provider, "codex");
});

test("AGENT2 remains decoupled from AGENT1B implementation internals", () => {
  const evaluator = fs.readFileSync(
    path.join(__dirname, "../../scripts/agent-eval/lib.js"),
    "utf8",
  );
  assert.doesNotMatch(evaluator, /require\([^)]*scripts\/agent\//);
  assert.doesNotMatch(evaluator, /orchestrate-task|provider adapter/i);
});
