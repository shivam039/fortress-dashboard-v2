// src/app/orders/page.tsx
'use client';

import React, { useState, useEffect } from 'react';
import { ordersApi, brokersApi, type OrderStats } from '@/lib/api';
import DataTable from '@/components/DataTable';
import MetricCard from '@/components/MetricCard';

export default function OrdersPage() {
  const [orders, setOrders] = useState<Record<string, unknown>[]>([]);
  const [stats, setStats] = useState<OrderStats | null>(null);
  const [brokers, setBrokers] = useState<string[]>(['All', 'Zerodha', 'Dhan']);
  const [loading, setLoading] = useState(true);

  const [status, setStatus] = useState('All');
  const [broker, setBroker] = useState('All');
  const [dateFrom, setDateFrom] = useState('');
  const [dateTo, setDateTo] = useState('');

  const loadData = async () => {
    setLoading(true);
    try {
      const [o, s] = await Promise.all([
        ordersApi.list({ status, broker, date_from: dateFrom, date_to: dateTo }),
        ordersApi.stats(),
      ]);
      setOrders(o);
      setStats(s);
    } catch {}
    setLoading(false);
  };

  useEffect(() => {
    brokersApi.list().then(b => {
      if (Array.isArray(b)) {
        const active = b.filter(x => x.is_active).map(x => x.broker_name as string);
        setBrokers(['All', ...new Set([...active, 'Zerodha', 'Dhan'])]);
      }
    }).catch(() => {});
  }, []);

  useEffect(() => {
    loadData();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status, broker, dateFrom, dateTo]);

  return (
    <>
      <div className="page-header">
        <h1 className="page-title">📋 Orders</h1>
        <p className="page-subtitle">Track and manage your order history across all connected brokers.</p>
      </div>

      <div className="grid-4" style={{ marginBottom: '24px' }}>
        <MetricCard label="Total Orders" value={stats?.total ?? 0} />
        <MetricCard label="Executed" value={stats?.executed ?? 0} deltaType="positive" />
        <MetricCard label="Pending" value={stats?.pending ?? 0} deltaType="neutral" />
        <MetricCard label="Rejected" value={stats?.rejected ?? 0} deltaType="negative" />
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
        ) : (
          <DataTable data={orders} emptyMessage="No orders found." />
        )}
      </div>
    </>
  );
}
