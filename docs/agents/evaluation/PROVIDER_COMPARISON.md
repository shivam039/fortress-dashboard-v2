# Provider Comparison

AGENT2 supports practical provider comparison through manual imports.

Use the same exported case for each provider:

```bash
node scripts/agent-eval/export-eval.js coordinator-backend-001
```

Then import each response:

```bash
node scripts/agent-eval/import-result.js coordinator-backend-001 codex codex-result.txt
node scripts/agent-eval/import-result.js coordinator-backend-001 anthropic claude-result.txt
node scripts/agent-eval/import-result.js coordinator-backend-001 xai grok-result.txt
```

Comparison format:

| Agent | Provider | Model | Score | Safety | Scope | Cost/Usage |
|---|---|---|---:|---:|---:|---|

Do not claim one provider is universally better from a tiny sample. Use results
to choose practical role/provider mappings, such as stronger reasoning for
Research or lower-cost capability for Docs.

When token metadata is available, record input tokens and output tokens and
compare quality score per 1k tokens. Do not estimate token counts when they
are unavailable.
