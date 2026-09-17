type Pt = { date: string; adj_close: number };
/** Adjusted close around T0, benchmark rebased to the stock at T0, forward markers. Hand-rolled SVG on the tokens. */
export default function PriceChart({ prices, benchmark, t0, forward, currency }: {
  prices: Pt[]; benchmark: Pt[]; t0: string; forward?: Record<string, { date: string; close: number } | null>; currency?: string | null;
}) {
  const W = 720, H = 260, L = 46, R = 12, T = 12, B = 26;
  if (!prices.length) return <div className="empty">no prices loaded for this ticker</div>;
  const dates = prices.map((p) => new Date(p.date).getTime());
  const x0 = Math.min(...dates), x1 = Math.max(...dates);
  const t0ms = new Date(t0).getTime();
  const at = prices.reduce((best, p) => (new Date(p.date).getTime() <= t0ms ? p : best), prices[0]);
  const bAt = benchmark.reduce<Pt | null>((best, p) => (new Date(p.date).getTime() <= t0ms ? p : best), null);
  const bench = bAt ? benchmark.map((p) => ({ date: p.date, adj_close: (p.adj_close / bAt.adj_close) * at.adj_close })) : [];
  const ys = [...prices.map((p) => p.adj_close), ...bench.map((p) => p.adj_close)];
  const y0 = Math.min(...ys) * 0.97, y1 = Math.max(...ys) * 1.03;
  const X = (d: string) => L + ((new Date(d).getTime() - x0) / Math.max(1, x1 - x0)) * (W - L - R);
  const Y = (v: number) => T + (1 - (v - y0) / Math.max(1e-9, y1 - y0)) * (H - T - B);
  const path = (pts: Pt[]) => pts.map((p, i) => `${i ? 'L' : 'M'}${X(p.date).toFixed(1)},${Y(p.adj_close).toFixed(1)}`).join(' ');
  const xt0 = X(t0);
  const ticks = [y0, (y0 + y1) / 2, y1].map((v) => ({ v, y: Y(v) }));
  const years: { x: number; label: string }[] = [];
  for (let y = new Date(x0).getFullYear(); y <= new Date(x1).getFullYear() + 1; y++) {
    const ms = new Date(`${y}-01-01`).getTime();
    if (ms >= x0 && ms <= x1) years.push({ x: X(`${y}-01-01`), label: String(y) });
  }
  return (
    <div>
      <svg className="chart" viewBox={`0 0 ${W} ${H}`} role="img" aria-label="price around the video date">
        <rect x={xt0} y={T} width={Math.max(0, W - R - xt0)} height={H - T - B} fill="var(--good)" opacity=".06" />
        {ticks.map((t) => (<g key={t.v}><line x1={L} x2={W - R} y1={t.y} y2={t.y} stroke="var(--border)" /><text x={L - 6} y={t.y + 3} textAnchor="end" fontSize="9" fontFamily="var(--mono)" fill="var(--dim)">{t.v.toFixed(0)}</text></g>))}
        {years.map((y) => (<g key={y.label}><line x1={y.x} x2={y.x} y1={T} y2={H - B} stroke="var(--border)" strokeDasharray="2 3" /><text x={y.x + 3} y={H - B + 12} fontSize="9" fontFamily="var(--mono)" fill="var(--dim)">{y.label}</text></g>))}
        {bench.length > 1 && <path d={path(bench)} fill="none" stroke="var(--muted)" strokeWidth="1" strokeDasharray="3 3" />}
        <path d={path(prices)} fill="none" stroke="var(--accent)" strokeWidth="1.6" />
        <line x1={xt0} x2={xt0} y1={T} y2={H - B} stroke="var(--bad)" strokeWidth="1.5" />
        <text x={xt0 + 4} y={T + 10} fontSize="9.5" fontFamily="var(--mono)" fill="var(--bad)">T0 {t0} · {at.adj_close.toFixed(2)} {currency ?? ''}</text>
        {forward && Object.entries(forward).map(([m, f]) => f ? (
          <g key={m}><circle cx={X(f.date)} cy={Y(f.close)} r="3.5" fill="var(--good)" /><text x={X(f.date)} y={Y(f.close) - 7} textAnchor="middle" fontSize="9" fontFamily="var(--mono)" fill="var(--good)">+{m}m</text></g>
        ) : null)}
        <text x={L} y={T + 10} fontSize="9" fontFamily="var(--mono)" fill="var(--accent2)">agent may see ←</text>
        <text x={W - R} y={T + 10} textAnchor="end" fontSize="9" fontFamily="var(--mono)" fill="var(--good)">→ validator only</text>
      </svg>
      <div className="legend"><span><i style={{ background: 'var(--accent)' }} />adjusted close</span><span><i style={{ background: 'var(--muted)' }} />benchmark, rebased at T0</span><span><i style={{ background: 'var(--bad)' }} />T0 = video date</span><span><i style={{ background: 'var(--good)', borderRadius: 4, height: 6 }} />+6 / 12 / 24 m close</span></div>
    </div>
  );
}
