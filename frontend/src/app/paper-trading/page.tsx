// src/app/paper-trading/page.tsx — FORTRESS-V4 / Blocker C: the smallest
// usable surface for FORTRESS-T2's paper-trading engine. Every trade here
// is PAPER TRADE — a simulation against real price data, never a real
// broker order (see engine/routers/paper_trading.py).
'use client';

import React, { useCallback, useEffect, useState } from 'react';
import { paperTradingApi, type FortressSignalLedgerRow, type PaperPositionValuation, type PaperTrade, type PaperTradeMetrics } from '@/lib/api';
import { useToast } from '@/contexts/ToastContext';
import MetricCard from '@/components/MetricCard';

export default function PaperTradingPage() {
  const { success, error } = useToast();
  const [open, setOpen] = useState<PaperTrade[]>([]);
  const [valuations, setValuations] = useState<PaperPositionValuation[]>([]);
  const [selected, setSelected] = useState<PaperPositionValuation | null>(null);
  const [closed, setClosed] = useState<PaperTrade[]>([]);
  const [metrics, setMetrics] = useState<PaperTradeMetrics | null>(null);
  const [signals, setSignals] = useState<FortressSignalLedgerRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<number | null>(null);

  const loadData = useCallback(() => {
    setLoading(true);
    setLoadError(null);
    Promise.all([
      paperTradingApi.openValuation(),
      paperTradingApi.list('closed'),
      paperTradingApi.metrics(),
      paperTradingApi.signals(20),
    ])
      .then(([o, c, m, s]) => { setValuations(o); setOpen(o); setClosed(c); setMetrics(m); setSignals(s); })
      .catch((err: unknown) => setLoadError((err as Error).message || 'Unknown error'))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    loadData();
  }, [loadData]);

  const handleOpen = async (signalId: number, symbol: string) => {
    setBusyId(signalId);
    try {
      await paperTradingApi.open(signalId);
      success(`PAPER TRADE opened for ${symbol}.`);
      loadData();
    } catch (err: unknown) {
      error(`Could not open paper trade: ${(err as Error).message}`);
    }
    setBusyId(null);
  };

  const handleClose = async (tradeId: number, symbol: string) => {
    if (!window.confirm(`Close the PAPER TRADE for ${symbol}? This is an explicit simulated close.`)) return;
    setBusyId(tradeId);
    try {
      const result = await paperTradingApi.close(tradeId);
      if ('status' in result && result.status === 'not_ready') {
        error(`${symbol}: ${result.reason}`);
      } else {
        success(`PAPER TRADE closed for ${symbol}.`);
        loadData();
      }
    } catch (err: unknown) {
      error(`Could not close paper trade: ${(err as Error).message}`);
    }
    setBusyId(null);
  };

  const openSignalIds = new Set(open.map(t => t.signal_id));

  return (
    <>
      <div className="page-header">
        <h1 className="page-title">📝 Paper Trading</h1>
        <p className="page-subtitle">
          Every position below is a <strong>PAPER TRADE</strong> — a deterministic simulation against real
          price data (FORTRESS-T2). No real broker order is ever placed here.
        </p>
      </div>

      <div className="grid-5" style={{ marginBottom: '24px' }}>
        <MetricCard label="Closed Trades" value={metrics?.trade_count ?? 0} />
        <MetricCard label="Win Rate" value={metrics?.win_rate_pct != null ? `${metrics.win_rate_pct}%` : 'n/a'}
          deltaType={metrics?.win_rate_pct != null ? (metrics.win_rate_pct >= 50 ? 'positive' : 'negative') : 'neutral'} />
        <MetricCard label="Net P&L" value={metrics ? `${metrics.total_net_pnl}` : '0'}
          deltaType={metrics ? (metrics.total_net_pnl >= 0 ? 'positive' : 'negative') : 'neutral'} />
        <MetricCard label="Expectancy" value={metrics?.expectancy ?? 'n/a'} />
        <MetricCard label="Max Drawdown" value={metrics ? `${metrics.max_drawdown}` : '0'} deltaType="negative" />
      </div>

      {loading ? (
        <div className="loading-overlay">Loading paper trading data...</div>
      ) : loadError ? (
        <div className="empty-state">
          <div className="icon">⚠️</div>
          <p>Couldn&apos;t load paper trading data: {loadError}</p>
          <button className="btn btn-secondary" style={{ marginTop: 12 }} onClick={loadData}>Retry</button>
        </div>
      ) : (
        <>
          <div className="section" style={{ marginBottom: '24px' }}>
            <h3 className="section-title">Recent Fortress Signals — open an eligible PAPER TRADE</h3>
            {signals.length === 0 ? (
              <div className="empty-state"><p>No signals recorded yet. Run a scan first.</p></div>
            ) : (
              <div style={{ overflowX: 'auto' }}>
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>Symbol</th><th>Score</th><th>Regime</th><th>Sector</th>
                      <th>Entry</th><th>Stop</th><th>Target</th><th></th>
                    </tr>
                  </thead>
                  <tbody>
                    {signals.map(s => (
                      <tr key={s.id}>
                        <td>{s.symbol}</td>
                        <td>{s.score ?? 'n/a'}</td>
                        <td>{s.market_regime ?? 'n/a'}</td>
                        <td>{s.sector ?? 'n/a'}</td>
                        <td>{s.suggested_entry ?? 'n/a'}</td>
                        <td>{s.stop_loss ?? 'n/a'}</td>
                        <td>{s.target ?? 'n/a'}</td>
                        <td>
                          <button
                            className="btn btn-secondary"
                            disabled={busyId === s.id || openSignalIds.has(s.id)}
                            onClick={() => handleOpen(s.id, s.symbol)}
                          >
                            {openSignalIds.has(s.id) ? 'Open position exists' : busyId === s.id ? 'Opening...' : 'Open PAPER TRADE'}
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          <div className="section" style={{ marginBottom: '24px' }}>
            <h3 className="section-title">Open PAPER Positions ({open.length})</h3>
            {open.length === 0 ? (
              <div className="empty-state"><p>No open paper positions.</p></div>
            ) : (
              <div style={{ overflowX: 'auto' }}>
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>Symbol</th><th>Entry</th><th>Current</th><th>P&amp;L</th><th>Return</th><th>Stop</th><th>Target</th><th>Holding</th><th>Status</th><th></th>
                    </tr>
                  </thead>
                  <tbody>
                    {valuations.map(t => (
                      <tr key={t.trade_id} onClick={() => setSelected(t)} style={{ cursor: 'pointer' }}>
                        <td>{t.symbol}<br /><small>Source: {t.source_type === 'ORACLE_SIGNAL' ? 'Oracle' : t.source_type || 'Manual'}</small></td>
                        <td>{t.entry_price}</td>
                        <td>{t.current_price ?? 'unavailable'}</td>
                        <td>{t.unrealized_pnl == null ? 'unavailable' : t.unrealized_pnl.toFixed(2)}</td>
                        <td>{t.unrealized_return_pct == null ? 'unavailable' : `${t.unrealized_return_pct.toFixed(2)}%`}</td>
                        <td>{t.stop_price ?? 'n/a'}</td>
                        <td>{t.target_price ?? 'n/a'}</td>
                        <td>{t.holding_period_days ?? 'n/a'} days</td>
                        <td><span className="badge">PAPER TRADE</span></td>
                        <td>
                          <button className="btn btn-secondary" disabled={busyId === t.trade_id} onClick={(e) => { e.stopPropagation(); handleClose(t.trade_id, t.symbol); }}>
                            {busyId === t.trade_id ? 'Closing...' : 'Close PAPER TRADE'}
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          <div className="section">
            <h3 className="section-title">Closed PAPER Trades ({closed.length})</h3>
            {closed.length === 0 ? (
              <div className="empty-state"><p>No closed paper trades yet.</p></div>
            ) : (
              <div style={{ overflowX: 'auto' }}>
                <table className="data-table">
                  <thead><tr><th>Symbol</th><th>Source</th><th>Entry</th><th>Exit</th><th>Realized P&amp;L</th><th>Opened</th><th>Closed</th></tr></thead>
                  <tbody>{closed.map(t => (
                    <tr key={t.trade_id}>
                      <td>{t.symbol}</td>
                      <td>{t.source_type === 'ORACLE_SIGNAL' ? 'Oracle' : t.source_type || 'Manual'}</td>
                      <td>{t.entry_price}</td>
                      <td>{t.exit_price ?? 'unavailable'}</td>
                      <td>{t.net_pnl == null ? 'unavailable' : t.net_pnl.toFixed(2)}</td>
                      <td>{t.entry_timestamp}</td>
                      <td>{t.exit_timestamp ?? 'unavailable'}</td>
                    </tr>
                  ))}</tbody>
                </table>
              </div>
            )}
          </div>
          {selected && (
            <div className="modal-backdrop" onClick={() => setSelected(null)}>
              <div className="modal" onClick={e => e.stopPropagation()}>
                <button className="btn btn-secondary" onClick={() => setSelected(null)}>Close</button>
                <h2>{selected.symbol} <span className="badge">PAPER TRADE</span></h2>
                <p>Current: {selected.current_price ?? 'unavailable'} · Entry: {selected.entry_price}</p>
                <p>P&amp;L: {selected.unrealized_pnl ?? 'unavailable'} · Return: {selected.unrealized_return_pct == null ? 'unavailable' : `${selected.unrealized_return_pct.toFixed(2)}%`}</p>
                <p>Stop: {selected.stop_price ?? 'n/a'} · Target: {selected.target_price ?? 'n/a'}</p>
                <p>Holding: {selected.holding_period_days ?? 'n/a'} days · Quantity: {selected.quantity} · Notional: {selected.notional}</p>
                <h3>Fortress Signal</h3>
                <p>{selected.signal ? `Score: ${selected.signal.score ?? 'n/a'} · ${selected.signal.market_regime ?? 'n/a'} · ${selected.signal.sector ?? 'n/a'}` : 'Signal detail unavailable'}</p>
                <p>Trade ID: #{selected.trade_id} · Signal ID: #{selected.signal_id} · Policy: {selected.policy_version ?? 'n/a'}</p>
                <p>Source: {selected.source_type === 'ORACLE_SIGNAL' ? 'Oracle signal' : selected.source_type || 'Manual'} · Original Oracle decision: {selected.oracle_decision ?? 'n/a'} · Version: {selected.oracle_version ?? 'n/a'}</p>
                <button className="btn btn-primary" onClick={() => handleClose(selected.trade_id, selected.symbol)}>Close PAPER TRADE</button>
              </div>
            </div>
          )}
        </>
      )}
    </>
  );
}
