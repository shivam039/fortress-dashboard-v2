// src/lib/types.ts — Shared investment data model for REITs, US Investing, MF Lab

export type AssetClass = 'REIT' | 'InvIT' | 'US_STOCK' | 'US_ETF' | 'MF';
export type Currency = 'INR' | 'USD';
export type DataQuality = 'complete' | 'partial' | 'stale';
export type RefreshStatus = 'pending' | 'running' | 'done' | 'error';

export interface ScoreBreakdown {
  performance_consistency?: number;
  alpha?: number;
  downside_protection?: number;
  volatility?: number;
  momentum?: number;
  efficiency?: number;
  yield_score?: number;
  valuation?: number;
  liquidity?: number;
  // REIT/InvIT-specific — is the per-unit distribution growing or
  // shrinking vs 3 years ago (see engine/reit_invits/logic.py).
  distribution_growth_score?: number;
  [key: string]: number | undefined;
}

export interface InvestmentInstrument {
  symbol: string;
  name: string;
  asset_class: AssetClass;
  sub_type?: string;
  sector?: string;
  price: number;
  currency: Currency;
  price_inr?: number;
  returns_1m: number | null;
  returns_3m: number | null;
  returns_6m: number | null;
  returns_1y: number | null;
  volatility_30d: number | null;
  max_drawdown_1y: number | null;
  yield_pct: number | null;
  distribution_frequency?: string;
  // Actual historical per-unit distributions (REIT/InvIT only) — the real
  // payout record, not just a trailing-yield percentage. distributions_1y/
  // 3y are ₹ per unit paid out over that window; distribution_count_1y is
  // how many payouts made up the 1y total (a consistency signal — most
  // REITs/InvITs pay quarterly); distribution_growth_3y_pct compares the
  // most recent 12 months of payouts to the 12 months ending ~3 years ago.
  distributions_1y?: number | null;
  distributions_3y?: number | null;
  distributions_3y_avg?: number | null;
  distribution_count_1y?: number | null;
  distribution_growth_3y_pct?: number | null;
  conviction_score: number | null;
  confidence_score: number | null;
  // Shared label vocabulary used across the app (STRONG BUY / BUY / HOLD /
  // UNDERPERFORMER / AVOID) — populated for REITs/InvITs.
  conviction_label?: string | null;
  conviction_emoji?: string | null;
  // Plain-language note on where the unit trades relative to its NAV
  // (REIT/InvIT only) — "any steam left" is largely a valuation question.
  valuation_note?: string | null;
  score_breakdown: ScoreBreakdown | null;
  risk_flags: string[];
  data_quality: DataQuality;
  score_version: string;
  extras: Record<string, number | string | null>;
  last_updated: string;
}

export interface WatchlistItem {
  id?: number;
  symbol: string;
  name?: string;
  asset_class: string;
  added_at: string;
  notes?: string;
}

export interface PortfolioItem {
  id?: number;
  symbol: string;
  name?: string;
  asset_class: string;
  quantity: number;
  avg_price: number;
  currency: Currency;
  allocation_pct?: number;
  current_price?: number;
  pnl_pct?: number;
  notes?: string;
  updated_at?: string;
}

export interface RefreshJob {
  id: number;
  job_type: string;
  source?: string;
  started_at?: string;
  finished_at?: string;
  status: RefreshStatus;
  error_detail?: string;
  records_refreshed?: number;
}
