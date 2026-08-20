// src/app/layout.tsx — Root layout with AuthProvider and Sidebar
import type { Metadata } from 'next';
import './globals.css';
import { AuthProvider } from '@/contexts/AuthContext';
import { ToastProvider } from '@/contexts/ToastContext';
import { ErrorBoundary } from '@/components/ErrorBoundary';
import AppShell from '@/components/AppShell';

export const metadata: Metadata = {
  title: 'Fortress 95 Pro — Quantitative Trading Dashboard',
  description: 'Professional quantitative stock screener, mutual fund analysis, and trading execution engine.',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <ErrorBoundary>
          <ToastProvider>
            <AuthProvider>
              <AppShell>{children}</AppShell>
            </AuthProvider>
          </ToastProvider>
        </ErrorBoundary>
      </body>
    </html>
  );
}
