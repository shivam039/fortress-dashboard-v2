#!/usr/bin/env node
const path = require("path");
const { VALID_PROVIDERS, extractJson, loadCases, scoreCase, writeJson } = require("./lib");

const [caseId, provider, resultPath] = process.argv.slice(2);
if (!caseId || !provider || !resultPath) {
  console.error("usage: node scripts/agent-eval/import-result.js <case-id> <provider> <result-file>");
  process.exit(2);
}
if (!VALID_PROVIDERS.has(provider)) {
  console.error(`unknown provider: ${provider}`);
  process.exit(1);
}

const found = loadCases().find(({ caseData }) => caseData.id === caseId);
if (!found) {
  console.error(`unknown eval case: ${caseId}`);
  process.exit(1);
}

const text = require("fs").readFileSync(path.resolve(resultPath), "utf8");
const parsed = extractJson(text);
const scored = scoreCase(found.caseData, parsed);
const output = {
  provider,
  case_id: caseId,
  imported_at: new Date().toISOString(),
  result: parsed,
  score: scored,
};
const outPath = path.join("agent-evals", "provider-results", `${caseId}.${provider}.json`);
writeJson(outPath, output);
console.log(JSON.stringify(scored, null, 2));
if (scored.status === "FAIL") process.exit(1);
