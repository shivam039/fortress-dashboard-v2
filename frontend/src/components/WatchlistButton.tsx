// src/components/WatchlistButton.tsx — Optimistic star toggle for watchlist
'use client';

import React, { useCallback, useEffect, useState } from 'react';
import { investmentsApi } from '@/lib/api';
import { useToast } from '@/contexts/ToastContext';
import type { AssetClass } from '@/lib/types';

interface WatchlistButtonProps {
  symbol: string;
  name?: string;
  assetClass: AssetClass | string;
  size?: 'sm' | 'md';
}

// Simple in-memory set for the session
const _watchlistSet = new Set<string>();

export default function WatchlistButton({ symbol, name, assetClass, size = 'sm' }: WatchlistButtonProps) {
  const { success, error } = useToast();
  const [inWatchlist, setInWatchlist] = useState(() => _watchlistSet.has(symbol));
  const [loading, setLoading] = useState(false);

  // Sync from API on first render
  useEffect(() => {
    investmentsApi.watchlist.list()
      .then(items => {
        items.forEach(i => _watchlistSet.add(i.symbol));
        setInWatchlist(_watchlistSet.has(symbol));
      })
      .catch(() => {});
  }, [symbol]);

  const toggle = useCallback(async (e: React.MouseEvent) => {
    e.stopPropagation();
    if (loading) return;

    const next = !inWatchlist;
    // Optimistic update
    setInWatchlist(next);
    if (next) _watchlistSet.add(symbol);
    else _watchlistSet.delete(symbol);

    setLoading(true);
    try {
      if (next) {
        await investmentsApi.watchlist.add({ symbol, name, asset_class: assetClass });
        success(`${symbol} added to watchlist`);
      } else {
        await investmentsApi.watchlist.remove(symbol);
        success(`${symbol} removed from watchlist`);
      }
    } catch (err: unknown) {
      // Revert on error
      setInWatchlist(!next);
      if (next) _watchlistSet.delete(symbol);
      else _watchlistSet.add(symbol);
      error(`Failed: ${(err as Error).message}`);
    } finally {
      setLoading(false);
    }
  }, [symbol, name, assetClass, inWatchlist, loading, success, error]);

  const sz = size === 'sm' ? '1.1rem' : '1.4rem';

  return (
    <button
      id={`watchlist-btn-${symbol}`}
      onClick={toggle}
      disabled={loading}
      title={inWatchlist ? `Remove ${symbol} from watchlist` : `Add ${symbol} to watchlist`}
      style={{
        background: 'none', border: 'none', cursor: loading ? 'default' : 'pointer',
        fontSize: sz, lineHeight: 1,
        opacity: loading ? 0.5 : 1,
        transition: 'transform 0.15s ease, opacity 0.15s ease',
        transform: inWatchlist ? 'scale(1.15)' : 'scale(1)',
        padding: '2px',
      }}
    >
      {inWatchlist ? '⭐' : '☆'}
    </button>
  );
}
