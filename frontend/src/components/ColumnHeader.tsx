'use client';

import React, { useId, useState } from 'react';
import Link from 'next/link';

import { ColumnDefinition, getColumnDefinition } from '@/lib/column-definitions';

export type ColumnSpec = string | ({ key: string } & Partial<ColumnDefinition>);

export function resolveColumn(column: ColumnSpec): ColumnDefinition & { key: string } {
  const key = typeof column === 'string' ? column : column.key;
  const canonical = getColumnDefinition(key);
  return { ...canonical, ...(typeof column === 'string' ? {} : column), key };
}

export default function ColumnHeader({ column, showLabel = true }: { column: ColumnSpec; showLabel?: boolean }) {
  const definition = resolveColumn(column);
  const tooltipId = useId();
  const [open, setOpen] = useState(false);

  if (!definition.description) return showLabel ? <span>{definition.label}</span> : null;

  return (
    <span className="column-heading">
      {showLabel && <span>{definition.label}</span>}
      <span
        className="column-help"
        onMouseEnter={() => setOpen(true)}
        onMouseLeave={() => setOpen(false)}
        onFocus={() => setOpen(true)}
        onBlur={(event) => {
          if (!event.currentTarget.contains(event.relatedTarget)) setOpen(false);
        }}
        onKeyDown={(event) => {
          if (event.key === 'Escape') {
            setOpen(false);
            event.stopPropagation();
          }
        }}
      >
        <button
          type="button"
          className="column-help-trigger"
          aria-label={`About ${definition.label} column`}
          aria-expanded={open}
          aria-describedby={open ? tooltipId : undefined}
          onClick={(event) => { event.stopPropagation(); setOpen(true); }}
        >ⓘ</button>
        {open && (
          <span className="column-help-tooltip" id={tooltipId} role="tooltip">
            {definition.description}
            {definition.format && <span className="column-help-format">Format: {definition.format}.</span>}
            {definition.glossaryKey && <Link href={`/glossary#${definition.glossaryKey}`} onClick={event => event.stopPropagation()}>Learn more</Link>}
          </span>
        )}
      </span>
    </span>
  );
}
