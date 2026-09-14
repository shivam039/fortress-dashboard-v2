# Product walkthrough status

**Audit baseline:** `094407a7fa5e764dac5a98a08622cc840e2999f0`

**Status: PARTIAL.** The current production build, route definitions, safe API
contract fixtures, loading/empty/error handling, and existing browser journeys
were audited. The browser binary required to execute Playwright was unavailable
in this environment (the approved download endpoints returned HTTP 403), so no
claim below is upgraded to a real live-provider walkthrough. No production
mutation was performed.

## Completion matrix

| Section | Visible | Navigable | Functional | Desktop | Mobile | Docs | Glossary | Tour | Proven |
|---|---|---|---|---|---|---|---|---|---|
| Login / session | PASS | PASS | PARTIAL | NOT_PROVEN | NOT_PROVEN | PASS | PASS | N/A | NOT_PROVEN |
| Dashboard | PASS | PASS | PARTIAL | NOT_PROVEN | NOT_PROVEN | PASS | PASS | PASS | NOT_PROVEN |
| Stock Screener | PASS | PASS | PARTIAL | NOT_PROVEN | NOT_PROVEN | PASS | PASS | PASS | NOT_PROVEN |
| Scan History | PASS | PASS | PARTIAL | NOT_PROVEN | NOT_PROVEN | PASS | PASS | PASS | NOT_PROVEN |
| Oracle Decision (contextual) | PASS | PARTIAL | PARTIAL | NOT_PROVEN | NOT_PROVEN | PASS | PASS | PASS | NOT_PROVEN |
| Paper Trading | PASS | PASS | PARTIAL | NOT_PROVEN | NOT_PROVEN | PASS | PASS | PASS | NOT_PROVEN |
| Mutual Fund Lab | PASS | PASS | PARTIAL | NOT_PROVEN | NOT_PROVEN | PASS | PASS | PASS | NOT_PROVEN |
| REITs & InvITs | PASS | PASS | PARTIAL | NOT_PROVEN | NOT_PROVEN | PASS | PASS | PASS | NOT_PROVEN |
| US Investing / US ETFs | PASS | PASS | PARTIAL | NOT_PROVEN | NOT_PROVEN | PASS | PASS | PASS | NOT_PROVEN |
| Commodities | PASS | PASS | PARTIAL | NOT_PROVEN | NOT_PROVEN | PASS | PASS | PARTIAL | NOT_PROVEN |
| Options | PASS | PASS | PARTIAL | NOT_PROVEN | NOT_PROVEN | PASS | PASS | PASS | NOT_PROVEN |
| Orders | PASS | PASS | PARTIAL | NOT_PROVEN | NOT_PROVEN | PASS | PASS | PASS | NOT_PROVEN |
| Picks Tracker | PASS | PASS | PARTIAL | NOT_PROVEN | NOT_PROVEN | PASS | PASS | PASS | NOT_PROVEN |
| Profile / broker settings | PASS | PASS | PARTIAL | NOT_PROVEN | NOT_PROVEN | PASS | PASS | PARTIAL | NOT_PROVEN |
| In-product tour / Help | PASS | PASS | PASS | NOT_PROVEN | NOT_PROVEN | PASS | N/A | PASS | PARTIAL |

“Functional: PARTIAL” means the production TypeScript/build contract and safe
mock-based test specification cover the UI, but data loads/actions were not
proved against production services in this audit. Tour functionality is proved
by static checks/build and dedicated Playwright coverage, but the browser test
could not launch locally.

## Canonical terminology

| Use | Avoid conflating it with | Decision |
|---|---|---|
| Stock Screener | Stock Scanner | Use the navigation name; “scan” remains the action/run noun. |
| Mutual Fund Lab | MF / MF scanner | Spell out on first mention; MF is acceptable in compact labels. |
| REITs & InvITs | REIT/INVIT | Preserve the capitalization used in navigation. |
| Paper Trade / Paper Position | Order / real trade | Always retain the PAPER label. |
| Open PAPER Position | Open Trade | “Position” is the lifecycle state; “trade” names the simulation record. |
| Fortress Score | Oracle confidence | Score is rule-based 0–100; confidence qualifies evidence. |
| Signal | Oracle Decision | A signal is an input/observation; a decision is a separate persisted layer. |
| Scan History | History | Use the complete navigation label. |
| COMPLETE | Successful investment | It only describes completion of a stored scan run. |

## Route and control audit

Fourteen user-visible routes were inventoried: `/`, `/login`, `/dashboard`,
`/screener`, `/mf-lab`, `/reit-invits`, `/us-investing`, `/orders`, `/picks`,
`/paper-trading`, `/commodities`, `/options`, `/history`, and `/profile`.
Twelve authenticated sidebar destinations are wired to matching page headings.
Oracle and research evidence have no first-class route; they are embedded in
recorded signal/history flows.

The safe walkthrough specification checks 12 navigation links plus Login/Guest,
mobile-menu open/close, two Scan History section tabs and run/back controls,
Paper Trading discovery, screener search/scan/result paths, options chain and
Strategy Lab controls, paper-trade empty/detail paths, accessibility checks,
and the tour controls. Across the existing and added Playwright specifications,
56 distinct meaningful click/control assertions were identified: 48 read-only
or fixture-safe PASS assertions, 0 confirmed FAIL controls, and 8 mutation or
expensive controls classified NOT_SAFE_TO_TEST live (Run Scan, four Mutual Fund
job variants as one control family, REIT refresh, US refresh, Commodity refresh,
create/close paper trade, create order, create pick, and connect/disconnect
broker are grouped by workflow rather than every button instance).

## Journeys and second pass

| Journey | Evidence | Result |
|---|---|---|
| Login/Guest → Dashboard → all 12 navigation destinations | Existing navigation spec and route/page cross-check | PARTIAL — browser unavailable locally |
| Scan History → Stocks → run → structured historical screener → back | Existing scan-history/responsive specs and implementation | PARTIAL |
| Scan History → Mutual Funds → run → labelled generic historical result | Existing history fixture/unit coverage and implementation | PARTIAL |
| Screener → result → score/evidence → Oracle → Options context | Component/route/API cross-check; safe tests cover parts | PARTIAL |
| Oracle signal → Paper Trading → open/closed lifecycle | Read-only route/detail verified in code/tests; mutation blocked | NOT_PROVEN live |
| REIT/InvIT → search/filter/detail/watchlist/Options | Route/control/API cross-check; write blocked | PARTIAL |
| US Investing → search/filter/detail/US ETF/Options | Route/control/API cross-check | PARTIAL |
| Options → expiry/chain/history → preset/explicit legs/payoff | Existing option spec and implementation | PARTIAL |

A documentation-only second pass matched every imperative in QUICK_START and
USER_GUIDE to a current visible control or route. Instructions for mutating or
expensive controls are explicitly cautionary and marked unproved. Result:
**PARTIAL**, because browser execution and live data could not be repeated.

## Error, empty, loading, and mobile truth

Loading components exist for the principal data pages. Critical fetch errors on
Screener, History, MF Lab, Paper Trading, and other tested pages offer distinct
messages/retry controls; fixture tests inject representative API errors. Empty
history, open-position, option-history, and table states are distinguished from
failures. Authentication expiry returns the user to the unauthenticated shell.

Mobile navigation has a labelled menu button, backdrop, close-on-navigation,
and an existing Pixel 7 Playwright scenario. Wide tables can still require
horizontal scrolling. The tour uses a centered responsive dialog and does not
require its sidebar target to be visible. Mobile remains **NOT_PROVEN in this
run** because Chromium could not be installed.

## Adversarial findings

1. **No top-level Oracle or Research route.** Documentation now describes them
   as contextual rather than inventing navigation.
2. **No Indian ETF, watchlist, or portfolio screen.** US ETFs and row-level
   watchlist actions exist; the guide states the limitation.
3. **Mutating controls sit beside browsing controls.** Scan, refresh, job,
   paper-trade, order, pick, and broker-setting actions were not clicked live.
4. **Historical generic results remain table-shaped.** Stocks have the richer
   structured replay; non-stock histories are labelled but not specialized to
   every possible scan schema.
5. **Options range ambiguity.** Existing UI reports theoretical risk separately;
   documentation explicitly distinguishes it from sampled payoff points.
6. **Operational language leaks into user UI.** “Job Controls,” “runtime
   capability truth,” “provider diagnostics,” and “Legacy Strategy Scanner” are
   accurate but advanced and can confuse beginners.
7. **Tour target disappearance.** The tour queries targets defensively and keeps
   the dialog usable when a target is absent or hidden on mobile.
8. **Raw backend-shaped fields.** Options snapshot history still exposes names
   such as `captured_at` and `snapshot_id`; this is documented as a UX follow-up.

## Bugs, dead controls, and follow-ups

No confirmed dead internal route or no-handler control was found. The current
code maps every sidebar link to a route, and link destinations found in asset
pages resolve to Options. Browser execution is still required before calling
that a live PASS.

Genuine follow-up stories:

- Run the complete fixture Playwright suite on desktop/mobile in CI with the
  pinned browser, then perform a credential-safe staging walkthrough with real
  read-only providers.
- Give Mutual Fund and future scan types section-specific historical renderers
  instead of the generic result table when their schemas stabilize.
- Replace raw options snapshot/provider field names with beginner labels and a
  recovery action for provider unavailability.
- Decide whether a first-class Watchlist/Portfolio and Research landing page are
  product requirements; do not document them until they exist.
- Separate operational refresh/job controls from ordinary research browsing or
  add role/safety explanations.

## Production impact

User-help-only: six documentation files, an on-demand local-only product tour,
and contextual explanations. The tour does not auto-run or call an API. No
scoring, methodology, portfolio, scheduler, infrastructure, secret, or market
workflow changed.
