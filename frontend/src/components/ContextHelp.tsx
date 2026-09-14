'use client';

import React, { useId, useState } from 'react';

export default function ContextHelp({ term, children }: { term: string; children: React.ReactNode }) {
  const [open, setOpen] = useState(false);
  const descriptionId = useId();

  return (
    <span className="context-help">
      <button
        type="button"
        className="context-help-trigger"
        aria-label={`Explain ${term}`}
        aria-expanded={open}
        aria-describedby={open ? descriptionId : undefined}
        onClick={() => setOpen(value => !value)}
        onBlur={() => setOpen(false)}
      >
        ⓘ
      </button>
      {open && <span id={descriptionId} role="tooltip" className="context-help-popover">{children}</span>}
    </span>
  );
}
