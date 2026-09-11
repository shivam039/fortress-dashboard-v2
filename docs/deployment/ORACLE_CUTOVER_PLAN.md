# Oracle Production Cutover Plan

This is a future plan only. Do not execute it during `FORTRESS-INFRA1`.

Production currently remains:

- Vercel frontend
- Render backend
- Neon production database
- GitHub Actions scheduled automation

## Preconditions

Oracle staging must already be deployed, HTTPS-working, DB-isolated,
health-checked, Playwright-passing, and safe-scan verified.

## Future Cutover Steps

1. Freeze production deployments.

   Stop merging deployment-affecting changes while the cutover is active.

2. Verify Oracle staging one final time.

   Check `/api/health`, login, dashboard, scan history, paper trading reads,
   and Nifty 50 safe-scan evidence.

3. Prepare Oracle production configuration.

   Create production-grade Oracle env values separately from staging. Do not
   reuse staging secrets.

4. Configure production database access.

   Use the intended production Neon database or production migration target.
   Confirm credentials, SSL, backups, and least privilege.

5. Prepare scheduler ownership.

   Do not disable Render-era scheduler workflows until Oracle production is
   ready to accept exactly one scheduler owner.

6. Switch Vercel production backend URL.

   Update the production frontend environment only after Oracle production
   health is passing.

7. Run health and Playwright.

   Verify `/api/health`, login, dashboard, stock screener, scan history, paper
   trading reads, and navigation.

8. Observe.

   Watch container status, memory, disk, Caddy logs, backend logs, and scan RSS
   logs through at least one scheduled cycle.

9. Keep Render available for rollback.

   Do not delete Render immediately. Keep the last known-good Render backend
   and env available until Oracle production has proven stable.

10. Retire Render later.

   Only after the user confirms production stability should Render deployment
   and production scheduler references be retired.

## Rollback Principle

Rollback should switch Vercel production backend URL back to Render and restore
the previous scheduler owner. Database rollback must be planned separately
based on the production data migration approach used in the cutover story.
