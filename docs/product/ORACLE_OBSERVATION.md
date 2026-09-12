# Oracle Observation

Status: `OBSERVE1_PASS`

The production pipeline is healthy and has one scheduler owner: GitHub Actions
→ Oracle production API. The corrected manual maturation run `34681554813`
passed, and the scheduled workflow remains enabled. No duplicate cron,
systemd, Render, or second GitHub maturation path was found.

The initial bounded backfill inspected 50 signals and found 0 eligible
signals, with 0 proposed outcomes and 0 writes. This is classified as
`BACKFILL_SCOPE_TOO_SMALL` / `NO_MATURE_SIGNALS_YET`, not a code defect: the
sample is too small to establish a useful evidence distribution and no rows
should be manufactured or made eligible by relaxing the contract.

Continue passive accumulation through the existing daily maturation workflow.
Run EVIDENCE2 after at least 20 matured observations in one decision × horizon
group, or after 30 calendar days of normal accumulation, or sooner only if a
clear operational anomaly appears. Do not tune Oracle before that gate.
