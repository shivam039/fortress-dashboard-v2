// src/components/AppShell.tsx — Conditional layout: login screen vs app with sidebar
'use client';

import React from 'react';
import { usePathname } from 'next/navigation';
import { useAuth } from '@/contexts/AuthContext';
import Sidebar from './Sidebar';

export default function AppShell({ children }: { children: React.ReactNode }) {
  const { isAuthenticated, isLoading } = useAuth();
  const pathname = usePathname();

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
      <Sidebar />
      <main className="main-content">{children}</main>
    </div>
  );
}
