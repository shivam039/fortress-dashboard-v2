#!/usr/bin/env node
const path = require("path");
const { extractJson, loadCases, readJson, scoreCase } = require("./lib");

const [caseId, resultPath] = process.argv.slice(2);
if (!caseId || !resultPath) {
  console.error("usage: node scripts/agent-eval/score-eval.js <case-id> <result-file>");
  process.exit(2);
}

const found = loadCases().find(({ caseData }) => caseData.id === caseId);
if (!found) {
  console.error(`unknown eval case: ${caseId}`);
  process.exit(1);
}

const absoluteResultPath = path.resolve(resultPath);
const text = require("fs").readFileSync(absoluteResultPath, "utf8");
const result = resultPath.endsWith(".json") ? readJson(absoluteResultPath) : extractJson(text);
console.log(JSON.stringify(scoreCase(found.caseData, result), null, 2));
