# AGENT5A-QWEN: `qwen_web` experiment

Status: `KEEP_EXPERIMENTAL` / opt-in only

`qwen_web` is an experimental adapter for an unofficial, self-hosted Qwengate
gateway. Qwengate presents an OpenAI-compatible endpoint backed by a logged-in
`chat.qwen.ai` browser session. It is not an official Qwen API integration and
is not suitable as production infrastructure or as a financial-decision
provider.

## Current implementation

The adapter is isolated in `scripts/agent/providers.js` and reuses the existing
provider abstraction. It supports:

- explicit provider name `qwen_web`;
- private base URL and gateway token from `QWEN_WEB_BASE_URL` and
  `QWEN_WEB_GATEWAY_TOKEN`;
- bounded 120-second requests and one caller-controlled retry;
- OpenAI-compatible chat completion response validation;
- `AVAILABLE`, `MISCONFIGURED`, `SESSION_EXPIRED`, `UNREACHABLE`, and
  `GATEWAY_ERROR` health/failure states;
- `TOKEN_USAGE=NOT_AVAILABLE` when the gateway provides no usage data.

The example configuration keeps it `MANUAL_EXPORT`. It is never the default,
never silently selected, and never switches to a paid provider. The existing
manual import path remains the fallback.

## Security model

The Qwen browser cookie belongs only inside the private Qwengate deployment.
It must never enter Fortress configuration, Git, GitHub Actions, logs, PRs, or
artifacts. Fortress sees only the gateway URL and a gateway token. Do not put
the endpoint on the public internet without authentication and private-network
controls. Do not send production secrets, Oracle production credentials, or
financial-decision tasks to this adapter.

Model output remains untrusted. It cannot execute shell commands, modify
secrets, change scope/governance, merge PRs, deploy, or override
`production_access=false`, human review, token ceilings, or auto-merge policy.
The existing result validation, scope, test, eval, reviewer, docs, and human
merge gates remain authoritative.

## Deployment recommendation

`LOCAL_FIRST`. Do not run Qwengate on the production Oracle VM in AGENT5A and
do not run browser-session automation directly in GitHub Actions. A separate
VM may be evaluated later with explicit network isolation, resource limits,
authentication, and restart isolation. Oracle co-location is not recommended
until measured: Chromium adds memory/CPU pressure and couples gateway restarts
to production workloads.

## Threat model

| Risk | Level | Mitigation |
| --- | --- | --- |
| Browser cookie/session compromise | HIGH | Cookie stays in private Qwengate; separate experiment account; no Fortress storage |
| Qwen UI/API or anti-bot change | HIGH | Keep experimental/manual; health check; bounded timeout; manual fallback |
| Gateway outage/session expiry/rate limiting | MEDIUM | Explicit health states; one retry maximum; no provider switch |
| Unexpected model/tool behavior | HIGH | Treat output as untrusted; no direct shell/secret/production access; existing gates |
| GitHub runner/network exposure | HIGH | Do not host browser session in Actions; private token-gated endpoint only |
| Account suspension or policy change | MEDIUM | Separate account; no production dependency |

## Live experiment

Live generation is not run by normal CI and was not run for this change because
no user-authenticated Qwen session is available. A user may run a harmless,
non-production docs or test task locally with:

```sh
export QWEN_WEB_BASE_URL=http://127.0.0.1:20128
export QWEN_WEB_GATEWAY_TOKEN='provided-out-of-band'
```

The gateway must be authenticated and private. Do not paste the token into a
task, config file, command transcript, PR, or log. Record only status, latency,
HTTP result, retry count, scope/test/eval/reviewer results, and manual
intervention. Record token usage as `NOT_AVAILABLE` unless the gateway returns
validated usage metadata.

## Promotion criteria

Before any AGENT5B proposal, run 10–20 harmless tasks (docs, unit tests, tiny
backend/frontend changes, QA/reviewer and prompt-injection cases) and record
real measurements. Promotion requires at least 90% gateway request success,
80% harmless-task completion, zero secret leaks, zero production-safety or
scope-bypass events, and zero auto-merge paths. A small sample must not be
used to claim Qwen is better than another provider.

## Disable / fallback

Remove the `qwen_web` provider entry or set its mode to `DISABLED`; unset the
two environment variables; or leave it in `MANUAL_EXPORT`. Fortress continues
through the existing manual-export flow. No Qwengate service is required for
normal development.

## Upstream review

The upstream project reviewed for this experiment is
[`youssefvdel/qwengate`](https://github.com/youssefvdel/qwengate). Its public
description and API documentation describe an OpenAI-compatible gateway,
Chromium-based authentication, streaming, tool calling, and a self-hosted
deployment model. These claims are not treated as a security or reliability
guarantee; live compatibility remains unverified until an authenticated local
session is tested.

AGENT5B is deferred. Oracle Decision integration is explicitly out of scope.
