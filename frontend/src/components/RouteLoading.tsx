// src/components/RouteLoading.tsx — Shared instant-feedback fallback for
// route navigation. Next.js App Router shows the nearest `loading.tsx`
// while a route segment's code is being prepared (in dev, this includes
// the moment Turbopack compiles that route for the first time). Without
// one, clicking a sidebar tab that hasn't been compiled yet just does
// nothing for a beat — indistinguishable from "stuck". Every page/
// loading.tsx renders this so a spinner shows immediately instead.
export default function RouteLoading() {
  return (
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', minHeight: '40vh' }}>
      <div style={{ textAlign: 'center' }}>
        <div className="spinner" style={{ margin: '0 auto 16px' }} />
        <div style={{ color: 'var(--text-muted)', fontSize: '0.88rem' }}>Loading…</div>
      </div>
    </div>
  );
}
