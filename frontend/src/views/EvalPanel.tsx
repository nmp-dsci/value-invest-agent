import { useState } from 'react';
import { api, type EvalDetail, type Reason } from '../api';

export const POS: Record<string, string> = { BUY: 'good', HOLD: 'acc', SELL: 'bad' };
export const REPRO: Record<string, string> = { statements: 'good', prices: 'good', derived: 'good', external: 'bad', judgement: '' };
export const ts = (s: number | null | undefined) => s == null ? '' : `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, '0')}`;
const pct = (v: number | null | undefined, d = 1) => v == null ? '—' : `${(v * 100).toFixed(d)} %`;
const num = (v: number | null | undefined, d = 2) => v == null ? '—' : v.toFixed(d);
const fmtVal = (v: number | null | undefined, unit?: string | null) => {
  if (v == null) return '—';
  if (Math.abs(v) >= 1e9) return (v / 1e9).toFixed(1) + ' B';
  if (Math.abs(v) >= 1e6) return (v / 1e6).toFixed(0) + ' M';
  if (Math.abs(v) < 1 && unit !== 'per_share') return (v * 100).toFixed(1) + ' %';
  return v.toFixed(2);
};

export function ReasonList({ reasons, onJump }: { reasons: Reason[]; onJump?: (chunkId: string | null, startS: number | null) => void }) {
  return (
    <div className="reasons">
      {reasons.map((r) => (
        <div className="reason" key={r.rank}>
          <div className="rhead">
            <span className={'badge ' + (r.direction === 'for_buy' ? 'good' : 'bad')}>{r.rank} · {r.direction === 'for_buy' ? 'for BUY' : 'for SELL'}</span>
            <span className="badge">{r.category}</span>
            {r.feeds !== 'none' && <span className="badge acc">feeds {r.feeds}</span>}
            {r.data_check && <span className={'badge ' + (REPRO[r.data_check.reproducible] ?? '')} title={r.data_check.formula ?? ''}>{r.data_check.reproducible}{r.data_check.agrees === true ? ' ✓' : r.data_check.agrees === false ? ' ✗' : ''}</span>}
            {r.start_s != null && <button className="pill" onClick={() => onJump?.(r.chunk_id, r.start_s)}>▶ {ts(r.start_s)}</button>}
          </div>
          <div className="rclaim">{r.claim}</div>
          <div className="rquote">"{r.quote}"</div>
          {r.data_check && (r.data_check.value_stated != null || r.data_check.gap_note) && (
            <div className="rcheck mono">
              {r.data_check.value_stated != null && <span>he says {fmtVal(r.data_check.value_stated, r.data_check.formula?.includes('EPS') ? 'per_share' : undefined)} · as-of {fmtVal(r.data_check.value_as_of)} ({r.data_check.as_of_period}) · {r.data_check.formula}</span>}
              {r.data_check.gap_note && <span className="dim"> · {r.data_check.gap_note}</span>}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

export default function EvalPanel({ ev, compact, onJump, onChanged }: { ev: EvalDetail; compact?: boolean; onJump?: (chunkId: string | null, startS: number | null) => void; onChanged?: (e: Partial<EvalDetail>) => void }) {
  const [note, setNote] = useState(ev.review_note ?? '');
  const [stance, setStance] = useState(ev.stance_detail);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const v = ev.valuation;
  const ivr = ev.iv_recomputed ?? {};
  const submit = async (status: string) => {
    setBusy(true); setMsg(null);
    try {
      const r = await api.review(ev.video_id, { curation_status: status, note, stance_detail: stance !== ev.stance_detail ? stance : undefined });
      setMsg(`saved: ${r.curation_status} · ${r.stance_detail} → ${r.position}`);
      onChanged?.({ curation_status: r.curation_status, stance_detail: r.stance_detail, position: r.position as EvalDetail['position'] });
    } catch (e) { setMsg(String(e)); } finally { setBusy(false); }
  };
  return (
    <div className="evalpanel">
      <div className="vhead">
        <span className={'badge big ' + POS[ev.position]}>{ev.position}</span>
        <span className="badge">{ev.stance_detail}</span>
        <span className="badge">he: {ev.personal_action}</span>
        {ev.expected_return_pct != null && <span className="badge">expects {ev.expected_return_pct} % / yr</span>}
        <span className="badge">{ev.conviction}</span>
        {ev.rule_sensitive && <span className="badge warn" title={`binary ${ev.binary_position} · hurdle ${ev.hurdle_position}`}>rule-sensitive</span>}
        {ev.title_says_buy && ev.position !== 'BUY' && <span className="badge warn">title says buy</span>}
        <span className={'badge ' + (ev.curation_status === 'reviewed' ? 'good' : ev.curation_status === 'rejected' ? 'bad' : '')}>{ev.curation_status}</span>
        <span className="badge acc">{ev.split}</span>
      </div>
      <div className="rquote" style={{ marginBottom: 10 }}>"{ev.headline_quote}"</div>
      {!compact && (
        <div className="grid2" style={{ gridTemplateColumns: 'minmax(0,1fr) minmax(0,1fr)' }}>
          <div className="panel" style={{ margin: 0 }}>
            <h3>Valuation <span className="microlabel">{v.method} · r {pct(v.discount_rate, 0)} · base {v.base_metric?.name} {num(v.base_metric?.value_stated)}{ivr.base_metric ? ` (as-of ${num(ivr.base_metric.as_of)} ${ivr.base_metric.period}${ivr.base_metric.gap_pct != null ? `, ${ivr.base_metric.gap_pct > 0 ? '+' : ''}${ivr.base_metric.gap_pct} %` : ''})` : ''}</span></h3>
            {v.scenarios.length ? (
              <table><thead><tr><th>scenario</th><th className="num">g y1–5</th><th className="num">g y6–10</th><th className="num">P/E</th><th className="num">p</th><th className="num">he says</th><th className="num">recomputed</th></tr></thead>
                <tbody>{v.scenarios.map((sc) => { const rc = (ivr.scenarios ?? []).find((x: any) => x.name === sc.name); return (
                  <tr key={sc.name}><td>{sc.name}</td><td className="num">{pct(sc.g_y1_5, 0)}</td><td className="num">{pct(sc.g_y6_10, 0)}</td><td className="num">{num(sc.terminal_multiple, 0)}</td><td className="num">{sc.probability == null ? '—' : sc.probability}</td><td className="num">{num(sc.iv_stated, 0)}</td><td className="num">{rc?.iv_model != null ? `${rc.iv_model.toFixed(0)} ${rc.ok === true ? '✓' : rc.ok === false ? '✗' : ''}` : '—'}</td></tr>); })}</tbody></table>
            ) : <div className="empty" style={{ padding: 10 }}>no valuation in this video</div>}
            <div className="mono" style={{ fontSize: 'var(--t-1)', color: 'var(--muted)', marginTop: 6 }}>
              weighted IV he says {num(v.iv_weighted_stated, 0)} · recomputed {num(ivr.iv_weighted_model, 0)} · price mentioned {num(v.price_mentioned, 0)} · close at T0 {num(ev.price_at_t0)} {ev.checks?.price_check === true ? '✓' : ev.checks?.price_check === false ? '✗ price check' : ''}
              {ev.checks?.iv_comparable != null && <><br />comparable IV {num(ev.checks.iv_comparable, 0)} ({ev.checks.iv_basis}{ev.checks.split_factor && ev.checks.split_factor !== 1 ? `, ÷ split ${ev.checks.split_factor}` : ''}) → upside {ev.checks.iv_upside_pct > 0 ? '+' : ''}{num(ev.checks.iv_upside_pct, 0)} % → rule D {ev.checks.position_iv ?? 'no call'}{ev.checks.position_iv && ev.checks.position_iv !== ev.position ? ' ≠ his ' + ev.position : ''}</>}
              {ivr.expected_return_at_price != null && <> · expected return at price <b>{ivr.expected_return_at_price} %</b></>}
              {v.what_is_priced_in && (v.what_is_priced_in.growth != null || v.what_is_priced_in.multiple != null) && <> · priced in: {pct(v.what_is_priced_in.growth, 0)} growth at P/E {num(v.what_is_priced_in.multiple, 0)}</>}
            </div>
          </div>
          <div className="panel" style={{ margin: 0 }}>
            <h3>Checks <span className="microlabel">grounding · critic</span></h3>
            <dl className="kv">
              <dt>reproducible</dt><dd>{Math.round((ev.checks?.reproducible_share ?? 0) * 100)} % of reasons · {Object.entries(ev.checks?.reproducible_counts ?? {}).filter(([, n]) => n).map(([k, n]) => `${k} ${n}`).join(' · ')}</dd>
              <dt>numbers checked</dt><dd>{ev.checks?.metrics_agree ?? 0} / {ev.checks?.metrics_compared ?? 0} agree within 15 %</dd>
              <dt>IV recomputed</dt><dd>{ev.checks?.iv_ok ?? 0} / {ev.checks?.iv_compared ?? 0} within ±10 %</dd>
              <dt>quotes verbatim</dt><dd>{Math.round((ev.checks?.faithful_share ?? 0) * 100)} % · critic {ev.critic ? (ev.critic.faithful ? 'faithful' : 'NOT faithful') : '—'}{ev.critic?.invented_reasons?.length ? ` · invented: ${ev.critic.invented_reasons.join(', ')}` : ''}</dd>
              <dt>critic stance</dt><dd>{ev.critic ? `${ev.critic.own_stance_detail} ${ev.critic.position_agrees ? '· agrees' : '· DISAGREES'}` : '—'}{ev.critic?.notes && ev.critic.notes !== 'ok' ? ` — ${ev.critic.notes}` : ''}</dd>
              <dt>latest FY at T0</dt><dd>{ev.checks?.latest_fy_visible ?? '—'}</dd>
              <dt>external facts</dt><dd style={{ color: 'var(--muted)' }}>{(ev.external_facts ?? []).join(' · ') || '—'}</dd>
            </dl>
          </div>
        </div>
      )}
      <ReasonList reasons={ev.reasons} onJump={onJump} />
      {ev.validations?.length ? (
        <div className="fwd">
          {ev.validations.map((x) => (
            <div className="stat" key={x.horizon_m}><div className="v" style={{ color: x.verdict === 'correct' ? 'var(--good)' : x.verdict === 'wrong' ? 'var(--bad)' : 'var(--muted)' }}>{x.excess > 0 ? '+' : ''}{(x.excess * 100).toFixed(1)} pp</div><div className="l">+{x.horizon_m} m vs index · {x.verdict}{x.iv_hit != null ? (x.iv_hit ? ' · IV reached' : ' · IV not reached') : ''}</div></div>
          ))}
        </div>
      ) : null}
      <div className="review">
        <select value={stance} onChange={(e) => setStance(e.target.value)}>{['absolute_buy', 'relative_buy', 'fair_hold', 'avoid', 'too_hard', 'short'].map((s) => <option key={s}>{s}</option>)}</select>
        <input type="search" placeholder="review note" value={note} onChange={(e) => setNote(e.target.value)} style={{ flex: 1, minWidth: 160 }} />
        <button className="btn pri" disabled={busy} onClick={() => submit('reviewed')}>accept{stance !== ev.stance_detail ? ' with edit' : ''}</button>
        <button className="btn" disabled={busy} onClick={() => submit('rejected')}>reject</button>
        {msg && <span className="mono" style={{ fontSize: 'var(--t-1)', color: 'var(--muted)' }}>{msg}</span>}
      </div>
    </div>
  );
}
