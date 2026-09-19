import { useCallback, useEffect, useRef, useState } from 'react';
import { EditorView, basicSetup } from 'codemirror';
import { Compartment, Prec } from '@codemirror/state';
import { keymap } from '@codemirror/view';
import { sql, PostgreSQL } from '@codemirror/lang-sql';
import { HighlightStyle, syntaxHighlighting } from '@codemirror/language';
import { tags as t } from '@lezer/highlight';

type Col = { name: string; type: string };
type CatTable = { name: string; kind: string; rows: number | null; columns: Col[] };
type Catalog = { tables: CatTable[]; macros: { name: string; kind: string; doc: string }[]; examples: { title: string; sql: string }[] };
type Result = { columns: string[]; rows: unknown[][]; row_count: number; truncated: boolean; elapsed_ms: number; sql: string };
type Hist = { sql: string; at: string; rows?: number; ms?: number; error?: string };

const HISTORY_KEY = 'vi-sql-history';
const cssVar = (n: string, fb: string) => (typeof window === 'undefined' ? fb : getComputedStyle(document.documentElement).getPropertyValue(n).trim() || fb);

/** Editor chrome and syntax colours from the live design tokens, rebuilt on theme change (data-qa-agent's pattern). */
function makeTheme() {
  const bg = cssVar('--bg', '#0d1017'), text = cssVar('--text', '#e7ebf3'), panel2 = cssVar('--panel2', '#1b2130');
  const border = cssVar('--border', '#242936'), muted = cssVar('--muted', '#8a90a0'), accent = cssVar('--accent2', '#9db0ff');
  const good = cssVar('--good', '#3fb950'), warn = cssVar('--warn', '#d29922');
  const theme = EditorView.theme({
    '&': { fontSize: '12.5px', backgroundColor: bg, color: text, height: '100%' },
    '.cm-content': { caretColor: accent, fontFamily: 'var(--mono)' },
    '.cm-gutters': { backgroundColor: bg, color: muted, border: 'none', borderRight: `1px solid ${border}` },
    '.cm-activeLine, .cm-activeLineGutter': { backgroundColor: panel2 },
    '&.cm-focused .cm-selectionBackground, .cm-selectionBackground': { backgroundColor: cssVar('--accent-dim', '#171d33') },
    '&.cm-focused': { outline: 'none' },
  });
  const hl = HighlightStyle.define([
    { tag: t.keyword, color: accent, fontWeight: '600' },
    { tag: [t.string, t.special(t.string)], color: good },
    { tag: t.number, color: warn },
    { tag: t.comment, color: muted, fontStyle: 'italic' },
    { tag: [t.function(t.variableName), t.typeName], color: cssVar('--text2', '#c7ccd9') },
  ]);
  return [theme, syntaxHighlighting(hl)];
}

function loadHistory(): Hist[] { try { return JSON.parse(localStorage.getItem(HISTORY_KEY) || '[]'); } catch { return []; } }
function saveHistory(h: Hist[]) { try { localStorage.setItem(HISTORY_KEY, JSON.stringify(h.slice(0, 50))); } catch { /* private mode */ } }

export default function Sql({ initialSql }: { initialSql?: string }) {
  const host = useRef<HTMLDivElement>(null);
  const view = useRef<EditorView | null>(null);
  const themeComp = useRef(new Compartment());
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [result, setResult] = useState<Result | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  const [history, setHistory] = useState<Hist[]>(loadHistory);
  const [open, setOpen] = useState<Record<string, boolean>>({});

  const run = useCallback(async () => {
    const q = view.current?.state.doc.toString() ?? '';
    if (!q.trim()) return;
    setRunning(true); setError(null);
    try {
      const r = await fetch('/api/sql', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ sql: q }) });
      const body = await r.json();
      if (!r.ok) throw new Error(body.detail ?? r.statusText);
      setResult(body);
      setHistory((h) => { const n = [{ sql: q, at: new Date().toISOString(), rows: body.row_count, ms: body.elapsed_ms }, ...h.filter((x) => x.sql !== q)]; saveHistory(n); return n; });
    } catch (e) {
      const msg = String((e as Error).message ?? e);
      setError(msg); setResult(null);
      setHistory((h) => { const n = [{ sql: q, at: new Date().toISOString(), error: msg }, ...h.filter((x) => x.sql !== q)]; saveHistory(n); return n; });
    } finally { setRunning(false); }
  }, []);

  const setSql = (s: string) => { const v = view.current; if (!v) return; v.dispatch({ changes: { from: 0, to: v.state.doc.length, insert: s } }); v.focus(); };
  const insert = (s: string) => { const v = view.current; if (!v) return; const pos = v.state.selection.main.head; v.dispatch({ changes: { from: pos, insert: s }, selection: { anchor: pos + s.length } }); v.focus(); };

  useEffect(() => { fetch('/api/sql/catalog').then((r) => r.json()).then(setCatalog); }, []);
  useEffect(() => {
    if (!host.current || view.current) return;
    const schema: Record<string, string[]> = {};
    view.current = new EditorView({
      parent: host.current,
      doc: initialSql ?? "SELECT published_at, primary_ticker, title, year_bucket\nFROM vi.videos WHERE in_sample ORDER BY published_at",
      extensions: [
        basicSetup,
        sql({ dialect: PostgreSQL, schema, upperCaseKeywords: true }),
        themeComp.current.of(makeTheme()),
        Prec.highest(keymap.of([{ key: 'Mod-Enter', run: () => { void run(); return true; } }])),
      ],
    });
    const obs = new MutationObserver(() => view.current?.dispatch({ effects: themeComp.current.reconfigure(makeTheme()) }));
    obs.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });
    return () => { obs.disconnect(); view.current?.destroy(); view.current = null; };
  }, [initialSql, run]);
  useEffect(() => { if (initialSql && view.current) { setSql(initialSql); void run(); } }, [initialSql, run]);

  return (
    <div className="split sqlsplit">
      <aside className="rail">
        <div className="rail-head"><span className="microlabel">catalog · schema vi</span></div>
        {catalog?.tables.map((tb) => (
          <div key={tb.name} className="rentry" onClick={() => setOpen({ ...open, [tb.name]: !open[tb.name] })}>
            <div className="rq"><span className="mono">{tb.name}</span> <span className="badge">{tb.kind}{tb.rows != null ? ` · ${tb.rows.toLocaleString()}` : ''}</span></div>
            {open[tb.name] && <div className="cols">{tb.columns.map((c) => (<div key={c.name} className="rmeta col" onClick={(e) => { e.stopPropagation(); insert(c.name); }}>{c.name} <span style={{ opacity: .6 }}>{c.type.toLowerCase()}</span></div>))}</div>}
          </div>
        ))}
        <div className="rail-head" style={{ position: 'static' }}><span className="microlabel">macros</span></div>
        {catalog?.macros.map((m) => (<div key={m.name} className="rentry" onClick={() => insert(m.name)}><div className="rq mono">{m.name}</div><div className="rmeta">{m.doc}</div></div>))}
        <div className="rail-head" style={{ position: 'static' }}><span className="microlabel">examples</span></div>
        {catalog?.examples.map((ex) => (<div key={ex.title} className="rentry" onClick={() => setSql(ex.sql)}><div className="rq">{ex.title}</div></div>))}
        {!!history.length && <><div className="rail-head" style={{ position: 'static' }}><span className="microlabel">history · this browser</span></div>
          {history.slice(0, 15).map((h) => (<div key={h.at} className="rentry" onClick={() => setSql(h.sql)}><div className="rq mono" style={{ whiteSpace: 'pre', overflow: 'hidden', textOverflow: 'ellipsis' }}>{h.sql.split('\n')[0]}</div><div className="rmeta">{h.error ? <span style={{ color: 'var(--bad)' }}>error</span> : `${h.rows} rows · ${h.ms} ms`} · {h.at.slice(0, 16).replace('T', ' ')}</div></div>))}</>}
      </aside>
      <div className="sqlmain">
        <div className="sqltoolbar">
          <button className="btn pri" onClick={() => void run()} disabled={running}>{running ? 'running…' : 'Run'} <span className="kbd">⌘⏎</span></button>
          <span className="microlabel">read-only · one SELECT · {`≤ 1000 rows`} · 20 s</span>
          <span className="spacer" />
          {result && <span className="microlabel">{result.row_count.toLocaleString()} rows{result.truncated ? ' (truncated)' : ''} · {result.elapsed_ms} ms</span>}
        </div>
        <div className="editor" ref={host} />
        {error && <div className="note warn" style={{ margin: '8px 12px' }}>{error}</div>}
        <div className="results tablewrap">
          {result && (
            <table>
              <thead><tr>{result.columns.map((c) => <th key={c}>{c}</th>)}</tr></thead>
              <tbody>{result.rows.map((r, i) => (<tr key={i}>{r.map((v, j) => <td key={j} className={typeof v === 'number' ? 'num' : 'mono'}>{v == null ? <span style={{ opacity: .4 }}>∅</span> : typeof v === 'number' ? (Number.isInteger(v) ? v.toLocaleString() : v.toLocaleString(undefined, { maximumFractionDigits: 4 })) : String(v)}</td>)}</tr>))}</tbody>
            </table>
          )}
          {!result && !error && <div className="empty">pick an example on the left, or write a query and press ⌘⏎</div>}
        </div>
      </div>
    </div>
  );
}
