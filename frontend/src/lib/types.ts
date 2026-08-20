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
  conviction_score: number | null;
  confidence_score: number | null;
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
