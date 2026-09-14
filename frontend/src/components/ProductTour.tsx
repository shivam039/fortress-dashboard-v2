'use client';

import React, { useEffect, useLayoutEffect, useRef, useState, useSyncExternalStore } from 'react';
import Link from 'next/link';

const TOUR_COMPLETE_KEY = 'fortress-product-tour-complete';
const TOUR_STATE_EVENT = 'fortress-product-tour-state';

const STEPS = [
  { target: 'dashboard', title: 'Your Fortress overview', body: 'Dashboard summarizes your account and recent activity. Use it as the starting point for a research session.' },
  { target: 'screener', title: 'Find and inspect stock signals', body: 'Stock Screener searches a selected Indian-stock universe. A Fortress Score is rule-based decision support, not a probability or return forecast.' },
  { target: 'history', title: 'Replay scans by section', body: 'Scan History first separates scanner types, then lists that section\'s runs. Opening a run shows a read-only historical result.' },
  { target: 'picks', title: 'Separate signals from outcomes', body: 'Oracle decisions can be opened from eligible signal evidence. Picks Tracker records monitored ideas; neither is a promise about future performance.' },
  { target: 'paper-trading', title: 'Practice without real capital', body: 'Paper Trading turns eligible recorded signals into simulated positions. Opening or closing one is still a saved action, never a broker order.' },
  { target: 'mf-lab', title: 'Research mutual funds', body: 'Mutual Fund Lab compares available schemes, categories, metrics, and conviction detail. Job controls change stored analysis, so use them only when appropriate.' },
  { target: 'reit-invits', title: 'Explore other asset classes', body: 'REITs & InvITs provide separate discovery and decision-support views for listed real-estate and infrastructure trusts.' },
  { target: 'us-investing', title: 'Research US stocks and ETFs', body: 'US Investing shows available US-listed instruments with USD prices and INR conversion. USD/INR movement independently affects your returns.' },
  { target: 'commodities', title: 'Compare commodity data', body: 'Commodities provides a snapshot of commodity analysis and decision cards. Refresh requests new provider data and triggers backend work.' },
  { target: 'options', title: 'Inspect options safely', body: 'Options shows chain snapshots and read-only expiry payoff calculations. Displayed payoff points are a range; theoretical maximum profit or loss is reported separately.' },
  { target: 'orders', title: 'Review recorded activity', body: 'Orders and Profile contain user-maintained records and broker settings. These controls can save or remove data, unlike read-only research screens.' },
  { target: 'profile', title: 'Manage account settings', body: 'Profile shows your account details and broker connections. Connecting or disconnecting a broker updates stored credentials - handle carefully.' },
  { target: 'help', title: 'Help is always available', body: 'Restart this tour from Help. The user guide and glossary explain screens, status labels, metrics, limitations, and common workflows.' },
] as const;

type HighlightRect = Pick<DOMRect, 'top' | 'left' | 'width' | 'height'>;

function subscribeToCompletion(onStoreChange: () => void): () => void {
  const notify = () => onStoreChange();
  window.addEventListener('storage', notify);
  window.addEventListener(TOUR_STATE_EVENT, notify);
  return () => {
    window.removeEventListener('storage', notify);
    window.removeEventListener(TOUR_STATE_EVENT, notify);
  };
}

function completionSnapshot(): boolean {
  return localStorage.getItem(TOUR_COMPLETE_KEY) === 'true';
}

function serverCompletionSnapshot(): boolean {
  return false;
}

function saveCompletion(): void {
  localStorage.setItem(TOUR_COMPLETE_KEY, 'true');
  window.dispatchEvent(new Event(TOUR_STATE_EVENT));
}

export default function ProductTour() {
  const [menuOpen, setMenuOpen] = useState(false);
  const [stepIndex, setStepIndex] = useState<number | null>(null);
  const [highlight, setHighlight] = useState<HighlightRect | null>(null);
  const dialogRef = useRef<HTMLDivElement>(null);
  const helpButtonRef = useRef<HTMLButtonElement>(null);
  const activeStep = stepIndex === null ? null : STEPS[stepIndex];
  const complete = useSyncExternalStore(
    subscribeToCompletion,
    completionSnapshot,
    serverCompletionSnapshot,
  );

  const close = (markComplete: boolean) => {
    if (markComplete) saveCompletion();
    setStepIndex(null);
    setHighlight(null);
    requestAnimationFrame(() => helpButtonRef.current?.focus());
  };

  useLayoutEffect(() => {
    if (!activeStep) return;
    const target = document.querySelector<HTMLElement>(`[data-tour="${activeStep.target}"]`);
    const updateHighlight = () => {
      if (!target || target.getClientRects().length === 0) {
        setHighlight(null);
        return;
      }
      const rect = target.getBoundingClientRect();
      setHighlight({ top: rect.top, left: rect.left, width: rect.width, height: rect.height });
    };
    updateHighlight();
    window.addEventListener('resize', updateHighlight);
    window.addEventListener('scroll', updateHighlight, true);
    return () => {
      window.removeEventListener('resize', updateHighlight);
      window.removeEventListener('scroll', updateHighlight, true);
    };
  }, [activeStep]);

  useEffect(() => {
    if (!activeStep || stepIndex === null) return;
    const currentIndex = stepIndex;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    dialogRef.current?.focus();
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') close(false);
      if (event.key === 'ArrowRight' && currentIndex < STEPS.length - 1) setStepIndex(currentIndex + 1);
      if (event.key === 'ArrowLeft' && currentIndex > 0) setStepIndex(currentIndex - 1);
      if (event.key === 'Tab' && dialogRef.current) {
        const focusable = Array.from(
          dialogRef.current.querySelectorAll<HTMLElement>('button:not(:disabled), [href], [tabindex]:not([tabindex="-1"])'),
        );
        const first = focusable[0];
        const last = focusable[focusable.length - 1];
        const outsideDialog = !dialogRef.current.contains(document.activeElement);
        if (outsideDialog || (event.shiftKey && document.activeElement === first)) {
          event.preventDefault();
          (event.shiftKey ? last : first)?.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first?.focus();
        }
      }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => {
      document.body.style.overflow = previousOverflow;
      window.removeEventListener('keydown', onKeyDown);
    };
  }, [activeStep, stepIndex]);

  const start = () => {
    setMenuOpen(false);
    setStepIndex(0);
  };

  return (
    <>
      <div className="tour-help" data-tour="help">
        <button
          ref={helpButtonRef}
          className="tour-help-button"
          aria-label="Help and product tour"
          aria-expanded={menuOpen}
          aria-controls="tour-help-panel"
          onClick={() => setMenuOpen(value => !value)}
        >
          ? <span>Help</span>
        </button>
        {menuOpen && (
          <div className="tour-help-menu" id="tour-help-panel">
            <strong>New to Fortress?</strong>
            <p>Take a short, read-only tour of the product.</p>
            <button className="btn btn-primary btn-sm" onClick={start}>
              {complete ? 'Restart Tour' : 'Take a Tour'}
            </button>
            <div className="tour-help-links">
              <Link href="/help/glossary" onClick={() => setMenuOpen(false)}>Glossary</Link>
              <a href="https://github.com/shivam039/fortress-dashboard-v2/blob/main/docs/user/QUICK_START.md" target="_blank" rel="noreferrer">Quick Start</a>
              <a href="https://github.com/shivam039/fortress-dashboard-v2/blob/main/docs/user/USER_GUIDE.md" target="_blank" rel="noreferrer">User Guide</a>
            </div>
          </div>
        )}
      </div>

      {activeStep && stepIndex !== null && (
        <div className="tour-overlay">
          {highlight && (
            <div
              className="tour-highlight"
              aria-hidden="true"
              style={{ top: highlight.top, left: highlight.left, width: highlight.width, height: highlight.height }}
            />
          )}
          <div
            ref={dialogRef}
            className="tour-dialog"
            role="dialog"
            aria-modal="true"
            aria-label="Fortress product tour"
            tabIndex={-1}
          >
            <div className="tour-progress">Step {stepIndex + 1} of {STEPS.length}</div>
            <h2>{activeStep.title}</h2>
            <p>{activeStep.body}</p>
            <div className="tour-actions">
              <button className="btn btn-secondary btn-sm" onClick={() => close(true)}>Skip tour</button>
              <span className="tour-spacer" />
              <button className="btn btn-secondary btn-sm" disabled={stepIndex === 0} onClick={() => setStepIndex(stepIndex - 1)}>Back</button>
              {stepIndex === STEPS.length - 1 ? (
                <button className="btn btn-primary btn-sm" onClick={() => close(true)}>Finish</button>
              ) : (
                <button className="btn btn-primary btn-sm" onClick={() => setStepIndex(stepIndex + 1)}>Next</button>
              )}
            </div>
          </div>
        </div>
      )}
    </>
  );
}
