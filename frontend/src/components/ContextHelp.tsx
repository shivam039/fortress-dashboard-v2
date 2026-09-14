'use client';

import Link from 'next/link';
import React, { useId, useState } from 'react';
import { helpDefinitions, type HelpKey } from '@/lib/help-definitions';

export default function ContextHelp({ term, helpKey, children }: { term?: string; helpKey?: HelpKey; children?: React.ReactNode }) {
  const [open, setOpen] = useState(false);
  const descriptionId = useId();
  const definition = helpKey ? helpDefinitions[helpKey] : undefined;
  const accessibleTerm = term ?? definition?.label ?? 'this value';

  return (
    <span className="context-help" onMouseLeave={() => setOpen(false)}>
      <button
        type="button"
        className="context-help-trigger"
        aria-label={`Explain ${accessibleTerm}`}
        aria-expanded={open}
        aria-describedby={open ? descriptionId : undefined}
        onClick={() => setOpen(value => !value)}
        onMouseEnter={() => setOpen(true)}
        onFocus={() => setOpen(true)}
        onKeyDown={(event) => { if (event.key === 'Escape') setOpen(false); }}
      >
        ⓘ
      </button>
      {open && (
        <span id={descriptionId} role="tooltip" className="context-help-popover">
          {children ?? definition?.shortDescription}
          {definition && <Link href={`/help/glossary#${definition.glossaryKey}`}>Learn more →</Link>}
        </span>
      )}
    </span>
  );
}
