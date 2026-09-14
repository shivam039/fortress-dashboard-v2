# Fortress site map

This hierarchy is generated from the authenticated navigation in the current
application, not from planned features.

```text
Fortress
├── /login                  Login, sign-up, or guest session
├── /dashboard              Account snapshot and recent orders
├── /screener               Stock Screener
│   ├── Symbol search
│   ├── Universe scan and results
│   ├── Fortress Score and historical evidence
│   └── Embedded Oracle Decision / link to Options
├── /mf-lab                 Mutual Fund Lab
├── /reit-invits            REIT and InvIT discovery/detail
├── /us-investing           US stock and US ETF discovery/detail
├── /orders                 User-recorded order log
├── /picks                  Picks Tracker
├── /paper-trading          Eligible signals, open positions, closed trades
├── /commodities            Commodity comparison and decision cards
├── /options                Chain, snapshot comparison, Strategy Lab
├── /history                Section-first Scan History
│   ├── Stocks              Structured historical screener
│   └── Other recorded scan types (only when data exists)
├── /profile                Account and broker connections
└── Help (lower-right)      Take / restart the in-product tour
```

## Route inventory

| Section | Purpose | Entry point | Important controls | Data/API | Related sections | Mobile |
|---|---|---|---|---|---|---|
| Login | Start an authenticated or guest session | Root redirect | Login, Sign Up, Guest | Authentication API | Dashboard | Direct |
| Dashboard | Overview of account and recent orders | Primary navigation | Read tables | Profile/order APIs | Orders, Profile | Menu |
| Stock Screener | Search one stock or analyse a universe | Primary navigation | Search, universe, provider, scan, result/detail links | Universe, scan-job, sector, evidence APIs | History, Options, Oracle, Paper Trading | Menu |
| Mutual Fund Lab | Compare available fund analysis | Primary navigation | Category/subcategory, table/grid, row detail, job controls | MF analysis/job APIs | History | Menu |
| REITs & InvITs | Discover and compare listed trusts | Primary navigation | Search, type, sort, row detail, watchlist, refresh | REIT/InvIT and investment APIs | Options | Menu |
| US Investing | Discover US stocks and ETFs | Primary navigation | Search, sector, sort, INR display, detail, watchlist, refresh | US investing and investment APIs | Options | Menu |
| Orders | Maintain an order record | Primary navigation | Add order, status/broker filters | Orders/broker APIs | Dashboard, Profile | Menu |
| Picks Tracker | Maintain monitored picks and outcomes | Primary navigation | New pick, outcome filter | Picks API | Screener, evidence | Menu |
| Paper Trading | Simulate eligible Fortress signals | Primary navigation | Open/close paper position, detail | Paper-trading API | Oracle, evidence | Menu |
| Commodities | Compare commodity data and descriptive decisions | Primary navigation | Refresh, cards/table views | Commodities API | — | Menu |
| Options | Inspect chain and calculate expiry payoff | Primary navigation or asset detail | Underlying, expiry, OI threshold, presets, legs, payoff | Options APIs | Screener, REIT/InvIT, US Investing | Menu |
| Scan History | Replay persisted scans by section | Primary navigation | Section tabs, run cards, back/retry | History/context APIs | Screener, MF Lab, evidence | Menu |
| Profile | Review account and broker connections | Primary navigation | Connect/disconnect broker | Profile/broker APIs | Orders | Menu |

There is no separate top-level Oracle, Research, Indian ETF, or portfolio route
in the current navigation. Oracle and research evidence are contextual within
recorded signal/history experiences. US ETFs appear in US Investing. Watchlist
controls exist on supported asset rows, but there is no first-class watchlist
or portfolio screen in the current sidebar.
