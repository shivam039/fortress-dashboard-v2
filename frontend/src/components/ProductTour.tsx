'use client';

import React, { useEffect, useRef, useState } from 'react';

const TOUR_COMPLETE_KEY = 'fortress-product-tour-complete';

const STEPS = [
  { target: 'dashboard', title: 'Your Fortress overview', body: 'Dashboard summarizes your account and recent activity. Use it as the starting point for a research session.' },
  { target: 'screener', title: 'Find and inspect stock signals', body: 'Stock Screener searches a selected Indian-stock universe. A Fortress Score is rule-based decision support, not a probability or return forecast.' },
  { target: 'history', title: 'Replay scans by section', body: 'Scan History first separates scanner types, then lists that section’s runs. Opening a run shows a read-only historical result.' },
  { target: 'picks', title: 'Separate signals from outcomes', body: 'Oracle decisions can be opened from eligible signal evidence. Picks Tracker records monitored ideas; neither is a promise about future performance.' },
  { target: 'paper-trading', title: 'Practice without real capital', body: 'Paper Trading turns eligible recorded signals into simulated positions. Opening or closing one is still a saved action, never a broker order.' },
  { target: 'mf-lab', title: 'Research mutual funds', body: 'Mutual Fund Lab compares available schemes, categories, metrics, and conviction detail. Job controls change stored analysis, so use them only when appropriate.' },
  { target: 'reit-invits', title: 'Explore other asset classes', body: 'REITs & InvITs, US Investing, and Commodities provide separate discovery and decision-support views with asset-specific risks.' },
  { target: 'options', title: 'Inspect options safely', body: 'Options shows chain snapshots and read-only expiry payoff calculations. Displayed payoff points are a range; theoretical maximum profit or loss is reported separately.' },
  { target: 'orders', title: 'Review recorded activity', body: 'Orders and Profile contain user-maintained records and broker settings. These controls can save or remove data, unlike read-only research screens.' },
  { target: 'help', title: 'Help is always available', body: 'Restart this tour from Help. The user guide and glossary explain screens, status labels, metrics, limitations, and common workflows.' },
] as const;

export default function ProductTour() {
  const [menuOpen, setMenuOpen] = useState(false);
  const [stepIndex, setStepIndex] = useState<number | null>(null);
  const dialogRef = useRef<HTMLDivElement>(null);
  const activeStep = stepIndex === null ? null : STEPS[stepIndex];
  const complete = typeof window !== 'undefined' && localStorage.getItem(TOUR_COMPLETE_KEY) === 'true';

  const close = (markComplete: boolean) => {
    if (markComplete) localStorage.setItem(TOUR_COMPLETE_KEY, 'true');
    setStepIndex(null);
  };

  useEffect(() => {
    if (!activeStep) return;
    const target = document.querySelector<HTMLElement>(`[data-tour="${activeStep.target}"]`);
    if (target && target.getClientRects().length > 0) target.classList.add('tour-target-active');
    dialogRef.current?.focus();
    return () => target?.classList.remove('tour-target-active');
  }, [activeStep]);

  useEffect(() => {
    if (!activeStep || stepIndex === null) return;
    const currentIndex = stepIndex;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') close(false);
      if (event.key === 'ArrowRight' && currentIndex < STEPS.length - 1) setStepIndex(currentIndex + 1);
      if (event.key === 'ArrowLeft' && currentIndex > 0) setStepIndex(currentIndex - 1);
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [activeStep, stepIndex]);

  const start = () => {
    setMenuOpen(false);
    setStepIndex(0);
  };

  return (
    <>
      <div className="tour-help" data-tour="help">
        <button
          className="tour-help-button"
          aria-label="Help and product tour"
          aria-expanded={menuOpen}
          onClick={() => setMenuOpen(value => !value)}
        >
          ? <span>Help</span>
        </button>
        {menuOpen && (
          <div className="tour-help-menu" role="menu">
            <strong>New to Fortress?</strong>
            <p>Take a short, read-only tour of the product.</p>
            <button className="btn btn-primary btn-sm" role="menuitem" onClick={start}>
              {complete ? 'Restart Tour' : 'Take a Tour'}
            </button>
          </div>
        )}
      </div>

      {activeStep && stepIndex !== null && (
        <div className="tour-overlay">
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
              <button className="btn btn-secondary btn-sm" onClick={() => close(false)}>Skip tour</button>
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
