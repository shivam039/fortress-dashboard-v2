// src/app/dashboard/page.tsx — Dashboard overview
'use client';

import React, { useEffect, useState } from 'react';
import { useAuth } from '@/contexts/AuthContext';
import { ordersApi, brokersApi, type OrderStats } from '@/lib/api';
import MetricCard from '@/components/MetricCard';
import DataTable from '@/components/DataTable';

export default function DashboardPage() {
  const { user } = useAuth();
  const [stats, setStats] = useState<OrderStats | null>(null);
  const [brokerCount, setBrokerCount] = useState(0);
  const [recentOrders, setRecentOrders] = useState<Record<string, unknown>[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function load() {
      try {
        const [s, b, o] = await Promise.all([
          ordersApi.stats().catch(() => ({ total: 0, executed: 0, pending: 0, rejected: 0 })),
          brokersApi.list().catch(() => []),
          ordersApi.list({ limit: '8' } as Record<string, string>).catch(() => []),
        ]);
        setStats(s);
        setBrokerCount(Array.isArray(b) ? b.filter((x: Record<string, unknown>) => x.is_active).length : 0);
        setRecentOrders(o);
      } catch {}
      setLoading(false);
    }
    load();
  }, []);

  const isGuest = user?.username === 'guest_user';

  return (
    <>
      <div className="page-header">
        <h1 className="page-title">Dashboard</h1>
        <p className="page-subtitle">Quick overview of your Fortress workspace, broker connectivity, and recent order flow.</p>
      </div>

      <div className="grid-4" style={{ marginBottom: '32px' }}>
        {loading ? (
          <>
            {[1,2,3,4].map(i => <div key={i} className="metric-card skeleton" style={{ height: 100 }} />)}
          </>
        ) : (
          <>
            <MetricCard
              label={isGuest ? 'Account Type' : 'Active Brokers'}
              value={isGuest ? 'Guest' : brokerCount}
            />
            <MetricCard label="Total Orders" value={stats?.total ?? 0} />
            <MetricCard label="Pending Orders" value={stats?.pending ?? 0} />
            <MetricCard label="Account Status" value={user?.account_status || 'Active'} />
          </>
        )}
      </div>

      <div className="grid-2">
        <div className="section">
          <h3 className="section-title">👤 Profile Snapshot</h3>
          <div className="card">
            <DataTable
              data={[
                { Field: 'Full Name', Value: user?.full_name || 'N/A' },
                { Field: 'Email', Value: user?.email || 'N/A' },
                { Field: 'Phone', Value: user?.phone || 'N/A' },
                { Field: 'Last Login', Value: user?.last_login_at || 'N/A' },
              ]}
              columns={['Field', 'Value']}
            />
          </div>
        </div>

        <div className="section">
          <h3 className="section-title">📋 Recent Orders</h3>
          <DataTable
            data={recentOrders}
            columns={['symbol', 'order_type', 'quantity', 'status', 'broker_name', 'created_at']}
            emptyMessage="No orders recorded yet."
            maxRows={8}
          />
        </div>
      </div>
    </>
  );
}
