'use client';

import React, { useState } from 'react';
import { oracleApi, type OracleDecision } from '@/lib/api';

export default function OracleDecisionCard({ signalId }: { signalId: number }) {
  const [state, setState] = useState<'idle' | 'loading' | 'ready' | 'error'>('idle');
  const [decision, setDecision] = useState<OracleDecision | null>(null);
  const [error, setError] = useState('');

  const load = async () => {
    setState('loading');
    setError('');
    try {
      setDecision(await oracleApi.decision(signalId));
      setState('ready');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not load Oracle Decision.');
      setState('error');
    }
  };

  return (
    <div className="card" data-testid="oracle-decision">
      {state === 'idle' && <button className="btn btn-secondary" onClick={load}>Oracle Decision</button>}
      {state === 'loading' && <p role="status">Loading Oracle Decision…</p>}
      {state === 'error' && <p role="alert">{error} <button className="btn btn-secondary" onClick={load}>Retry</button></p>}
      {decision && state === 'ready' && (
        <div>
          <h4>{decision.symbol} · {decision.decision}</h4>
          <p>Confidence: {decision.confidence} · Score: {decision.score ?? 'unavailable'}</p>
          <p>Data as of: {decision.data_as_of ?? 'unavailable'}</p>
          {decision.reasons.length > 0 && <><strong>Reasons</strong><ul>{decision.reasons.map(r => <li key={r.key}>{r.label}: {String(r.value)}</li>)}</ul></>}
          {decision.cautions.length > 0 && <><strong>Cautions</strong><ul>{decision.cautions.map(c => <li key={c.key}>{c.label}: {String(c.value)}</li>)}</ul></>}
          {decision.paper_trade.available && <p>Paper Trade remains a separate user-confirmed action.</p>}
        </div>
      )}
    </div>
  );
}
