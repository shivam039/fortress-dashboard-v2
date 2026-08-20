// src/components/Sidebar.tsx — Collapsible navigation sidebar
'use client';

import React from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useAuth } from '@/contexts/AuthContext';
import SystemStatus from './SystemStatus';

const NAV_ITEMS = [
  { href: '/dashboard', icon: '🏠', label: 'Dashboard' },
  { href: '/screener', icon: '📊', label: 'Stock Screener' },
  { href: '/mf-lab', icon: '📈', label: 'MF Lab' },
  { href: '/reit-invits', icon: '🏢', label: 'REITs & InvITs' },
  { href: '/us-investing', icon: '🇺🇸', label: 'US Investing' },
  { href: '/orders', icon: '📋', label: 'Orders' },
  { href: '/commodities', icon: '🌍', label: 'Commodities' },
  { href: '/options', icon: '⚡', label: 'Options' },
  { href: '/history', icon: '🕐', label: 'Scan History' },
  { href: '/profile', icon: '👤', label: 'Profile' },
];

export default function Sidebar() {
  const pathname = usePathname();
  const { user, logout } = useAuth();

  return (
    <aside className="sidebar">
      <div className="sidebar-header">
        <span style={{ fontSize: '1.5rem' }}>🏹</span>
        <span className="sidebar-logo">Fortress</span>
      </div>

      <SystemStatus />

      <nav className="sidebar-nav">
        {NAV_ITEMS.map((item) => (
          <Link
            key={item.href}
            href={item.href}
            className={`nav-item ${pathname === item.href ? 'active' : ''}`}
          >
            <span className="nav-icon">{item.icon}</span>
            <span>{item.label}</span>
          </Link>
        ))}
      </nav>

      <div className="sidebar-footer">
        {user && (
          <div style={{ padding: '8px 14px', marginBottom: '8px' }}>
            <div style={{ fontSize: '0.82rem', fontWeight: 600, color: 'var(--text-primary)' }}>
              {user.full_name || user.username}
            </div>
            <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>
              {user.role === 'guest' ? 'Guest Session' : user.email || user.username}
            </div>
          </div>
        )}
        <button className="btn btn-secondary btn-block btn-sm" onClick={logout}>
          🚪 Logout
        </button>
      </div>
    </aside>
  );
}
