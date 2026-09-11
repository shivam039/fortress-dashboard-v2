#!/usr/bin/env node
'use strict';

/*
 * PR body template (AGENT1B Phase 22). Never includes secrets or a full
 * generated prompt — only the structured summary fields.
 */

function buildPrBody({
  issue, agent, provider, model, inputBudget, outputBudget, risk,
  allowedFiles = [], changedFiles = [], testsSummary = '(not run)',
  reviewVerdict = '(not reviewed)', docsRequired = false, docsFiles = [],
  productionImpact = 'NONE',
}) {
  const lines = [];
  lines.push('## AGENT TASK');
  lines.push(`Issue: ${issue != null ? `#${issue}` : '(none)'}`);
  lines.push(`Agent: ${agent}`);
  lines.push(`Provider: ${provider}`);
  lines.push(`Model: ${model}`);
  lines.push(`Budget: input=${inputBudget} output=${outputBudget}`);
  lines.push(`Risk: ${risk}`);
  lines.push('');
  lines.push('## SCOPE');
  lines.push(`Allowed: ${JSON.stringify(allowedFiles)}`);
  lines.push(`Changed: ${JSON.stringify(changedFiles)}`);
  lines.push('');
  lines.push('## TESTS');
  lines.push(testsSummary);
  lines.push('');
  lines.push('## REVIEW');
  lines.push(reviewVerdict);
  lines.push('');
  lines.push('## DOCS');
  lines.push(docsRequired ? `Required — updated: ${JSON.stringify(docsFiles)}` : 'Not required');
  lines.push('');
  lines.push('## PRODUCTION IMPACT');
  lines.push(productionImpact === 'NONE' ? 'NONE' : `HUMAN APPROVAL REQUIRED — ${productionImpact}`);
  lines.push('');
  lines.push('---');
  lines.push('_Opened by the AGENT1B pipeline. Requires human review and merge — no auto-merge is configured._');
  return lines.join('\n');
}

if (require.main === module) {
  console.log(buildPrBody(JSON.parse(process.argv[2] || '{}')));
}
module.exports = { buildPrBody };
