import { useEffect, useMemo, useState } from 'react';
import { api, type Video, type VideoDetail } from '../api';
import PriceChart from './PriceChart';

const fmt = (v: number | undefined) => v === undefined || v === null ? '' : Math.abs(v) >= 1e9 ? (v / 1e9).toFixed(2) + ' B' : Math.abs(v) >= 1e6 ? (v / 1e6).toFixed(1) + ' M' : Math.abs(v) >= 1e3 ? (v / 1e3).toFixed(1) + ' K' : v.toFixed(2);
const ts = (s: number | null | undefined) => s == null ? '' : `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, '0')}`;
const pct = (a: number, b: number) => `${(((b - a) / a) * 100).toFixed(1)} %`;

export default function VideoView({ videoId, onSelect }: { videoId?: string; onSelect: (id: string) => void }) {
  const [list, setList] = useState<Video[]>([]);
  const [q, setQ] = useState('');
  const [d, setD] = useState<VideoDetail | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [showAll, setShowAll] = useState<Record<string, boolean>>({});
  useEffect(() => { api.videos(true).then(setList); }, []);
  useEffect(() => {
    if (!videoId) { setD(null); return; }
    setErr(null);
    api.video(videoId).then(setD).catch((e) => setErr(String(e)));
  }, [videoId]);
  useEffect(() => { if (!videoId && list.length) onSelect(list[list.length - 1].video_id); }, [list, videoId, onSelect]);
  const rows = useMemo(() => list.filter((v) => !q || v.title.toLowerCase().includes(q.toLowerCase()) || (v.primary_ticker ?? '').toLowerCase().includes(q.toLowerCase())), [list, q]);
  const cov = d?.coverage;
  return (
    <div className="split">
      <aside className="rail">
        <div className="rail-head"><input type="search" placeholder="filter sampled videos" value={q} onChange={(e) => setQ(e.target.value)} /></div>
        {rows.map((v) => (
          <div key={v.video_id} className={'rentry ' + (v.video_id === videoId ? 'on' : '')} onClick={() => onSelect(v.video_id)}>
            <div className="rq">{v.title}</div>
            <div className="rmeta">{v.primary_ticker} · {v.published_at} · {v.year_bucket} · {v.transcript_status}</div>
          </div>
        ))}
      </aside>
      <div className="scroll"><div className="pagewrap">
        {err && <div className="note warn">{err}</div>}
        {!d && !err && <div className="empty">pick a video</div>}
        {d && (
          <>
            <div className="vhead"><h2>{d.video.title}</h2><span className="badge acc">{d.video.kind}</span>{cov && <span className={'badge ' + (cov.coverage === 'full' ? 'good' : cov.coverage === 'shallow' ? 'warn' : 'bad')}>{cov.coverage}</span>}</div>
            <div className="vmeta">
              <span>{d.video.primary_ticker} · {d.video.company ?? ''} {d.video.exchange ? `· ${d.video.exchange}` : ''}</span>
              <span>T0 {d.t0}</span><span>{d.video.year_bucket} · rank {d.video.sample_rank}</span>
              <span>{Math.round((d.video.duration_s ?? 0) / 60)} min · {d.video.view_count?.toLocaleString()} views</span>
              <a className="mono" href={`https://www.youtube.com/watch?v=${d.video.video_id}`} target="_blank" rel="noreferrer" style={{ color: 'var(--accent2)' }}>youtube ↗</a>
              <span>classifier {d.video.confidence?.toFixed(2)} — {d.video.rationale}</span>
            </div>
            <div className="grid2">
              <div>
                <div className="panel"><h3>Price around T0 <span className="microlabel">vi.prices · adjusted close</span></h3>
                  {d.t0 && <PriceChart prices={d.prices} benchmark={d.benchmark} t0={d.t0} forward={d.forward} currency={d.video.currency} />}
                  {d.price_at_t0 && (
                    <div className="fwd">
                      <div className="stat"><div className="v">{d.price_at_t0.close.toFixed(2)}</div><div className="l">close at T0 ({d.price_at_t0.date})</div></div>
                      {Object.entries(d.forward ?? {}).map(([m, f]) => (
                        <div className="stat" key={m}><div className="v" style={{ color: f ? (f.close >= d.price_at_t0!.close ? 'var(--good)' : 'var(--bad)') : 'var(--dim)' }}>{f ? pct(d.price_at_t0!.close, f.close) : '—'}</div><div className="l">+{m} m {f ? `(${f.date})` : 'not yet'}</div></div>
                      ))}
                    </div>
                  )}
                  <p className="note">Everything right of the red line is what the future validator will use. The agent (deferred) only ever sees the left side, and only the statements below.</p>
                </div>
                <div className="panel"><h3>Annual statements visible at T0 <span className="microlabel">vi.statements_as_of(ticker, T0) · yfinance annual · period_end + 90 d</span></h3>
                  {!d.statement_periods.length && <div className="empty">no fiscal year is visible at T0 for this ticker {d.statements_hidden_after_t0?.length ? `— the earliest yfinance still returns becomes visible on ${d.statements_hidden_after_t0[0].available_from}` : ''}</div>}
                  {!!d.statement_period_info?.some((p) => !p.complete) && <p className="note warn">yfinance's oldest column is a stub: FY {d.statement_period_info.filter((p) => !p.complete).map((p) => `${p.period_end.slice(0, 4)} (${p.n_items} items, no revenue / total assets)`).join(', ')}. Complete fiscal years visible at T0: {d.coverage?.fys_visible ?? 0}.</p>}
                  {(['income', 'balance', 'cashflow'] as const).map((k) => d.statements[k] && (
                    <div key={k} style={{ marginBottom: 12 }}>
                      <div className="microlabel" style={{ marginBottom: 4 }}>{k} · {showAll[k] ? Object.keys(d.statements[k].items).length : d.statements[k].headline.length} items <button className="pill" style={{ marginLeft: 8 }} onClick={() => setShowAll({ ...showAll, [k]: !showAll[k] })}>{showAll[k] ? 'headline only' : 'all line items'}</button></div>
                      <div className="tablewrap" style={{ maxHeight: showAll[k] ? 420 : 'none' }}>
                        <table><thead><tr><th>line item</th>{d.statement_periods.map((p) => <th key={p} className="num">FY {p.slice(0, 4)}{d.statement_period_info?.find((i) => i.period_end === p)?.complete === false ? ' (stub)' : ''}</th>)}</tr></thead>
                          <tbody>{(showAll[k] ? Object.keys(d.statements[k].items) : d.statements[k].headline).map((li) => (
                            <tr key={li}><td>{li}</td>{d.statement_periods.map((p) => <td key={p} className="num">{fmt(d.statements[k].items[li]?.[p])}</td>)}</tr>
                          ))}</tbody></table>
                      </div>
                    </div>
                  ))}
                  {!!d.statements_hidden_after_t0?.length && <p className="note warn">Hidden from the agent by the as-of rule: FY {d.statements_hidden_after_t0.map((h) => `${h.period_end.slice(0, 4)} (visible ${h.available_from})`).join(', ')}.</p>}
                </div>
              </div>
              <div>
                <div className="panel"><h3>Coverage</h3>
                  {cov ? (
                    <dl className="kv">
                      <dt>price at T0</dt><dd>{cov.price_at_t0 != null ? `${cov.price_at_t0.toFixed(2)} ${cov.currency ?? ''} (${cov.price_date})` : 'none'}</dd>
                      <dt>complete FYs at T0</dt><dd>{cov.fys_visible ?? 0} of {cov.fys_total ?? 0} yfinance returns{cov.latest_fy_visible ? ` · latest FY ${String(cov.latest_fy_visible).slice(0, 4)}` : ''}{cov.stub_fys_visible ? ` · +${cov.stub_fys_visible} stub` : ''}</dd>
                      <dt>earliest FY known</dt><dd>{cov.earliest_fy ? String(cov.earliest_fy).slice(0, 4) : '—'}</dd>
                      <dt>benchmark</dt><dd className="mono">{cov.benchmark}</dd>
                    </dl>
                  ) : <div className="empty">run <span className="mono">vi market</span></div>}
                </div>
                <div className="panel"><h3>Transcript <span className="microlabel">transcript·lab raw_transcripts · {d.transcript?.segments.length ?? 0} segments · {d.chunks.length} chunks</span></h3>
                  {d.transcript_error && <div className="note warn">corpus unavailable: {d.transcript_error}</div>}
                  {!d.transcript && !d.transcript_error && <div className="empty">not ingested yet (<span className="mono">uv run vi ingest</span>)</div>}
                  {d.transcript && (
                    <div className="transcript">
                      {d.transcript.segments.map((s, i) => (
                        <div className="seg" key={i}><span className="ts">{ts(s.start_seconds ?? (s.offset_ms != null ? s.offset_ms / 1000 : null))}</span><span>{s.text}</span></div>
                      ))}
                    </div>
                  )}
                </div>
                {d.video.description && <div className="panel"><h3>Description</h3><div style={{ whiteSpace: 'pre-wrap', fontSize: 'var(--t0)', color: 'var(--text2)', maxHeight: 200, overflow: 'auto' }}>{d.video.description}</div></div>}
              </div>
            </div>
          </>
        )}
      </div></div>
    </div>
  );
}
