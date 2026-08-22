// src/components/DataTable.tsx — Sortable data table
'use client';

import React, { useState, useMemo } from 'react';

interface DataTableProps {
  data: Record<string, unknown>[];
  columns?: string[];
  emptyMessage?: string;
  maxRows?: number;
  // Called with the actual row object (after this table's own internal
  // sort is applied) plus its on-screen index. Callers must not try to
  // re-derive "which row was clicked" from DOM position or an index into
  // their own unsorted data array — this table sorts internally on column
  // click, so on-screen row order can diverge from the order `data` was
  // passed in, and a position-based lookup silently resolves to the wrong
  // row once the user sorts.
  onRowClick?: (row: Record<string, unknown>, index: number) => void;
  // Identifies the currently-selected row so it can be highlighted even
  // after a sort changes its on-screen position. Compared against
  // `rowKey(row, index)` for each row.
  selectedRowKey?: string | null;
  rowKey?: (row: Record<string, unknown>, index: number) => string;
}

function formatCell(value: unknown): string {
  if (value === null || value === undefined) return '—';
  if (typeof value === 'number') {
    if (Number.isInteger(value)) return value.toLocaleString();
    return value.toFixed(2);
  }
  if (typeof value === 'boolean') return value ? '✅' : '❌';
  if (typeof value === 'object') {
    try {
      return JSON.stringify(value);
    } catch {
      return '[object]';
    }
  }
  return String(value);
}

function renderObject(value: unknown): string {
  if (!value || typeof value !== 'object') return formatCell(value);

  const entries = Object.entries(value as Record<string, unknown>);
  return entries
    .map(([key, val]) => `${key}: ${formatCell(val)}`)
    .join(', ');
}

function isTrustedHtml(value: unknown): value is string {
  return (
    typeof value === 'string' &&
    value.includes('<a ') &&
    value.includes("target='_blank'")
  );
}

function getScoreClass(value: unknown): string {
  const num = typeof value === 'number' ? value : parseFloat(String(value));
  if (isNaN(num)) return '';
  if (num >= 85) return 'score-high';
  if (num >= 60) return 'score-medium';
  if (num < 35) return 'score-low';
  return '';
}

export default function DataTable({ data, columns, emptyMessage, maxRows, onRowClick, selectedRowKey, rowKey }: DataTableProps) {
  const [sortCol, setSortCol] = useState<string | null>(null);
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc');

  const cols = useMemo(() => {
    if (columns && columns.length > 0) return columns;
    if (data.length === 0) return [];
    return Object.keys(data[0]);
  }, [data, columns]);

  const sorted = useMemo(() => {
    if (!sortCol) return data;
    return [...data].sort((a, b) => {
      const va = a[sortCol];
      const vb = b[sortCol];
      if (va === vb) return 0;
      if (va === null || va === undefined) return 1;
      if (vb === null || vb === undefined) return -1;
      const cmp = typeof va === 'number' && typeof vb === 'number'
        ? va - vb
        : String(va).localeCompare(String(vb));
      return sortDir === 'asc' ? cmp : -cmp;
    });
  }, [data, sortCol, sortDir]);

  const rows = maxRows ? sorted.slice(0, maxRows) : sorted;

  if (data.length === 0) {
    return (
      <div className="empty-state">
        <div className="icon">📭</div>
        <p>{emptyMessage || 'No data available.'}</p>
      </div>
    );
  }

  const handleSort = (col: string) => {
    if (sortCol === col) {
      setSortDir(d => d === 'asc' ? 'desc' : 'asc');
    } else {
      setSortCol(col);
      setSortDir('desc');
    }
  };

  const isScoreCol = (col: string) =>
    col.toLowerCase().includes('score') || col === 'Score' || col === 'AI Score';

  return (
    <div className="data-table-container">
      <table className="data-table">
        <thead>
          <tr>
            {cols.map(col => (
              <th
                key={col}
                className={sortCol === col ? 'sorted' : ''}
                onClick={() => handleSort(col)}
              >
                {col.replace(/_/g, ' ')}
                {sortCol === col && (sortDir === 'asc' ? ' ↑' : ' ↓')}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => {
            const key = rowKey ? rowKey(row, i) : String(i);
            const isSelected = selectedRowKey != null && key === selectedRowKey;
            return (
            <tr
              key={key}
              className={onRowClick ? (isSelected ? 'row-selected' : 'row-clickable') : undefined}
              style={onRowClick ? { cursor: 'pointer' } : undefined}
              onClick={onRowClick ? () => onRowClick(row, i) : undefined}
            >
              {cols.map(col => (
                <td key={col}>
                  {isTrustedHtml(row[col]) ? (
                    <span dangerouslySetInnerHTML={{ __html: row[col] }} />
                  ) : isScoreCol(col) ? (
                    <span className={`score-badge ${getScoreClass(row[col])}`}>
                      {formatCell(row[col])}
                    </span>
                  ) : typeof row[col] === 'object' && row[col] !== null ? (
                    renderObject(row[col])
                  ) : (
                    formatCell(row[col])
                  )}
                </td>
              ))}
            </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
