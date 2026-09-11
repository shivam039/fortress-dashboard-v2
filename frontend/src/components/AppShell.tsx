// src/components/AppShell.tsx — Conditional layout: login screen vs app with sidebar
'use client';

import React, { useState } from 'react';
import { usePathname } from 'next/navigation';
import { useAuth } from '@/contexts/AuthContext';
import Sidebar from './Sidebar';

export default function AppShell({ children }: { children: React.ReactNode }) {
  const { isAuthenticated, isLoading } = useAuth();
  const pathname = usePathname();
  // Mobile-only nav toggle — desktop ignores this entirely (the sidebar
  // has no `.open` requirement above the 768px breakpoint).
  const [sidebarOpen, setSidebarOpen] = useState(false);

  // Show loading screen while checking auth
  if (isLoading) {
    return (
      <div className="login-page">
        <div style={{ textAlign: 'center' }}>
          <div className="spinner" style={{ margin: '0 auto 16px' }} />
          <div style={{ color: 'var(--text-muted)', fontSize: '0.88rem' }}>
            Initializing Fortress…
          </div>
        </div>
      </div>
    );
  }

  // Login page — no sidebar
  if (!isAuthenticated || pathname === '/login') {
    return <>{children}</>;
  }

  // Authenticated — show sidebar + content
  return (
    <div className="app-layout">
      <button
        className="mobile-menu-toggle"
        aria-label={sidebarOpen ? 'Close menu' : 'Open menu'}
        aria-expanded={sidebarOpen}
        onClick={() => setSidebarOpen(v => !v)}
      >
        {sidebarOpen ? '✕' : '☰'}
      </button>
      {sidebarOpen && (
        <div className="sidebar-backdrop" onClick={() => setSidebarOpen(false)} />
      )}
      <Sidebar open={sidebarOpen} onNavigate={() => setSidebarOpen(false)} />
      <main className="main-content">{children}</main>
    </div>
  );
}
