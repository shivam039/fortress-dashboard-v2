#!/usr/bin/env node
const { loadCases, validateSuite } = require("./lib");

const root = process.argv[2];
const result = validateSuite(loadCases(root));
if (!result.ok) {
  console.error(result.errors.join("\n"));
  process.exit(1);
}
console.log(`validated ${result.total_cases} eval cases`);
