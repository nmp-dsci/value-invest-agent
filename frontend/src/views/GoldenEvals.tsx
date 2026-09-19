import { useEffect, useMemo, useState } from 'react';
import { api, type Bucket, type EvalDetail, type EvalRow, type EvalSummary } from '../api';
import EvalPanel, { POS } from './EvalPanel';

const H = ['6', '12', '24'];
const hit = (b: Bucket | undefined, cls: string) => { const h = b?.hits?.[cls]; return h && h[1] ? `${h[0]}/${h[1]}` : '—'; };
const ex = (v: number | null | undefined) => v == null ? '—' : `${v > 0 ? '+' : ''}${v.toFixed(0)}`;
const pp = (v: number | null | undefined) => v == null ? '—' : `${v > 0 ? '+' : ''}${(v * 100).toFixed(1)}`;
/** D15: train / test are stamped per video; holdout is the state at a horizon whose outcome is not in the price table yet. */
const splitAt = (r: EvalRow, h: string) => (r.validations?.[h] ? r.split : 'holdout');
const splitCls = (s: string) => (s === 'holdout' ? 'warn' : s === 'test' ? 'acc' : '');
const vwx = (b: Bucket | undefined) => (b ? `${b.verdict.correct} · ${b.verdict.wrong} · ${b.verdict.indeterminate}` : '—');
const hits3 = (b: Bucket | undefined) => (b ? `${hit(b, 'BUY')} · ${hit(b, 'HOLD')} · ${hit(b, 'SELL')}` : '—');

export default function GoldenEvals({ videoId, onOpen, onVideo }: { videoId?: string; onOpen: (id: string) => void; onVideo: (id: string) => void }) {
  const [rows, setRows] = useState<EvalRow[]>([]);
  const [sum, setSum] = useState<EvalSummary | null>(null);
  const [detail, setDetail] = useState<EvalDetail | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [f, setF] = useState({ year: '', position: '', split: '', status: '', q: '', rs: false, iv: false });
  const [h, setH] = useState('12');
  const load = () => { api.evals().then(setRows).catch((e) => setErr(String(e))); api.evalSummary().then(setSum).catch(() => setSum(null)); };
  useEffect(load, []);
  useEffect(() => { if (!videoId) { setDetail(null); return; } api.eval(videoId).then(setDetail).catch((e) => setErr(String(e))); }, [videoId]);
  const years = useMemo(() => [...new Set(rows.map((r) => r.year_bucket))].sort(), [rows]);
  const list = useMemo(() => rows.filter((r) => (!f.year || r.year_bucket === f.year) && (!f.position || r.position === f.position) && (!f.split || splitAt(r, h) === f.split) && (!f.status || r.curation_status === f.status) && (!f.rs || r.rule_sensitive) && (!f.iv || r.iv_weighted_stated != null) && (!f.q || r.title.toLowerCase().includes(f.q.toLowerCase()) || r.ticker.toLowerCase().includes(f.q.toLowerCase()))), [rows, f, h]);
  const overall = sum?.validation.overall ?? {};
  const st = sum?.stats ?? {};
  const cuts = (rule: string) => (sum?.cuts ?? []).filter((c) => c.rule.startsWith(rule)).map((c) => `${c.label} ${c.n}`).join(' · ');
  const seed = sum?.seed_eval_v0; const kappa = sum?.kappa;
  return (
    <div className="scroll"><div className="pagewrap">
      <h1 className="h1">Golden Evals — his call, his reasons, and what the stock did next</h1>
      <p className="sub">One eval per sampled video, extracted from the transcript by the Agent SDK (extractor v0 → Sonnet, critic → Opus), grounded in the point-in-time data, validated against the index at T0 + 6 / 12 / 24 m. Position is <b>BUY / HOLD / SELL</b> from his 6-way stance (rule C); the binary and hurdle views are shown as alternative cuts. Verdict bands: buy right if it beat the benchmark by &gt; 5 pp, sell right if it lagged by &gt; 5 pp, hold right within ±10 pp.</p>
      {err && <div className="note warn">{err}</div>}
      {!rows.length && !err && <div className="empty">no evals yet — run <span className="mono">uv run vi extract</span> then <span className="mono">uv run vi validate</span></div>}
      {sum && rows.length > 0 && (
        <>
          <div className="filters" style={{ marginBottom: 6 }}><span className="microlabel">insights · horizon</span>{H.map((x) => <button key={x} className={'pill ' + (h === x ? 'on' : '')} onClick={() => setH(x)}>+{x} m</button>)}<span className="microlabel">n = {overall[h]?.n ?? 0} evals old enough</span></div>
          <div className="stats">
            {(['BUY', 'HOLD', 'SELL'] as const).map((cls) => { const b = overall[h]; const hh = b?.hits?.[cls]; return (
              <div className="stat" key={cls}><div className={'v ' + (hh && hh[1] && hh[0] / hh[1] >= 0.5 ? 'good' : '')} style={{ color: POS[cls] === 'good' ? 'var(--good)' : POS[cls] === 'bad' ? 'var(--bad)' : 'var(--accent2)' }}>{hit(b, cls)}</div><div className="l">{cls} calls right @ {h} m</div><div className="d">{cls === 'BUY' ? 'beat index by > 5 pp' : cls === 'SELL' ? 'lagged index by > 5 pp' : 'within ±10 pp'} · mean excess {ex(b?.mean_excess?.[cls])} pp</div></div>); })}
            <div className="stat"><div className="v">{overall[h]?.verdict?.correct ?? 0} · {overall[h]?.verdict?.wrong ?? 0} · {overall[h]?.verdict?.indeterminate ?? 0}</div><div className="l">correct · wrong · indeterminate</div><div className="d">HOLD as "did not lag": {overall[h]?.verdict_hold_alt?.correct ?? 0} correct</div></div>
            <div className="stat"><div className="v">{overall[h]?.iv_hit?.[1] ? `${overall[h].iv_hit[0]} / ${overall[h].iv_hit[1]}` : '—'}</div><div className="l">intrinsic value reached</div><div className="d">{st.with_iv ?? 0} of {st.n ?? 0} evals state an IV</div></div>
            <div className="stat"><div className="v">{st.n ?? 0}</div><div className="l">evals · {st.reviewed ?? 0} reviewed</div><div className="d">3-way {cuts('C')} · binary {cuts('A')} · hurdle {cuts('B')}</div></div>
            <div className="stat"><div className="v">{Math.round(((st.reproducible_share as number) ?? 0) * 100)} %</div><div className="l">reasons reproducible at T0</div><div className="d">{(sum.reproducible ?? []).map((r) => `${r.reproducible} ${r.n}`).join(' · ')}</div></div>
            <div className="stat"><div className="v">{st.critic_n ? `${st.critic_agrees} / ${st.critic_n}` : '—'}</div><div className="l">critic agrees on position</div><div className="d">κ 6-way {kappa?.kappa_6way ?? '—'} · 3-way {kappa?.kappa_3way ?? '—'} · quotes verbatim {Math.round(((st.faithful_share as number) ?? 0) * 100)} %</div></div>
            <div className="stat"><div className="v">{seed?.position_accuracy_full != null ? `${Math.round(seed.position_accuracy_full * 100)} %` : '—'}</div><div className="l">seed position accuracy ({seed?.n_full ?? 0} read in full)</div><div className="d">balanced {seed?.balanced_full?.balanced_accuracy ?? '—'} · stance {seed?.stance_accuracy_full != null ? Math.round(seed.stance_accuracy_full * 100) + ' %' : '—'} · reason recall {seed?.reason_recall ?? '—'}</div></div>
            <div className="stat"><div className="v">{st.price_n ? `${st.price_ok} / ${st.price_n}` : '—'}</div><div className="l">price he quotes ≈ close at T0</div><div className="d">IV recomputed within ±10 %: {st.iv_ok ?? 0} / {st.iv_compared ?? 0} · base metric gap &gt; 15 %: {st.base_gap_over_15 ?? 0}</div></div>
          </div>
          <div className="panel tablewrap" style={{ maxHeight: 'none' }}>
            <h3>Per window year · train / test / holdout @ {h} m <span className="microlabel">train · test fixed per video (seeded, {Math.round((sum.validation.test_share ?? 0.3) * 100)} % test inside every year) · holdout = outcome not yet in the price table at +{h} m</span></h3>
            <table><thead><tr><th>year</th><th className="num">n</th><th className="num">BUY / HOLD / SELL</th><th className="num">train · test</th><th className="num">@ {h} m: train · test · holdout</th><th className="num">train ✓ · ✗ · ~</th><th className="num">test ✓ · ✗ · ~</th><th className="num">train right B · H · S</th><th className="num">test right B · H · S</th><th className="num">reviewed</th><th className="num">rule-sens.</th></tr></thead>
              <tbody>{sum.mix.map((m) => { const sa = sum.validation.split_at?.[h]?.by_year?.[m.year_bucket] ?? {}; return (
                <tr key={m.year_bucket}><td className="mono">{m.year_bucket}</td><td className="num">{m.n}</td><td className="num">{m.buy} / {m.hold} / {m.sell}</td><td className="num">{m.train} · <span style={{ color: 'var(--accent2)' }}>{m.test}</span></td>
                  <td className="num">{sa.train?.n ?? 0} · <span style={{ color: 'var(--accent2)' }}>{sa.test?.n ?? 0}</span> · <span style={{ color: 'var(--warn)' }}>{sa.holdout?.n ?? 0}</span></td>
                  <td className="num">{vwx(sa.train)}</td><td className="num">{vwx(sa.test)}</td><td className="num">{hits3(sa.train)}</td><td className="num">{hits3(sa.test)}</td>
                  <td className="num">{m.reviewed}</td><td className="num">{m.rule_sensitive}</td>
                </tr>); })}
                {(() => { const sa = sum.validation.split_at?.[h]?.overall ?? {}; const sp = sum.validation.splits ?? {}; return (
                <tr><td><b>all</b></td><td className="num"><b>{st.n}</b></td><td className="num"><b>{cuts('C').replace(/[A-Z]+ /g, '').replace(/ · /g, ' / ')}</b></td><td className="num"><b>{sp.train ?? 0} · <span style={{ color: 'var(--accent2)' }}>{sp.test ?? 0}</span></b></td>
                  <td className="num"><b>{sa.train?.n ?? 0} · <span style={{ color: 'var(--accent2)' }}>{sa.test?.n ?? 0}</span> · <span style={{ color: 'var(--warn)' }}>{sa.holdout?.n ?? 0}</span></b></td>
                  <td className="num"><b>{vwx(sa.train)}</b></td><td className="num"><b>{vwx(sa.test)}</b></td><td className="num"><b>{hits3(sa.train)}</b></td><td className="num"><b>{hits3(sa.test)}</b></td>
                  <td className="num">{st.reviewed}</td><td className="num">{st.rule_sensitive}</td>
                </tr>); })()}
              </tbody></table>
            <p className="note" style={{ marginBottom: 0 }}>The agent (M3) is tuned on <b>train</b> and gated on <b>test</b> across the same years, so it is checked on history it never saw. <b>Holdout</b> is not a label — it is every eval whose +{h} m close has not happened yet; pick +6 m and most of it resolves, pick +24 m and the last two window years are still open.</p>
          </div>
          {sum.method_summary && (
            <div className="panel"><h3>His method, distilled <span className="microlabel">method_summary.json · n = {sum.method_summary.n_evals}</span></h3>
              <div className="mono" style={{ fontSize: 'var(--t-1)', color: 'var(--text2)', lineHeight: 1.7 }}>
                discount rate {Object.entries(sum.method_summary.discount_rate ?? {}).map(([k, n]) => `${k} ×${n}`).join(', ') || '—'} · base metric {Object.entries(sum.method_summary.base_metric ?? {}).map(([k, n]) => `${k} ×${n}`).join(', ') || '—'}<br />
                terminal P/E median: {Object.entries(sum.method_summary.terminal_multiple ?? {}).map(([k, v]: any) => `${k} ${v?.median ?? '—'} (n ${v?.n ?? 0})`).join(' · ') || '—'} · by growth bucket: {Object.entries(sum.method_summary.terminal_multiple_by_growth_bucket ?? {}).map(([k, v]: any) => `${k} → ${v?.median ?? '—'}`).join(' · ') || '—'}<br />
                scenario probability median: {Object.entries(sum.method_summary.scenario_probability ?? {}).map(([k, v]: any) => `${k} ${v?.median ?? '—'}`).join(' · ') || '—'} · expected return by stance: {Object.entries(sum.method_summary.expected_return_by_stance ?? {}).map(([k, v]: any) => `${k} ${v?.median ?? '—'} %`).join(' · ') || '—'}<br />
                reasons for BUY: {Object.entries(sum.method_summary.reason_categories?.for_buy ?? {}).slice(0, 5).map(([k, n]) => `${k} ${n}`).join(', ') || '—'} · for SELL: {Object.entries(sum.method_summary.reason_categories?.for_sell ?? {}).slice(0, 5).map(([k, n]) => `${k} ${n}`).join(', ') || '—'} · feeds: {Object.entries(sum.method_summary.reason_feeds ?? {}).map(([k, n]) => `${k} ${n}`).join(', ')}
              </div>
            </div>
          )}
        </>
      )}
      {detail && (
        <div className="panel" id="evaldetail">
          <h3>{detail.ticker} · {detail.t0} — {detail.title} <span className="microlabel">{detail.year_bucket} · {detail.extractor_version} · {detail.model}</span><button className="pill" onClick={() => onVideo(detail.video_id)}>open video ↗</button><button className="pill" onClick={() => onOpen('')}>close</button></h3>
          <EvalPanel ev={detail} onJump={() => onVideo(detail.video_id)} onChanged={(e) => { setDetail({ ...detail, ...e } as EvalDetail); load(); }} />
        </div>
      )}
      {rows.length > 0 && (
        <div className="panel tablewrap" style={{ maxHeight: 'none' }}>
          <div className="filters">
            <input type="search" placeholder="ticker or title" value={f.q} onChange={(e) => setF({ ...f, q: e.target.value })} />
            <select value={f.year} onChange={(e) => setF({ ...f, year: e.target.value })}><option value="">any year</option>{years.map((y) => <option key={y}>{y}</option>)}</select>
            <select value={f.position} onChange={(e) => setF({ ...f, position: e.target.value })}><option value="">any position</option>{['BUY', 'HOLD', 'SELL'].map((p) => <option key={p}>{p}</option>)}</select>
            <select value={f.split} onChange={(e) => setF({ ...f, split: e.target.value })}><option value="">any split</option>{['train', 'test', 'holdout'].map((p) => <option key={p}>{p}</option>)}</select>
            <select value={f.status} onChange={(e) => setF({ ...f, status: e.target.value })}><option value="">any status</option>{['auto', 'reviewed', 'rejected'].map((p) => <option key={p}>{p}</option>)}</select>
            <button className={'pill ' + (f.rs ? 'on' : '')} onClick={() => setF({ ...f, rs: !f.rs })}>rule-sensitive</button>
            <button className={'pill ' + (f.iv ? 'on' : '')} onClick={() => setF({ ...f, iv: !f.iv })}>has IV</button>
            <span className="microlabel">{list.length} of {rows.length}</span>
          </div>
          <table><thead><tr><th>ticker · T0</th><th>title</th><th>split @ {h} m</th><th>position</th><th>stance</th><th className="num">expects</th><th className="num">IV → price</th>{H.map((x) => <th key={x} className="num">+{x} m ex</th>)}<th>verdict @ {h} m</th><th className="num">repro.</th><th>critic</th><th>review</th></tr></thead>
            <tbody>{list.map((r) => { const v = r.validations?.[h]; return (
              <tr key={r.video_id} className="click" onClick={() => onOpen(r.video_id)}>
                <td className="mono" style={{ whiteSpace: 'nowrap' }}><b>{r.ticker}</b> · {r.t0}</td><td>{r.title}</td><td><span className={'badge ' + splitCls(splitAt(r, h))}>{splitAt(r, h)}</span></td>
                <td><span className={'badge ' + POS[r.position]}>{r.position}</span>{r.rule_sensitive && <span className="badge warn" style={{ marginLeft: 4 }}>A≠B</span>}{r.title_says_buy && r.position !== 'BUY' && <span className="badge warn" style={{ marginLeft: 4 }}>title</span>}</td>
                <td className="mono">{r.stance_detail}</td><td className="num">{r.expected_return_pct != null ? `${r.expected_return_pct} %` : '—'}</td>
                <td className="num">{r.iv_weighted_stated != null ? `${r.iv_weighted_stated.toFixed(0)} → ${r.price_at_t0?.toFixed(0) ?? '—'}` : '—'}</td>
                {H.map((x) => { const vv = r.validations?.[x]; return <td key={x} className="num" style={{ color: vv ? (vv.excess > 0.05 ? 'var(--good)' : vv.excess < -0.05 ? 'var(--bad)' : 'var(--muted)') : 'var(--dim)' }}>{vv ? pp(vv.excess) : '—'}</td>; })}
                <td>{v ? <span className={'badge ' + (v.verdict === 'correct' ? 'good' : v.verdict === 'wrong' ? 'bad' : '')}>{v.verdict}</span> : <span className="badge">too recent</span>}</td>
                <td className="num">{Math.round((r.checks?.reproducible_share ?? 0) * 100)} %</td>
                <td>{r.critic ? (r.critic.position_agrees ? <span className="badge good">agrees</span> : <span className="badge bad">{r.critic.own_stance_detail}</span>) : '—'}</td>
                <td><span className={'badge ' + (r.curation_status === 'reviewed' ? 'good' : r.curation_status === 'rejected' ? 'bad' : '')}>{r.curation_status}</span></td>
              </tr>); })}</tbody></table>
        </div>
      )}
    </div></div>
  );
}
