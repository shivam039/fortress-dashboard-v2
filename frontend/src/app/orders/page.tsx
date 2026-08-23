// src/app/orders/page.tsx
'use client';

import React, { useState, useEffect, useCallback } from 'react';
import { ordersApi, brokersApi, type OrderStats } from '@/lib/api';
import { useToast } from '@/contexts/ToastContext';
import DataTable from '@/components/DataTable';
import MetricCard from '@/components/MetricCard';

const ORDER_TYPES = ['Buy', 'Sell'];
const ORDER_STATUSES = ['Pending', 'Executed', 'Rejected', 'Cancelled'];

export default function OrdersPage() {
  const { success, error } = useToast();
  const [orders, setOrders] = useState<Record<string, unknown>[]>([]);
  const [stats, setStats] = useState<OrderStats | null>(null);
  const [brokers, setBrokers] = useState<string[]>(['All', 'Zerodha', 'Dhan']);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);

  const [status, setStatus] = useState('All');
  const [broker, setBroker] = useState('All');
  const [dateFrom, setDateFrom] = useState('');
  const [dateTo, setDateTo] = useState('');

  const [showForm, setShowForm] = useState(false);
  const [formSymbol, setFormSymbol] = useState('');
  const [formStockName, setFormStockName] = useState('');
  const [formOrderType, setFormOrderType] = useState('Buy');
  const [formQuantity, setFormQuantity] = useState('1');
  const [formPrice, setFormPrice] = useState('');
  const [formStatus, setFormStatus] = useState('Pending');
  const [formBroker, setFormBroker] = useState('Zerodha');
  const [formNotes, setFormNotes] = useState('');
  const [creating, setCreating] = useState(false);

  const loadData = useCallback(() => {
    setLoading(true);
    setLoadError(null);
    Promise.all([
      ordersApi.list({ status, broker, date_from: dateFrom, date_to: dateTo }),
      ordersApi.stats(),
    ])
      .then(([o, s]) => {
        setOrders(o);
        setStats(s);
      })
      .catch((err: unknown) => {
        setLoadError((err as Error).message || 'Unknown error');
      })
      .finally(() => setLoading(false));
  }, [status, broker, dateFrom, dateTo]);

  useEffect(() => {
    brokersApi.list().then(b => {
      if (Array.isArray(b)) {
        const active = b.filter(x => x.is_active).map(x => x.broker_name as string);
        setBrokers(['All', ...new Set([...active, 'Zerodha', 'Dhan'])]);
      }
    }).catch(() => {});
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    loadData();
  }, [loadData]);

  const handleCreateOrder = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!formSymbol.trim()) {
      error('Symbol is required.');
      return;
    }
    setCreating(true);
    try {
      await ordersApi.create({
        symbol: formSymbol.trim().toUpperCase(),
        stock_name: formStockName.trim() || formSymbol.trim().toUpperCase(),
        order_type: formOrderType,
        quantity: Number(formQuantity) || 1,
        price: Number(formPrice) || 0,
        status: formStatus,
        broker_name: formBroker,
        notes: formNotes.trim(),
      });
      success(`Order for ${formSymbol.trim().toUpperCase()} logged.`);
      setFormSymbol('');
      setFormStockName('');
      setFormQuantity('1');
      setFormPrice('');
      setFormNotes('');
      setShowForm(false);
      loadData();
    } catch (err: unknown) {
      error((err as Error).message || 'Failed to create order');
    }
    setCreating(false);
  };

  return (
    <>
      <div className="page-header">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: 12 }}>
          <div>
            <h1 className="page-title">📋 Orders</h1>
            <p className="page-subtitle">Track and manage your order history across all connected brokers.</p>
          </div>
          <button className="btn btn-primary" onClick={() => setShowForm(v => !v)}>
            {showForm ? 'Cancel' : '+ New Order'}
          </button>
        </div>
      </div>

      {showForm && (
        <div className="card" style={{ marginBottom: '24px' }}>
          <h3 className="section-title">Log a New Order</h3>
          <form onSubmit={handleCreateOrder}>
            <div className="grid-4" style={{ marginBottom: '16px' }}>
              <div className="input-group">
                <label>Symbol *</label>
                <input className="input" required value={formSymbol} onChange={e => setFormSymbol(e.target.value)} placeholder="e.g. RELIANCE" />
              </div>
              <div className="input-group">
                <label>Stock Name</label>
                <input className="input" value={formStockName} onChange={e => setFormStockName(e.target.value)} placeholder="Optional" />
              </div>
              <div className="input-group">
                <label>Order Type</label>
                <select className="input" value={formOrderType} onChange={e => setFormOrderType(e.target.value)}>
                  {ORDER_TYPES.map(t => <option key={t} value={t}>{t}</option>)}
                </select>
              </div>
              <div className="input-group">
                <label>Status</label>
                <select className="input" value={formStatus} onChange={e => setFormStatus(e.target.value)}>
                  {ORDER_STATUSES.map(s => <option key={s} value={s}>{s}</option>)}
                </select>
              </div>
            </div>
            <div className="grid-4" style={{ marginBottom: '16px' }}>
              <div className="input-group">
                <label>Quantity</label>
                <input className="input" type="number" min="0" step="any" value={formQuantity} onChange={e => setFormQuantity(e.target.value)} />
              </div>
              <div className="input-group">
                <label>Price</label>
                <input className="input" type="number" min="0" step="any" value={formPrice} onChange={e => setFormPrice(e.target.value)} placeholder="0" />
              </div>
              <div className="input-group">
                <label>Broker</label>
                <select className="input" value={formBroker} onChange={e => setFormBroker(e.target.value)}>
                  {brokers.filter(b => b !== 'All').map(b => <option key={b} value={b}>{b}</option>)}
                </select>
              </div>
              <div className="input-group">
                <label>Notes</label>
                <input className="input" value={formNotes} onChange={e => setFormNotes(e.target.value)} placeholder="Optional" />
              </div>
            </div>
            <button className="btn btn-primary" type="submit" disabled={creating}>
              {creating ? 'Logging...' : 'Log Order'}
            </button>
          </form>
        </div>
      )}

      <div className="grid-5" style={{ marginBottom: '24px' }}>
        <MetricCard label="Total Orders" value={stats?.total ?? 0} />
        <MetricCard label="Executed" value={stats?.executed ?? 0} deltaType="positive" />
        <MetricCard label="Pending" value={stats?.pending ?? 0} deltaType="neutral" />
        <MetricCard label="Rejected" value={stats?.rejected ?? 0} deltaType="negative" />
        <MetricCard label="Cancelled" value={stats?.cancelled ?? 0} deltaType="neutral" />
      </div>

      <div className="card" style={{ marginBottom: '24px' }}>
        <div className="grid-4">
          <div className="input-group">
            <label>Status</label>
            <select className="input" value={status} onChange={e => setStatus(e.target.value)}>
              {['All', 'Pending', 'Executed', 'Rejected', 'Cancelled'].map(s => <option key={s} value={s}>{s}</option>)}
            </select>
          </div>
          <div className="input-group">
            <label>Broker</label>
            <select className="input" value={broker} onChange={e => setBroker(e.target.value)}>
              {brokers.map(b => <option key={b} value={b}>{b}</option>)}
            </select>
          </div>
          <div className="input-group">
            <label>Date From</label>
            <input className="input" type="date" value={dateFrom} onChange={e => setDateFrom(e.target.value)} />
          </div>
          <div className="input-group">
            <label>Date To</label>
            <input className="input" type="date" value={dateTo} onChange={e => setDateTo(e.target.value)} />
          </div>
        </div>
      </div>

      <div className="section">
        {loading ? (
          <div className="loading-overlay">Loading orders...</div>
        ) : loadError ? (
          <div className="empty-state">
            <div className="icon">⚠️</div>
            <p>Couldn&apos;t load orders: {loadError}</p>
            <button className="btn btn-secondary" style={{ marginTop: 12 }} onClick={loadData}>
              Retry
            </button>
          </div>
        ) : (
          <DataTable data={orders} emptyMessage="No orders found. Log your first order above." />
        )}
      </div>
    </>
  );
}
