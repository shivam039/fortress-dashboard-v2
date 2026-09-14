// src/components/Sidebar.tsx — Collapsible navigation sidebar
'use client';

import React from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useAuth } from '@/contexts/AuthContext';
import SystemStatus from './SystemStatus';

const NAV_ITEMS = [
  { href: '/dashboard', icon: '🏠', label: 'Dashboard', tour: 'dashboard' },
  { href: '/screener', icon: '📊', label: 'Stock Screener', tour: 'screener' },
  { href: '/mf-lab', icon: '📈', label: 'MF Lab', tour: 'mf-lab' },
  { href: '/reit-invits', icon: '🏢', label: 'REITs & InvITs', tour: 'reit-invits' },
  { href: '/us-investing', icon: '🇺🇸', label: 'US Investing', tour: 'us-investing' },
  { href: '/orders', icon: '📋', label: 'Orders', tour: 'orders' },
  { href: '/picks', icon: '🎯', label: 'Picks Tracker', tour: 'picks' },
  { href: '/paper-trading', icon: '📝', label: 'Paper Trading', tour: 'paper-trading' },
  { href: '/commodities', icon: '🌍', label: 'Commodities', tour: 'commodities' },
  { href: '/options', icon: '⚡', label: 'Options', tour: 'options' },
  { href: '/history', icon: '🕐', label: 'Scan History', tour: 'history' },
  { href: '/profile', icon: '👤', label: 'Profile', tour: 'profile' },
];

interface SidebarProps {
  // Mobile only — on desktop the sidebar (`.sidebar`, no `.open` needed)
  // is always visible; see the `@media (max-width: 768px)` rule in
  // globals.css that positions it off-screen until `.open` is added.
  open?: boolean;
  onNavigate?: () => void;
}

export default function Sidebar({ open = false, onNavigate }: SidebarProps) {
  const pathname = usePathname();
  const { user, logout } = useAuth();

  return (
    <aside className={`sidebar ${open ? 'open' : ''}`}>
      <div className="sidebar-header">
        <span style={{ fontSize: '1.5rem' }}>🏹</span>
        <span className="sidebar-logo">Fortress</span>
      </div>

      <SystemStatus />

      <nav className="sidebar-nav" aria-label="Primary">
        {NAV_ITEMS.map((item) => (
          <Link
            key={item.href}
            href={item.href}
            className={`nav-item ${pathname === item.href ? 'active' : ''}`}
            data-tour={item.tour}
            onClick={onNavigate}
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
