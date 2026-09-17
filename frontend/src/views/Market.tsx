import { useEffect, useState } from 'react';
import { api, type Coverage } from '../api';

const C: Record<string, string> = { full: 'good', shallow: 'warn', prices_only: 'bad', no_prices: 'bad' };

export default function Market({ onOpen }: { onOpen: (id: string) => void }) {
  const [c, setC] = useState<Coverage | null>(null);
  useEffect(() => { api.coverage().then(setC); }, []);
  if (!c) return <div className="empty">loading</div>;
  return (
    <div className="scroll"><div className="pagewrap">
      <h1 className="h1">Market data — what the agent would be allowed to see at each T0</h1>
      <p className="sub">yfinance daily prices from 2018 and <b>annual</b> statements (income · balance · cash flow). A fiscal year is visible at T0 once period_end + 90 days ≤ T0. <span className="mono">full</span> = 3+ fiscal years visible, <span className="mono">shallow</span> = 1–2, <span className="mono">prices_only</span> = 0.</p>
      <div className="stats">
        {Object.entries(c.summary).map(([k, n]) => (<div className="stat" key={k}><div className="v">{n}</div><div className="l">{k}</div></div>))}
        <div className="stat"><div className="v">{c.tickers.filter((t) => t.benchmark).length}</div><div className="l">tickers</div><div className="d">{c.tickers.filter((t) => !t.benchmark).map((t) => String(t.ticker)).join(', ')} as benchmarks</div></div>
      </div>
      <div className="panel tablewrap">
        <table>
          <thead><tr><th>T0</th><th>ticker</th><th>title</th><th>year</th><th className="num">price at T0</th><th className="num">FYs visible</th><th>latest FY</th><th>earliest FY known</th><th>coverage</th></tr></thead>
          <tbody>{c.rows.map((r) => (
            <tr key={r.video_id} className="click" onClick={() => onOpen(r.video_id)}>
              <td className="mono">{r.t0}</td><td className="mono">{r.ticker}</td><td>{r.title}</td><td className="mono">{r.year_bucket}</td>
              <td className="num">{r.price_at_t0 != null ? `${r.price_at_t0.toFixed(2)} ${r.currency ?? ''}` : '—'}</td>
              <td className="num">{r.fys_visible ?? 0} / {r.fys_total ?? 0}</td>
              <td className="mono">{r.latest_fy_visible ? String(r.latest_fy_visible).slice(0, 4) : '—'}</td>
              <td className="mono">{r.earliest_fy ? String(r.earliest_fy).slice(0, 4) : '—'}</td>
              <td><span className={'badge ' + (C[r.coverage] ?? '')}>{r.coverage}</span></td>
            </tr>
          ))}</tbody>
        </table>
        {!c.rows.length && <div className="empty">no sampled videos yet</div>}
      </div>
      <div className="panel"><h3>Tickers <span className="microlabel">vi.tickers</span></h3>
        <table><thead><tr><th>ticker</th><th>name</th><th>exchange</th><th>ccy</th><th>benchmark</th><th>prices</th></tr></thead>
          <tbody>{c.tickers.map((t) => (<tr key={String(t.ticker)}><td className="mono">{String(t.ticker)}</td><td>{String(t.name ?? '')}</td><td className="mono">{String(t.exchange ?? '')}</td><td className="mono">{String(t.currency ?? '')}</td><td className="mono">{String(t.benchmark ?? '— (is one)')}</td><td className="mono">{t.yahoo_ok ? `${t.first_price} → ${t.last_price}` : <span className="badge bad">none</span>}</td></tr>))}</tbody></table>
      </div>
    </div></div>
  );
}
