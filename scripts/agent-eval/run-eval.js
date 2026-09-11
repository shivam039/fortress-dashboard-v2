#!/usr/bin/env node
const path = require("path");
const {
  loadCases,
  scoreCase,
  staticResultFor,
  summarize,
  writeJson,
} = require("./lib");

const args = process.argv.slice(2);
const mode = (args.find((arg) => arg.startsWith("--mode=")) || "--mode=static")
  .split("=")[1]
  .toUpperCase();
const outArg = args.find((arg) => arg.startsWith("--out="));

if (mode !== "STATIC") {
  console.error("provider mode is advisory/manual in AGENT2; use import-result.js for provider outputs");
  process.exit(2);
}

const cases = loadCases();
const results = cases.map(({ caseData }) => scoreCase(caseData, staticResultFor(caseData)));
const summary = summarize(results, { mode: "STATIC" });

if (outArg) {
  writeJson(path.resolve(outArg.split("=")[1]), summary);
}

console.log(JSON.stringify(summary, null, 2));
if (summary.status === "FAIL") process.exit(1);
