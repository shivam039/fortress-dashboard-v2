'use client';

import { useMemo, useState } from 'react';
import Link from 'next/link';
import { helpDefinitions } from '@/lib/help-definitions';

export default function GlossaryPage() {
  const [query, setQuery] = useState('');
  const entries = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return Object.values(helpDefinitions)
      .filter(item => !needle || [item.label, item.fullName, item.shortDescription, item.format]
        .filter(Boolean).join(' ').toLowerCase().includes(needle))
      .sort((left, right) => left.label.localeCompare(right.label));
  }, [query]);

  return (
    <div className="page-container glossary-page">
      <div className="page-header">
        <div>
          <h1>Glossary</h1>
          <p>Plain-language definitions for terms shown in Fortress. These explanations provide context, not investment advice.</p>
        </div>
        <Link href="/dashboard" className="btn btn-secondary">Back to Dashboard</Link>
      </div>
      <label className="glossary-search-label" htmlFor="glossary-search">Search by abbreviation, full name, description, or unit</label>
      <input id="glossary-search" className="form-input glossary-search" type="search" value={query} onChange={event => setQuery(event.target.value)} placeholder="Try RSI, volatility, or contracts" />
      <p className="glossary-count" role="status">{entries.length} {entries.length === 1 ? 'term' : 'terms'}</p>
      {entries.length === 0 ? (
        <div className="empty-state"><div className="icon">🔎</div><p>No glossary terms match “{query}”. Try an abbreviation or broader concept.</p></div>
      ) : (
        <div className="glossary-grid">
          {entries.map(item => (
            <article className="card glossary-entry" id={item.glossaryKey} key={item.glossaryKey}>
              <h2>{item.label}</h2>
              {item.fullName && <p className="glossary-full-name">{item.fullName}</p>}
              <p>{item.shortDescription}</p>
              {item.format && <p><strong>Unit / scale:</strong> {item.format}</p>}
              <span className="badge badge-neutral">{item.category}</span>
            </article>
          ))}
        </div>
      )}
    </div>
  );
}
