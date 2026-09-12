# QWEN-DOGFOOD1

This is a controlled evaluation of the existing `qwen_web` provider, not a
provider feature or product change. `scripts/agent/qwen-dogfood1.js` creates
three bounded task contracts (frontend, backend, and QA), checks provider
readiness, and validates returned results. It never falls back to another
provider and never repairs Qwen output before scoring.

Each task is isolated, has a one-cycle repair limit, and is scored on six
five-point gates: correctness, tests, scope, reviewer quality, autonomy, and
repository understanding. Transport failures are recorded separately from
model failures. A result with production access, auto-merge, unsafe scope, or
credential exposure is a hard failure.

The CLI is intentionally observational and safe:

```sh
node scripts/agent/qwen-dogfood1.js
```

It emits a plan and provider readiness status. When Qwen is unavailable, the
experiment is `DOGFOOD_BLOCKED_PROVIDER`; no task is rescued, retried through
another provider, merged, or deployed. Experimental fixes remain on the
dedicated `experiment/qwen-dogfood1` branch until a human separately decides
whether to promote one.
