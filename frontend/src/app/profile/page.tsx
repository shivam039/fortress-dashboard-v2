// src/app/profile/page.tsx
'use client';

import React, { useState, useEffect } from 'react';
import { useAuth } from '@/contexts/AuthContext';
import { useToast } from '@/contexts/ToastContext';
import { brokersApi } from '@/lib/api';
import DataTable from '@/components/DataTable';

interface Broker {
  broker_name: string;
  broker_client_id?: string;
  is_active?: boolean;
}

export default function ProfilePage() {
  const { user } = useAuth();
  const { success, error } = useToast();
  const [brokers, setBrokers] = useState<Broker[]>([]);
  const [loading, setLoading] = useState(true);

  const [brokerName, setBrokerName] = useState('Zerodha');
  const [brokerClientId, setBrokerClientId] = useState('');
  const [brokerToken, setBrokerToken] = useState('');
  const [connectLoading, setConnectLoading] = useState(false);

  const loadBrokers = async () => {
    try {
      const data = await brokersApi.list();
      setBrokers(data as unknown as Broker[]);
    } catch {}
    setLoading(false);
  };

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    loadBrokers();
  }, []);

  const handleConnect = async (e: React.FormEvent) => {
    e.preventDefault();
    setConnectLoading(true);
    try {
      await brokersApi.connect({
        broker_name: brokerName,
        broker_client_id: brokerClientId,
        access_token: brokerToken,
      });
      success('Connected successfully!');
      setBrokerClientId('');
      setBrokerToken('');
      loadBrokers();
    } catch (err: unknown) {
      error((err as Error).message);
    }
    setConnectLoading(false);
  };

  const handleDisconnect = async (name: string) => {
    if (!confirm(`Disconnect ${name}?`)) return;
    try {
      await brokersApi.disconnect(name);
      success(`${name} disconnected`);
      loadBrokers();
    } catch (err: unknown) {
      error((err as Error).message);
    }
  };

  const isGuest = user?.username === 'guest_user';

  return (
    <>
      <div className="page-header">
        <h1 className="page-title">👤 Profile & Settings</h1>
        <p className="page-subtitle">Manage your account and broker connections.</p>
      </div>

      <div className="grid-2">
        <div className="section">
          <h3 className="section-title">Account Details</h3>
          <div className="card">
            <DataTable
              data={[
                { Field: 'Username', Value: user?.username || '' },
                { Field: 'Full Name', Value: user?.full_name || 'N/A' },
                { Field: 'Email', Value: user?.email || 'N/A' },
                { Field: 'Phone', Value: user?.phone || 'N/A' },
                { Field: 'Status', Value: user?.account_status || '' },
                { Field: 'Role', Value: user?.role || '' },
              ]}
              columns={['Field', 'Value']}
            />
          </div>
        </div>

        <div className="section">
          <h3 className="section-title">🔑 Broker Connections</h3>
          
          {isGuest && (
            <div className="empty-state" style={{ padding: '24px' }}>
              <p>Guests cannot connect brokers.</p>
            </div>
          )}

          {!isGuest && (
            <>
              <div className="card" style={{ marginBottom: '24px' }}>
                <form onSubmit={handleConnect}>
                  <div className="grid-2" style={{ marginBottom: '16px' }}>
                    <div className="input-group">
                      <label>Broker</label>
                      <select className="input" value={brokerName} onChange={e => setBrokerName(e.target.value)}>
                        <option value="Zerodha">Zerodha</option>
                        <option value="Dhan">Dhan</option>
                      </select>
                    </div>
                    <div className="input-group">
                      <label>Client ID (optional)</label>
                      <input className="input" value={brokerClientId} onChange={e => setBrokerClientId(e.target.value)} />
                    </div>
                  </div>
                  <div className="input-group" style={{ marginBottom: '16px' }}>
                    <label>Access Token</label>
                    <input className="input" type="password" required value={brokerToken} onChange={e => setBrokerToken(e.target.value)} />
                  </div>
                  <button className="btn btn-primary" type="submit" disabled={connectLoading}>
                    {connectLoading ? 'Connecting...' : 'Connect Broker'}
                  </button>
                </form>
              </div>

              {loading ? (
                <div className="loading-overlay">Loading brokers...</div>
              ) : brokers.length > 0 ? (
                <div className="data-table-container">
                  <table className="data-table">
                    <thead>
                      <tr>
                        <th>Broker</th>
                        <th>Client ID</th>
                        <th>Status</th>
                        <th>Action</th>
                      </tr>
                    </thead>
                    <tbody>
                      {brokers.map((b: Broker) => (
                        <tr key={b.broker_name}>
                          <td><strong>{b.broker_name}</strong></td>
                          <td>{b.broker_client_id || '—'}</td>
                          <td>
                            <span className={`badge ${b.is_active ? 'badge-success' : 'badge-danger'}`}>
                              {b.is_active ? 'Active' : 'Inactive'}
                            </span>
                          </td>
                          <td>
                            <button className="btn btn-danger btn-sm" onClick={() => handleDisconnect(b.broker_name)}>
                              Disconnect
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <div className="empty-state" style={{ padding: '24px' }}>
                  <p>No brokers connected.</p>
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </>
  );
}
