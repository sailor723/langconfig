/**
 * Analysis store — the dashboard browser's state, shared by the LEFT sidebar and
 * the Analysis page.
 *
 * Same dependency-free pattern as graph-studio's studioStore (`useSyncExternalStore`):
 * the rail owns the list, search and filters; the page owns the viewer. Splitting
 * the two without a store would mean fetching `/api/analysis/dashboards` twice and
 * letting the two copies disagree about which page is open.
 */
import { useSyncExternalStore } from 'react';
import apiClient from '../../lib/api-client';

export interface DashboardFile {
  filename: string;
  path: string;
  size_bytes: number;
  created: string;
  db_path?: string | null;
  skills?: string[];
  mode?: string | null;
  entry?: string | null;
  /** Parsed server-side from the page's own <title>. */
  title?: string | null;
}

/** One database: the browser's unit. A database owns several pages and exactly
 *  one home page — the page a click on its name or card opens. */
export interface DbGroup {
  key: string;
  name: string;
  intro: string;
  home: DashboardFile | null;
  pages: number;
  latest: number;
  registered: boolean;
}

export interface AnalysisState {
  dashboards: DashboardFile[];
  databases: DbGroup[];
  loading: boolean;
  error: string | null;
  /** Free-text filter over title + filename. */
  query: string;
  /** Database family filter; 'all' = no filter. */
  db: string;
  /** Database currently selected in the rail ('all' = homepage). */
  activeDb: string | null;
  /** Filename of the page currently shown in the viewer. */
  activeFilename: string | null;
  /** Bumped to force the viewer to reload the same file. */
  reloadToken: number;
}

/** A page's family: its meta db_path when declared, else the filename prefix.
 *  Every generator in data/analysis_dbs names pages `<family>_<page>.html`. */
export function familyOf(d: DashboardFile): string {
  const fromMeta = (d.db_path || '').split('/').pop();
  if (fromMeta && fromMeta !== 'None') {
    return fromMeta.replace(/\.(db|sqlite3?)$/, '');
  }
  return d.filename.split('_')[0] || 'other';
}

const initialState: AnalysisState = {
  dashboards: [],
  databases: [],
  loading: false,
  error: null,
  query: '',
  db: 'all',
  activeDb: null,
  activeFilename: null,
  reloadToken: 0,
};

let state: AnalysisState = initialState;
const listeners = new Set<() => void>();

function setState(patch: Partial<AnalysisState>) {
  state = { ...state, ...patch };
  listeners.forEach(l => l());
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

function getSnapshot(): AnalysisState {
  return state;
}

export function useAnalysisState(): AnalysisState {
  return useSyncExternalStore(subscribe, getSnapshot);
}

export const analysis = {
  async loadDashboards() {
    setState({ loading: true, error: null });
    try {
      // Both levels in one round trip: the rail lists databases, the homepage
      // draws one card per database from the same payload.
      const [dbRes, pageRes] = await Promise.all([
        apiClient.get('/api/analysis/databases'),
        apiClient.get('/api/analysis/dashboards'),
      ]);
      const databases: DbGroup[] = Array.isArray(dbRes.data) ? dbRes.data : [];
      const rows: DashboardFile[] = Array.isArray(pageRes.data) ? pageRes.data : [];
      setState({ dashboards: rows, databases, loading: false });
      // Drop a selection that no longer exists (a page was deleted/renamed).
      const stillThere = rows.some(d => d.filename === state.activeFilename);
      const dbStillThere = databases.some(d => d.key === state.activeDb);
      setState({
        activeFilename: stillThere ? state.activeFilename : null,
        activeDb: dbStillThere ? state.activeDb : null,
      });
    } catch (e) {
      setState({
        loading: false,
        error: e instanceof Error ? e.message : 'failed to load dashboards',
      });
    }
  },

  /** Open a page in the viewer. Clicking the already-open page reloads it —
   *  dashboards are regenerated often, so "open" must mean "show the current
   *  file on disk", not "keep the cached iframe". */
  open(filename: string) {
    if (state.activeFilename === filename) {
      setState({ reloadToken: state.reloadToken + 1 });
    } else {
      setState({ activeFilename: filename, reloadToken: state.reloadToken + 1 });
    }
  },

  /** Select a database: the rail highlights it and the viewer opens its home
   *  page. A database with no home page still selects (the page shows a hint). */
  openDatabase(key: string) {
    const group = state.databases.find(d => d.key === key);
    state = { ...state, activeDb: key, activeFilename: group?.home?.filename ?? null };
    setState({});
    if (group?.home) {
      const same = state.activeFilename === group.home.filename;
      setState({ reloadToken: same ? state.reloadToken + 1 : state.reloadToken });
    }
  },

  /** Back to the homepage (one card per database). */
  openHome() {
    setState({ activeDb: null, activeFilename: null });
  },

  setQuery(query: string) {
    setState({ query });
  },

  setDb(db: string) {
    setState({ db });
  },
};

/** Visible rows for the current query + database filter. */
export function visibleDashboards(s: AnalysisState): DashboardFile[] {
  const q = s.query.trim().toLowerCase();
  return s.dashboards.filter(d => {
    if (s.db !== 'all' && familyOf(d) !== s.db) return false;
    if (!q) return true;
    return (
      (d.title || '').toLowerCase().includes(q) ||
      d.filename.toLowerCase().includes(q)
    );
  });
}

/** Database chips with counts, biggest family first. */
export function dbFilters(s: AnalysisState): { key: string; label: string; count: number }[] {
  const counts = new Map<string, number>();
  s.dashboards.forEach(d => {
    const f = familyOf(d);
    counts.set(f, (counts.get(f) || 0) + 1);
  });
  return [
    { key: 'all', label: '全部', count: s.dashboards.length },
    ...Array.from(counts.entries())
      .sort((a, b) => b[1] - a[1])
      .map(([key, count]) => ({ key, label: key, count })),
  ];
}
