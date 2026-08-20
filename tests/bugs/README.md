# Bug Regression Tests

Place focused regression tests for confirmed bugs in this directory. Keep test
names descriptive, for example `test_conviction_bug_<short_description>.py`, and
include a short comment in each test explaining the bug scenario it protects.

Temporary debugging files should not live in the repository root. If a debug
reproduction becomes valuable, convert it into a deterministic pytest regression
here; otherwise keep it untracked or remove it.
