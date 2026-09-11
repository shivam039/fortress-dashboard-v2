// src/lib/scan-history.ts — FORTRESS-UX1: pure section/filter logic for the
// Scan History page. Kept side-effect-free (no fetch, no DOM) so it can be
// unit-tested the same way lib/scan-state.ts is (tests/scan.test.mjs).
import type { ScanHistoryEntry } from '@/lib/api';

export const STOCK_SECTION = 'STOCK';
const STORAGE_KEY = 'fortress.scanHistory.section';

export interface SectionMeta {
  scanType: string;
  label: string;
  icon: string;
  loadingMessage: string;
  emptyMessage: string;
  errorMessage: string;
}

// Every scan_type this app actually writes today (see engine/main.py's
// register_scan() call sites) gets friendly copy here. STOCK is always
// offered (it's the primary product surface, per FORTRESS-UX1 Part 3) even
// with zero rows; every other section only appears if the app has actually
// recorded a run for it — never an empty section invented from this list.
const SECTION_META: Record<string, SectionMeta> = {
  STOCK: {
    scanType: 'STOCK', label: 'Stocks', icon: '📈',
    loadingMessage: 'Loading Stock scan history…',
    emptyMessage: 'No Stock scans yet.',
    errorMessage: "Stock scan history couldn't be loaded.",
  },
  MF: {
    scanType: 'MF', label: 'Mutual Funds', icon: '🪙',
    loadingMessage: 'Loading Mutual Fund scan history…',
    emptyMessage: 'No Mutual Fund scans yet.',
    errorMessage: "Mutual Fund scan history couldn't be loaded.",
  },
  COMMODITY: {
    scanType: 'COMMODITY', label: 'Commodities', icon: '🌍',
    loadingMessage: 'Loading Commodities scan history…',
    emptyMessage: 'No Commodities scans yet.',
    errorMessage: "Commodities scan history couldn't be loaded.",
  },
  OPTIONS: {
    scanType: 'OPTIONS', label: 'Options', icon: '🧮',
    loadingMessage: 'Loading Options scan history…',
    emptyMessage: 'No Options scans yet.',
    errorMessage: "Options scan history couldn't be loaded.",
  },
};

export function sectionMeta(scanType: string): SectionMeta {
  return SECTION_META[scanType] || {
    scanType, label: scanType, icon: '📄',
    loadingMessage: `Loading ${scanType} scan history…`,
    emptyMessage: `No ${scanType} scans yet.`,
    errorMessage: `${scanType} scan history couldn't be loaded.`,
  };
}

/** STOCK first, then every other scan_type actually present in `entries` — never a section with zero real runs, except STOCK. */
export function sectionsFromEntries(entries: ScanHistoryEntry[]): SectionMeta[] {
  const present = new Set(entries.map(e => e.scan_type));
  const ordered = [STOCK_SECTION, ...Array.from(present).filter(t => t !== STOCK_SECTION).sort()];
  return ordered.filter(t => t === STOCK_SECTION || present.has(t)).map(sectionMeta);
}

/** Only this section's runs, newest first — chronology lives inside a section, never across sections. */
export function filterEntriesBySection(entries: ScanHistoryEntry[], scanType: string): ScanHistoryEntry[] {
  return entries.filter(e => e.scan_type === scanType).sort((a, b) => b.scan_id - a.scan_id);
}

/** "AUTO_MULTI(Nifty 50,Nifty Next 50,...)" -> "4 universes"; anything else passes through as-is. */
export function describeUniverseCoverage(universe: string): string {
  const match = universe.match(/^AUTO_MULTI\(([^)]*)\)$/);
  if (!match) return universe;
  const count = match[1].split(',').filter(Boolean).length;
  return count === 1 ? '1 universe' : `${count} universes`;
}

export function getStoredSection(): string | null {
  try {
    return typeof window === 'undefined' ? null : window.localStorage.getItem(STORAGE_KEY);
  } catch {
    return null;
  }
}

export function setStoredSection(scanType: string): void {
  try {
    if (typeof window !== 'undefined') window.localStorage.setItem(STORAGE_KEY, scanType);
  } catch {
    // best-effort only — a blocked/full localStorage must never break navigation
  }
}

/** URL `?section=` wins, then the remembered local choice, then the Stocks default. */
export function resolveInitialSection(urlSection: string | null, sections: SectionMeta[]): string {
  const known = new Set(sections.map(s => s.scanType));
  if (urlSection && known.has(urlSection)) return urlSection;
  const stored = getStoredSection();
  if (stored && known.has(stored)) return stored;
  return STOCK_SECTION;
}

export interface StockResultSplit {
  actionable: Record<string, unknown>[];
  filtered: Record<string, unknown>[];
  momentum: Record<string, unknown>[];
  longTerm: Record<string, unknown>[];
}

/** The exact live-screener split (Quality_Gate_Pass / Strategy) — reused
 * verbatim for historical rows so a historical run is grouped exactly the
 * way the live scanner would have grouped it, using only stored fields. */
export function splitStockResults(rows: Record<string, unknown>[]): StockResultSplit {
  return {
    actionable: rows.filter(r => r.Quality_Gate_Pass === true),
    filtered: rows.filter(r => r.Quality_Gate_Pass === false),
    momentum: rows.filter(r => r.Strategy === 'Momentum Pick'),
    longTerm: rows.filter(r => r.Strategy === 'Long-Term Pick'),
  };
}
