import { useEffect, useState } from 'react';
import { api } from './api';
import Corpus from './views/Corpus';
import VideoView from './views/Video';
import Market from './views/Market';
import Sql from './views/Sql';

type Tab = 'corpus' | 'video' | 'market' | 'sql' | 'golden' | 'agent' | 'scoreboard';
const TABS: { id: Tab; label: string; stub?: string }[] = [
  { id: 'corpus', label: 'Corpus' },
  { id: 'video', label: 'Video' },
  { id: 'market', label: 'Market' },
  { id: 'sql', label: 'SQL' },
  { id: 'golden', label: 'Golden calls', stub: 'M2 — golden extraction + review' },
  { id: 'agent', label: 'Agent runs', stub: 'deferred until the M2 review passes' },
  { id: 'scoreboard', label: 'Scoreboard', stub: 'deferred until the M2 review passes' },
];

function readHash(): { tab: Tab; id?: string; q?: string } {
  const raw = location.hash.replace(/^#\/?/, '');
  const [path, query] = raw.split('?');
  const [tab, id] = path.split('/');
  const known = TABS.find((t) => t.id === tab);
  const q = query ? new URLSearchParams(query).get('q') ?? undefined : undefined;
  return { tab: (known ? known.id : 'corpus') as Tab, id, q };
}

export default function App() {
  const [route, setRoute] = useState(readHash());
  const [health, setHealth] = useState<{ mode: string; tables: Record<string, number> } | null>(null);
  const [theme, setTheme] = useState(document.documentElement.dataset.theme ?? 'dark');
  useEffect(() => {
    const on = () => setRoute(readHash());
    window.addEventListener('hashchange', on);
    return () => window.removeEventListener('hashchange', on);
  }, []);
  useEffect(() => { api.health().then(setHealth).catch(() => setHealth(null)); }, []);
  const go = (tab: Tab, id?: string) => { location.hash = id ? `#/${tab}/${id}` : `#/${tab}`; };
  const flip = () => {
    const t = theme === 'dark' ? 'light' : 'dark';
    document.documentElement.dataset.theme = t; setTheme(t);
    try { localStorage.setItem('vi-theme', t); } catch { /* private mode */ }
  };
  const cur = TABS.find((t) => t.id === route.tab)!;
  return (
    <div className="app">
      <div className="topbar">
        <span className="brand">
          <svg className="logo" viewBox="0 0 32 32" aria-hidden="true"><rect width="32" height="32" rx="7" fill="var(--good-dim)" /><path d="M8.5 16.5l5 5 10-11" fill="none" stroke="var(--good)" strokeWidth="3.5" strokeLinecap="round" strokeLinejoin="round" /></svg>
          value·<em>invest</em>
        </span>
        <nav className="nav">
          {TABS.map((t) => (
            <button key={t.id} className={(route.tab === t.id ? 'on ' : '') + (t.stub ? 'stub' : '')} onClick={() => go(t.id)}>{t.label}</button>
          ))}
        </nav>
        <span className="spacer" />
        <span className="topstat">
          {health ? (<><span>mode <b>{health.mode}</b></span><span>videos <b>{health.tables.videos}</b></span><span>prices <b>{health.tables.prices}</b></span><span>statements <b>{health.tables.statements}</b></span></>) : <span>api offline</span>}
        </span>
        <button className="themetoggle" onClick={flip}>{theme === 'dark' ? 'light' : 'dark'}</button>
      </div>
      <div className="view">
        {route.tab === 'corpus' && <Corpus onOpen={(id) => go('video', id)} />}
        {route.tab === 'video' && <VideoView videoId={route.id} onSelect={(id) => go('video', id)} />}
        {route.tab === 'market' && <Market onOpen={(id) => go('video', id)} />}
        {route.tab === 'sql' && <Sql initialSql={route.q} />}
        {cur.stub && (
          <div className="stub"><h2>{cur.label}</h2><p>{cur.stub}. This tab exists so the walkthrough shows where the later data lands; nothing here is built yet.</p></div>
        )}
      </div>
    </div>
  );
}
