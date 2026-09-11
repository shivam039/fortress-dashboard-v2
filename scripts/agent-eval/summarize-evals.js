#!/usr/bin/env node
const fs = require("fs");
const path = require("path");
const { readJson, summarize } = require("./lib");

const files = process.argv.slice(2);
if (files.length === 0) {
  console.error("usage: node scripts/agent-eval/summarize-evals.js <score-json>...");
  process.exit(2);
}

const results = files.flatMap((file) => {
  const parsed = readJson(path.resolve(file));
  if (Array.isArray(parsed.results)) return parsed.results;
  if (parsed.score) return [parsed.score];
  return [parsed];
});
console.log(JSON.stringify(summarize(results), null, 2));
