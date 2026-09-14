export interface ColumnDefinition {
  label: string;
  description: string;
  format?: string;
  glossaryKey?: string;
}

const definition = (
  label: string,
  description: string,
  format?: string,
  glossaryKey?: string,
): ColumnDefinition => ({ label, description, format, glossaryKey });

/** Canonical, product-wide column copy. Keep this aligned with docs/user/GLOSSARY.md. */
export const columnDefinitions: Record<string, ColumnDefinition> = {
  symbol: definition('Symbol', 'Exchange ticker used to identify the instrument in Fortress.', 'ticker', 'symbol'),
  name: definition('Name', 'Published name of the security, fund, or trust.', 'text'),
  type: definition('Type', 'Instrument or contract classification used by this table.', 'category'),
  sector: definition('Sector', 'Business-sector classification used for grouping and comparison.', 'category', 'sector'),
  convictionscore: definition('Conviction Score', 'Section-specific score showing how strongly available inputs align; compare only within the same model.', '0–100', 'conviction-score'),
  convictionlabel: definition('Conviction Label', 'Plain-language band derived from this fund score.', 'label', 'conviction-score'),
  dataquality: definition('Data Quality', 'Completeness and freshness assessment for inputs behind this result.', 'status', 'data-quality'),
  score: definition('Score', 'Fortress rule-based score summarising the available inputs. It is not a return forecast.', '0–100', 'fortress-score'),
  fortressscore: definition('Fortress Score', 'Fortress rule-based score summarising the available inputs. It is not a probability or return forecast.', '0–100', 'fortress-score'),
  confidence: definition('Confidence', 'Evidence-quality band attached to this result; it is not probability of profit.', 'HIGH / MEDIUM / LOW', 'confidence'),
  signal: definition('Signal', 'Current observation produced by Fortress rules. It is not an order or guaranteed direction.', 'label', 'signal'),
  price: definition('Price', 'Price associated with this row at the table’s stated observation time.', 'currency', 'price'),
  priceusd: definition('Price USD', 'Latest available native US-market price before currency conversion.', 'USD', 'price-usd'),
  priceinr: definition('Price INR', 'Indicative USD price converted to rupees; it is not an executable quote or landed cost.', '₹', 'price-inr'),
  entry: definition('Entry', 'Recorded or suggested opening price for the simulated position.', 'currency', 'entry--exit'),
  current: definition('Current', 'Latest available price used to value this open paper position.', 'currency', 'paper-trade'),
  exit: definition('Exit', 'Recorded closing price for the simulated position.', 'currency', 'entry--exit'),
  stop: definition('Stop', 'Recorded risk threshold for the simulation; it does not guarantee execution at that price.', 'currency', 'paper-trade'),
  target: definition('Target', 'Recorded reference objective for the simulation, not a promised future price.', 'currency', 'paper-trade'),
  pnl: definition('P&L', 'Profit or loss in currency units; open values are unrealised and can change.', 'currency', 'pl--profit-and-loss'),
  realizedpnl: definition('Realized P&L', 'Recorded profit or loss after a simulated position was closed.', 'currency', 'pl--profit-and-loss'),
  return: definition('Return', 'Percentage change from the recorded entry price; open values are unrealised and exclude real execution effects.', '%', 'return'),
  '1yreturn': definition('1Y Return', 'Price or NAV change over the trailing one-year period.', '%', 'return'),
  '3yreturn': definition('3Y Return', 'Annualised price or NAV return over the trailing three-year period when available.', '% p.a.', 'cagr'),
  '5yreturn': definition('5Y Return', 'Annualised price or NAV return over the trailing five-year period when available.', '% p.a.', 'cagr'),
  '1mret': definition('1M Ret', 'Price return over the trailing one-month period.', '%', 'return'),
  '1yret': definition('1Y Ret', 'Price return over the trailing one-year period.', '%', 'return'),
  holding: definition('Holding', 'Elapsed calendar time since entry for an open paper position.', 'days', 'holding-period'),
  status: definition('Status', 'Current workflow or record state; its meaning is specific to this table.', 'label', 'status-labels'),
  regime: definition('Regime', 'Broad market-environment classification used as context, not a prediction.', 'category', 'market-regime'),
  source: definition('Source', 'Origin of the record or signal shown in this row.', 'text'),
  opened: definition('Opened', 'Date and time the simulated position was recorded as open.', 'date/time', 'entry--exit'),
  closed: definition('Closed', 'Date and time the simulated position was recorded as closed.', 'date/time', 'entry--exit'),
  strike: definition('Strike', 'Contract exercise price used to determine intrinsic value and payoff.', '₹', 'strike'),
  moneyness: definition('Moneyness', 'Relationship of strike to spot: ITM, ATM, or OTM. Profitability also depends on premium.', 'category', 'moneyness'),
  ltp: definition('LTP', 'Last traded option premium; it may be stale and is not guaranteed execution.', '₹', 'premium--ltp'),
  oi: definition('OI', 'Outstanding option contracts for this strike and expiry. Higher OI does not imply direction by itself.', 'contracts', 'open-interest--oi'),
  changeoi: definition('Change OI', 'Change in outstanding contracts over the provider’s measured interval; it does not reveal intent with certainty.', 'contracts', 'change-in-oi'),
  volume: definition('Volume', 'Contracts or units traded during the measured session or period; unlike OI, it measures activity.', 'contracts/units', 'volume'),
  iv: definition('IV', 'Market-implied volatility under an options model. Higher IV generally raises premiums, all else equal.', '%', 'implied-volatility--iv'),
  bid: definition('Bid', 'Highest displayed buyer price; execution at this price is not guaranteed.', '₹', 'bid'),
  ask: definition('Ask', 'Lowest displayed seller price; compare it with bid to assess the spread.', '₹', 'ask'),
  spot: definition('Spot', 'Provider’s current or reference underlying price used for moneyness and ATM selection.', '₹', 'spot'),
  capturedat: definition('Captured at', 'Date and time this historical snapshot was stored; values belong to that observation.', 'date/time', 'snapshot'),
  provider: definition('Provider', 'Market-data source that supplied this snapshot.', 'text'),
  freshness: definition('Freshness', 'Whether the inputs meet Fortress’s expected recency at display time.', 'status', 'freshness'),
  snapshotid: definition('Snapshot ID', 'Stable identifier for this persisted historical options observation.', 'identifier', 'snapshot'),
  nav: definition('NAV', 'Per-unit assets minus liabilities for the fund or trust.', '₹', 'nav--net-asset-value'),
  aum: definition('AUM', 'Total value managed by the fund; scale does not guarantee quality.', '₹', 'aum--assets-under-management'),
  expenseratio: definition('Expense Ratio', 'Annual operating cost charged as a percentage of fund assets.', '% p.a.', 'expense-ratio'),
  cagr: definition('CAGR', 'Smoothed annual growth between the stated start and end dates; it hides the return path.', '% p.a.', 'cagr'),
  sharpe: definition('Sharpe', 'Excess return per unit of total variability; interpretation depends on period and assumptions.', 'ratio', 'sharpe-ratio'),
  alpha: definition('Alpha', 'Return beyond the selected benchmark or model expectation; it depends on period and benchmark.', '% or model value', 'alpha'),
  downsidedeviation: definition('Downside Deviation', 'Variability of returns below the selected threshold; lower is not automatically better.', '%', 'sortino-ratio'),
  pe: definition('P/E', 'Market price divided by earnings per share; negative or missing earnings can make it unsuitable.', 'ratio', 'pe-ratio'),
  sortino: definition('Sortino', 'Return relative to downside variability; interpretation depends on period and assumptions.', 'ratio', 'sortino-ratio'),
  yield: definition('Yield', 'Income divided by price or value for the stated period; it is not total return.', '%', 'yield'),
  volatility: definition('Volatility', 'How widely returns vary over the table’s measurement period.', '%', 'volatility'),
  quality: definition('Quality', 'Fortress data/model quality assessment for the available inputs.', 'label', 'data-quality'),
};

export function normalizeColumnKey(value: string): string {
  return value.toLowerCase().replace(/[^a-z0-9]/g, '');
}

export function getColumnDefinition(key: string): ColumnDefinition {
  const normalized = normalizeColumnKey(key);
  return columnDefinitions[normalized] ?? definition(
    key.replace(/_/g, ' '),
    `Value recorded for ${key.replace(/_/g, ' ')} in this Fortress table. Check the surrounding table context for its period and units.`,
  );
}
