export interface HelpDefinition {
  label: string;
  fullName?: string;
  shortDescription: string;
  format?: string;
  glossaryKey: string;
  aliases?: readonly string[];
  category: 'Fortress' | 'Financial' | 'Status' | 'Data';
}

const define = (definition: HelpDefinition): HelpDefinition => definition;

/** The single source of truth used by table headers, metric cards and Glossary. */
export const helpDefinitions = {
  fortressScore: define({ label: 'Fortress Score', shortDescription: 'A 0–100 rule-based summary of how strongly the available inputs align with Fortress criteria. It is not a probability or return forecast.', format: '0–100 score', glossaryKey: 'fortress-score', aliases: ['score', 'ai score', 'conviction score', 'avg conviction'], category: 'Fortress' }),
  signal: define({ label: 'Signal', shortDescription: 'A recorded observation produced by analysis rules. It can inform an Oracle decision or paper trade, but is not an order or recommendation.', glossaryKey: 'signal', category: 'Fortress' }),
  oracleConfidence: define({ label: 'Oracle Confidence', shortDescription: 'How complete and consistent the evidence supporting an Oracle decision is. It is not the probability that a trade will profit.', glossaryKey: 'oracle-confidence', aliases: ['confidence'], category: 'Fortress' }),
  evidenceConfidence: define({ label: 'Evidence Confidence', shortDescription: 'A qualification of how much historical evidence is available and how reliable it is for the stated observation.', glossaryKey: 'evidence-confidence', category: 'Fortress' }),
  scanStatus: define({ label: 'Scan Status', shortDescription: 'The processing state of a stored scan run. Completion describes the workflow, not investment success.', glossaryKey: 'scan-status', aliases: ['status'], category: 'Status' }),
  price: define({ label: 'Price', shortDescription: 'The instrument price in the currency shown by this table. In historical scan results it is the stored value at scan time, not a live quote.', glossaryKey: 'price', aliases: ['price usd', 'price inr', 'current', 'underlying'], category: 'Data' }),
  entryPrice: define({ label: 'Entry', shortDescription: 'The simulated price recorded when a paper position was opened; fees and slippage are included only when explicitly stated.', glossaryKey: 'entry-price', aliases: ['entry'], category: 'Financial' }),
  exitPrice: define({ label: 'Exit', shortDescription: 'The simulated price recorded when a paper position was closed.', glossaryKey: 'exit-price', aliases: ['exit'], category: 'Financial' }),
  pnl: define({ label: 'P&L', fullName: 'Profit and Loss', shortDescription: 'The gain or loss from the displayed entry to current or exit value. Check the table label for whether it is unrealized or realized and which currency applies.', glossaryKey: 'p-and-l', aliases: ['p&l', 'realized p&l', 'expiry p/l', 'net p&l', 'avg p&l'], category: 'Financial' }),
  return: define({ label: 'Return', shortDescription: 'Percentage change over the period named in the column. It is not benchmark-relative unless explicitly labelled that way.', format: '%', glossaryKey: 'return', aliases: ['return', '1m ret', '1y ret'], category: 'Financial' }),
  hitRate: define({ label: 'Hit Rate', shortDescription: 'The percentage of evaluated observations that met the defined success condition. It does not show the size of wins or losses.', format: '%', glossaryKey: 'hit-rate', aliases: ['hit rate', 'win rate'], category: 'Fortress' }),
  expectancy: define({ label: 'Expectancy', shortDescription: 'Average outcome per evaluated observation, combining how often wins and losses occur with their average sizes. It is historical, not a forecast.', glossaryKey: 'expectancy', category: 'Financial' }),
  drawdown: define({ label: 'Maximum Drawdown', shortDescription: 'The largest observed peak-to-trough decline over the evaluated period. It describes historical downside, not a guaranteed worst case.', glossaryKey: 'drawdown', aliases: ['drawdown', 'max drawdown'], category: 'Financial' }),
  rsi: define({ label: 'RSI', fullName: 'Relative Strength Index', shortDescription: 'Measures recent price momentum on a 0–100 scale. Higher values mean stronger recent upward momentum, not an automatic buy or sell.', format: '0–100', glossaryKey: 'rsi', category: 'Financial' }),
  adx: define({ label: 'ADX', fullName: 'Average Directional Index', shortDescription: 'Estimates trend strength on a 0–100 scale, regardless of whether price is moving up or down.', format: '0–100', glossaryKey: 'adx', category: 'Financial' }),
  atr: define({ label: 'ATR', fullName: 'Average True Range', shortDescription: 'Measures recent price movement size in price units. A larger ATR means greater movement, not direction.', glossaryKey: 'atr', category: 'Financial' }),
  nav: define({ label: 'NAV', fullName: 'Net Asset Value', shortDescription: 'Per-unit value of a fund or trust based on its assets minus liabilities. Market price may trade above or below NAV.', glossaryKey: 'nav', category: 'Financial' }),
  aum: define({ label: 'AUM', fullName: 'Assets Under Management', shortDescription: 'The total market value managed by the fund, in the unit shown. Size alone does not establish quality.', glossaryKey: 'aum', category: 'Financial' }),
  expenseRatio: define({ label: 'Expense Ratio', shortDescription: 'Annual fund operating costs expressed as a percentage of average assets. It reduces investor returns.', format: '% per year', glossaryKey: 'expense-ratio', category: 'Financial' }),
  sharpe: define({ label: 'Sharpe Ratio', shortDescription: 'Historical excess return per unit of total volatility. Compare values calculated over the same period and assumptions.', format: 'ratio', glossaryKey: 'sharpe', aliases: ['sharpe'], category: 'Financial' }),
  sortino: define({ label: 'Sortino Ratio', shortDescription: 'Historical excess return per unit of downside volatility. It does not predict future risk-adjusted return.', format: 'ratio', glossaryKey: 'sortino', aliases: ['sortino'], category: 'Financial' }),
  beta: define({ label: 'Beta', shortDescription: 'Sensitivity of historical returns to a benchmark. A beta above 1 indicates larger past moves on average, not guaranteed future movement.', format: 'ratio', glossaryKey: 'beta', category: 'Financial' }),
  alpha: define({ label: 'Alpha', shortDescription: 'Return above or below a benchmark-adjusted expectation over the measured period. Results depend on benchmark and methodology.', format: '%', glossaryKey: 'alpha', category: 'Financial' }),
  yield: define({ label: 'Yield', shortDescription: 'Distribution income expressed as a percentage of price or NAV for the stated period. It can change and is not guaranteed.', format: '%', glossaryKey: 'yield', aliases: ['yield', 'distribution yield'], category: 'Financial' }),
  volatility: define({ label: 'Volatility', shortDescription: 'How widely historical returns varied over the measured period. It measures dispersion, not direction.', format: '% when shown', glossaryKey: 'volatility', category: 'Financial' }),
  oi: define({ label: 'OI', fullName: 'Open Interest', shortDescription: 'The number of outstanding option contracts at this strike and expiry. Participation does not by itself indicate price direction.', format: 'contracts', glossaryKey: 'open-interest', aliases: ['oi', 'open interest', 'change oi', 'changeoi'], category: 'Financial' }),
  iv: define({ label: 'IV', fullName: 'Implied Volatility', shortDescription: 'The annualized volatility implied by an option price. It reflects market pricing assumptions, not a direction forecast.', format: '% annualized', glossaryKey: 'implied-volatility', aliases: ['iv'], category: 'Financial' }),
  strike: define({ label: 'Strike', shortDescription: 'The fixed underlying price at which an option may be exercised, subject to the contract terms.', glossaryKey: 'strike', category: 'Financial' }),
  premium: define({ label: 'Premium / LTP', shortDescription: 'The displayed option-contract price, not the underlying spot price. LTP is the most recently traded price and can differ from an executable quote.', glossaryKey: 'premium', aliases: ['premium', 'ltp'], category: 'Financial' }),
  moneyness: define({ label: 'Moneyness', shortDescription: 'Whether a call or put strike is in, at, or out of the money relative to current spot. It does not include premium paid or predict profit.', glossaryKey: 'moneyness', category: 'Financial' }),
  bid: define({ label: 'Bid', shortDescription: 'Highest displayed price a buyer currently offers for the option. It may change before an order can execute.', glossaryKey: 'bid', category: 'Financial' }),
  ask: define({ label: 'Ask', shortDescription: 'Lowest displayed price a seller currently requests for the option. The difference from bid is the spread.', glossaryKey: 'ask', category: 'Financial' }),
  delta: define({ label: 'Delta', shortDescription: 'Estimated option-price change for a one-unit underlying move, with other inputs held constant. It changes as market conditions change.', format: 'ratio', glossaryKey: 'delta', category: 'Financial' }),
  theta: define({ label: 'Theta', shortDescription: 'Estimated option-value change from one day passing, with other inputs held constant. It is model-based, not guaranteed.', format: 'price units/day', glossaryKey: 'theta', category: 'Financial' }),
  gamma: define({ label: 'Gamma', shortDescription: 'Estimated change in delta for a one-unit underlying move, with other inputs held constant.', glossaryKey: 'gamma', category: 'Financial' }),
  vega: define({ label: 'Vega', shortDescription: 'Estimated option-price sensitivity to a one-percentage-point change in implied volatility.', glossaryKey: 'vega', category: 'Financial' }),
  volume: define({ label: 'Volume', shortDescription: 'Contracts or units traded during the reported session. It measures activity, not outstanding positions or direction.', glossaryKey: 'volume', category: 'Financial' }),
  pe: define({ label: 'P/E', fullName: 'Price-to-Earnings Ratio', shortDescription: 'Market price divided by earnings per share for the stated basis. It is not meaningful when earnings are negative.', format: 'ratio', glossaryKey: 'pe-ratio', aliases: ['p/e'], category: 'Financial' }),
} as const;

export type HelpKey = keyof typeof helpDefinitions;

const normalize = (value: string): string => value.toLowerCase().replace(/[_()%₹$]/g, ' ').replace(/\s+/g, ' ').trim();

export function findHelpKey(label: string): HelpKey | undefined {
  const normalized = normalize(label);
  return (Object.keys(helpDefinitions) as HelpKey[]).find((key) => {
    const item = helpDefinitions[key];
    return [item.label, item.fullName, ...(item.aliases ?? [])]
      .filter(Boolean).some(candidate => normalize(candidate as string) === normalized);
  });
}
