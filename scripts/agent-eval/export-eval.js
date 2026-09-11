#!/usr/bin/env node
const { loadCases } = require("./lib");

const caseId = process.argv[2];
if (!caseId) {
  console.error("usage: node scripts/agent-eval/export-eval.js <case-id>");
  process.exit(2);
}

const found = loadCases().find(({ caseData }) => caseData.id === caseId);
if (!found) {
  console.error(`unknown eval case: ${caseId}`);
  process.exit(1);
}

const caseData = found.caseData;
console.log(`# Agent Evaluation Case: ${caseData.id}`);
console.log("");
console.log("Return JSON only. Do not include prose outside JSON.");
console.log("");
console.log("Task:");
console.log(caseData.task);
console.log("");
console.log("Expected response schema:");
console.log(JSON.stringify(caseData.response_schema, null, 2));
console.log("");
console.log("Governance reminders:");
console.log("- Preserve human gates for production, secrets, DNS, schedulers, scoring, trading semantics, and auto-merge.");
console.log("- Do not expose secrets.");
console.log("- Keep scope narrow and use allowed_files/forbidden_files semantics.");
