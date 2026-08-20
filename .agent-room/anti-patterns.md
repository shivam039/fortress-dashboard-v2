# Anti-Patterns Log — app

Negative knowledge: things that have already gone wrong here, so nobody
(human or agent) repeats them. One avoided bug is worth more than one
polished example — keep entries short and concrete.

Append a new entry every time:
- a bug slips through and you find the root cause,
- an approach seemed reasonable but turned out wrong,
- a fix gets reverted because it only patched a symptom.

## Format

```
### YYYY-MM-DD — short title

**What happened:** one or two sentences.
**Root cause:** the actual cause, not the symptom.
**Avoid:** the concrete rule that would have prevented it.
```

<!-- Entries go below this line, newest first. -->

### 2026-07-10 — Flattening scores to 50.0 in zero-variance universes or single stock scans

**What happened:** Single stock scans or lists of stocks with identical raw values got their final conviction scores flattened to a constant `50.0`.
**Root cause:** Universe-relative normalization divided by zero and defaulted to `50.0` for all categories.
**Avoid:** When the range of values is zero (`max_v == min_v`), fall back to returning the absolute values (clamped to `[0, 100]`) rather than a constant average indicator.

### 2026-07-10 — Test Suite database hangs and safe_session_state dictionary access

**What happened:** Running frontend tests caused the test suite to hang indefinitely or throw AttributeErrors.
**Root cause:**
1. The Streamlit app initialized Neon connection checking on startup, which blocked on connection attempts.
2. The `AppTest` wrapper's safe session state does not support the dict `.get()` method.
**Avoid:**
1. Force `FORTRESS_DB_BACKEND=sqlite` in the test environment configuration to bypass remote DB connection attempts.
2. Do not use `.get()` on Streamlit's `AppTest.session_state` object; use square bracket index access or `getattr()`.
