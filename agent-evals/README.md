# Agent Evaluation Harness

AGENT2 is a static and provider-optional evaluation system for Fortress's
agent framework. It answers whether agent routing, scope, safety, reviewer
behavior, docs impact, production gates, and token discipline are improving
or regressing over time.

Static mode is deterministic and free. It validates fixtures and scores the
expected structured behavior without calling Claude, Codex, Grok, or any other
provider.

## Run Static Evals

```bash
node scripts/agent-eval/validate-case.js
node scripts/agent-eval/run-eval.js --mode=static --out=agent-evals/expected/static-summary.json
```

## Manual Provider Comparison

Export the same case prompt for any provider:

```bash
node scripts/agent-eval/export-eval.js coordinator-backend-001
```

Run that prompt manually in Codex, Claude, or Grok, save the model output, then
import and score it:

```bash
node scripts/agent-eval/import-result.js coordinator-backend-001 codex result.txt
```

Raw provider outputs should not be committed. Store only compact scored
summaries when useful.

## Case Format

Cases are JSON files under `agent-evals/cases/<category>/`.

Required fields:

- `id`
- `suite_version`
- `category`
- `task`
- `expected`
- `scoring`
- `tags`

Scoring dimensions are `correctness`, `safety`, `scope_discipline`,
`governance`, and `token_discipline`, each on a 0-4 scale in fixtures.
