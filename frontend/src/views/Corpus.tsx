import { useEffect, useMemo, useState } from 'react';
import { api, type Funnel, type Video } from '../api';

const KIND_BADGE: Record<string, string> = { single: 'good', multi: 'warn', macro: 'bad', other: '', unlabelled: '' };

export default function Corpus({ onOpen }: { onOpen: (id: string) => void }) {
  const [funnel, setFunnel] = useState<Funnel | null>(null);
  const [videos, setVideos] = useState<Video[]>([]);
  const [sampleOnly, setSampleOnly] = useState(true);
  const [kind, setKind] = useState<string>('');
  const [year, setYear] = useState<string>('');
  const [q, setQ] = useState('');
  useEffect(() => { api.funnel().then(setFunnel); }, []);
  useEffect(() => { api.videos(sampleOnly).then(setVideos); }, [sampleOnly]);
  const rows = useMemo(() => videos.filter((v) => (!kind || v.kind === kind) && (!year || v.year_bucket === year) && (!q || v.title.toLowerCase().includes(q.toLowerCase()))), [videos, kind, year, q]);
  const years = funnel?.per_year.map((y) => y.year_bucket) ?? [];
  return (
    <div className="scroll"><div className="pagewrap">
      <h1 className="h1">Corpus — what was catalogued, classified, sampled and ingested</h1>
      <p className="sub">Channel @Value-Investing · window {funnel?.since} → {funnel?.until} · {funnel?.per_year_target} single-stock videos per window year, seed {funnel?.seed}. Transcripts live in transcript·lab's Chroma; this table is <span className="mono">vi.videos</span>.</p>
      {funnel && (
        <div className="stats">
          <div className="stat"><div className="v">{funnel.listed.toLocaleString()}</div><div className="l">videos listed</div><div className="d">Supadata channel listing</div></div>
          <div className="stat"><div className="v">{funnel.in_window.toLocaleString()}</div><div className="l">in the 4-year window</div><div className="d">dated per video (yt-dlp)</div></div>
          {funnel.kinds.map((k) => (<div className="stat" key={k.kind}><div className="v">{k.n}</div><div className="l">{k.kind}</div><div className="d">title classifier</div></div>))}
          <div className="stat"><div className="v">{funnel.sampled}</div><div className="l">sampled</div><div className="d">{funnel.per_year.map((y) => `${y.year_bucket}: ${y.sampled}`).join(' · ')}</div></div>
          <div className="stat"><div className="v">{funnel.indexed}</div><div className="l">transcripts indexed</div><div className="d">in transcript·lab</div></div>
        </div>
      )}
      {funnel && (
        <div className="panel"><h3>Per window year</h3>
          <table><thead><tr><th>window year</th><th className="num">videos</th><th className="num">single</th><th className="num">sampled</th><th className="num">indexed</th></tr></thead>
            <tbody>{funnel.per_year.map((y) => (<tr key={y.year_bucket}><td className="mono">{y.year_bucket}</td><td className="num">{y.videos}</td><td className="num">{y.single}</td><td className="num">{y.sampled}</td><td className="num">{y.indexed}</td></tr>))}</tbody></table>
        </div>
      )}
      <div className="filters">
        <button className={'pill ' + (sampleOnly ? 'on' : '')} onClick={() => setSampleOnly(true)}>sample only</button>
        <button className={'pill ' + (!sampleOnly ? 'on' : '')} onClick={() => setSampleOnly(false)}>every video in window</button>
        <select value={kind} onChange={(e) => setKind(e.target.value)}><option value="">any kind</option>{['single', 'multi', 'macro', 'other'].map((k) => <option key={k}>{k}</option>)}</select>
        <select value={year} onChange={(e) => setYear(e.target.value)}><option value="">any year</option>{years.map((y) => <option key={y}>{y}</option>)}</select>
        <input type="search" placeholder="search titles" value={q} onChange={(e) => setQ(e.target.value)} />
        <span className="microlabel">{rows.length} rows</span>
      </div>
      <div className="panel tablewrap">
        <table>
          <thead><tr><th>date</th><th>title</th><th>kind</th><th>ticker</th><th className="num">conf</th><th>year</th><th className="num">rank</th><th>transcript</th></tr></thead>
          <tbody>
            {rows.map((v) => (
              <tr key={v.video_id} className="click" onClick={() => onOpen(v.video_id)}>
                <td className="mono">{v.published_at}</td>
                <td>{v.title}<div className="microlabel" style={{ textTransform: 'none', letterSpacing: 0 }}>{v.rationale}</div></td>
                <td><span className={'badge ' + (KIND_BADGE[v.kind ?? 'unlabelled'] ?? '')}>{v.kind ?? '—'}</span></td>
                <td className="mono">{v.primary_ticker ?? (v.tickers.length ? v.tickers.map((t) => t.yahoo_ticker).join(', ') : '—')}</td>
                <td className="num">{v.confidence?.toFixed(2) ?? ''}</td>
                <td className="mono">{v.year_bucket}</td>
                <td className="num">{v.sample_rank ?? ''}</td>
                <td>{v.transcript_status === 'indexed' ? <span className="badge good">indexed · {v.transcript_segments} seg</span> : v.transcript_status === 'failed' ? <span className="badge bad">failed</span> : <span className="badge">none</span>}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {!rows.length && <div className="empty">nothing matches — or the catalog has not been built yet (<span className="mono">uv run vi catalog</span>).</div>}
      </div>
    </div></div>
  );
}
