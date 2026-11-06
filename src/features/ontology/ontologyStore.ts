/**
 * ontologyStore — the ontologies this account can open, and the one currently selected.
 *
 * WHERE THE LIST COMES FROM: the `ontology` settings namespace (Settings → Ontology), so
 * which profiles exist is a decision someone made rather than four URLs compiled into the
 * bundle. The built-in list below is only a fallback for a first run before the settings
 * document is seeded — it is labelled as such in the UI's error path, never silently mixed in.
 *
 * Three facts are kept apart because they come from three places: the selected URL
 * (localStorage), whether that workbench answers (a fetch of /api/ontology), and what it
 * declares (the document that same call returns). The document is replaced on every profile
 * switch and never merged — a browser showing clinic declarations under a TPC-H header is
 * the failure mode this tool exists to prevent.
 */
import { useEffect, useReducer } from 'react';
import apiClient from '../../lib/api-client';

export interface OntologyCounts {
  objects: number;
  definitions: number;
  links: number;
  metrics: number;
  compiled: number;
  refused: number;
}

export interface OntologyColumn { name: string; column: string | null; label?: string | null; annotated: boolean }
export interface OntologyClass {
  name: string; label?: string | null; description?: string | null;
  table?: string | null; primaryKey?: string[]; columns?: OntologyColumn[];
  kind?: string; kinds?: string[]; members?: string[]; predicate?: string | null; base?: string | null;
}
export interface OntologyLink {
  name: string; label?: string | null; from: string[]; to: string | null; column: string | null;
}
export interface OntologyMetric {
  name: string; label?: string | null; description?: string | null;
  aggregate?: string | null; grain?: string | null; universe?: string | null;
  where?: string | null; groupBy?: string[]; formula?: string | null;
  numerator?: string | null; denominator?: string | null; scale?: string | null;
  unit?: string | null; missing?: string[]; sql?: string; refused?: string; notes?: string[];
}
export interface Ontology {
  ok: boolean;
  profile?: string;
  path?: string;
  ns?: string;
  title?: string | null;
  dsn?: Record<string, unknown>;
  guard?: Record<string, unknown>;
  features?: Record<string, unknown>;
  objects?: OntologyClass[];
  definitions?: OntologyClass[];
  links?: OntologyLink[];
  metrics?: OntologyMetric[];
  counts?: OntologyCounts;
  error?: string;
}

export interface OntologyProfile {
  key: string;
  label: string;
  url: string;
  profile?: string | null;
  note?: string | null;
  enabled?: boolean;
}

/** Fallback only: the four profiles that ship in the ontology repo. */
export const FALLBACK_PROFILES: OntologyProfile[] = [
  { key: 'clinic', label: 'Clinic', url: 'http://127.0.0.1:8096', profile: 'ontologies/clinic/clinic_settings.json', note: 'built by a DeepAgent from clinic_db — 门诊 / 收费 / 理赔' },
  { key: 'retail', label: 'Retail', url: 'http://127.0.0.1:8092', profile: 'retail_graph/settings.json', note: 'the hand-built reference: orders, customers, stores, two lanes' },
  { key: 'tpch', label: 'TPC-H', url: 'http://127.0.0.1:8093', profile: 'retail_graph/tpch_settings.json', note: 'SF0.1 benchmark — historical data, so the guard refuses windows' },
  { key: 'abc', label: 'ABC', url: 'http://127.0.0.1:8094', profile: 'retail_graph/abc_settings.json', note: 'cold-chain training set with declared writes (lane C)' },
];

const STORAGE_URL = 'langconfig.ontology.url';

export interface OntologySection {
  key: string;
  label: string;
  path: string;
  hint: string;
  enabled: boolean;
}

/**
 * The workbench section an ontology exposes. The workbench's own rail is hidden when it is
 * framed (embed=1) — these are the entries that replace it, one list under each ontology.
 */
export const SECTIONS: Array<{ key: string; label: string; path: string; hint: string }> = [
  { key: 'home', label: 'Overview', path: '/', hint: 'the generated ontology page: objects, links, documentation' },
  { key: 'query', label: 'Query', path: '/query', hint: 'ask in your own words; rules first, model only when unsure' },
  { key: 'actions', label: 'Actions', path: '/actions', hint: 'declared writes: compiled preconditions, dry-run, audit' },
  { key: 'design', label: 'Design', path: '/design', hint: 'the architecture of this ontology: two lanes, one question' },
  { key: 'tutorial', label: 'Tutorial', path: '/tutorial', hint: 'a guided walk through the axioms and their numbers' },
];

/** Everything the frame needs: the page, no workbench chrome, and the host app's look. */
export function framedUrl(url: string, sectionPath: string, theme: 'dark' | 'light', lang?: string): string {
  const base = normalizeUrl(url);
  const sep = sectionPath.includes('?') ? '&' : '?';
  const params = new URLSearchParams({ embed: '1', theme });
  if (lang) params.set('lang', lang);
  return `${base}${sectionPath}${sep}${params.toString()}`;
}



export interface OntologyState {
  url: string;
  preset: string | null;
  status: 'idle' | 'loading' | 'up' | 'down';
  error: string | null;
  ontology: Ontology | null;
  profiles: OntologyProfile[];
  /** Where the list came from: the settings document, or the compiled-in fallback. */
  profilesFrom: 'settings' | 'fallback';
  /** A workbench start is in flight, so the UI says 'starting' instead of 'down'. */
  starting: boolean;
  /** Why the list is the built-in fallback, when it is. A silent fallback is a lie. */
  profilesError: string | null;
  defaultKey: string | null;
  showSql: boolean;
  /** Sections this profile serves (from the server, not a compiled list). */
  sections: OntologySection[];
  probes: Record<string, {
    status: 'unknown' | 'up' | 'down';
    counts?: OntologyCounts;
    error?: string;
    /** That profile's own sections — a peeked row must not list the selected one's. */
    sections?: OntologySection[];
  }>;
}

export function normalizeUrl(raw: string): string {
  return (raw || '').trim().replace(/\/+$/, '');
}

const storedUrl = (() => {
  try {
    return localStorage.getItem(STORAGE_URL) || '';
  } catch {
    return '';
  }
})();

let state: OntologyState = {
  url: storedUrl || '',
  preset: null,
  status: 'idle',
  error: null,
  ontology: null,
  profiles: FALLBACK_PROFILES,
  profilesFrom: 'fallback',
  profilesError: null,
  starting: false,
  defaultKey: null,
  showSql: true,
  sections: SECTIONS.map(x => ({ ...x, enabled: x.key !== 'actions' && x.key !== 'tutorial' })),
  probes: {},
};

const listeners = new Set<() => void>();

function emit(next: Partial<OntologyState>) {
  state = { ...state, ...next };
  listeners.forEach(fn => fn());
}

async function getJson(url: string, path: string, ms: number): Promise<any> {
  const res = await fetch(normalizeUrl(url) + path, { signal: AbortSignal.timeout(ms) });
  const body = await res.json();
  if (!res.ok) throw new Error(body?.error || `HTTP ${res.status}`);
  return body;
}

function pickProfiles(ns: any): { items: OntologyProfile[]; defaultKey: string | null; showSql: boolean } | null {
  const value = ns?.value;
  if (!value || !Array.isArray(value.items)) return null;
  const items = value.items
    .filter((i: any) => i && i.key && i.url && i.enabled !== false)
    .map((i: any) => ({
      key: String(i.key),
      label: String(i.label || i.key),
      url: normalizeUrl(String(i.url)),
      profile: i.profile ?? null,
      note: i.note ?? null,
      enabled: i.enabled !== false,
    }));
  return { items, defaultKey: value.default_key ?? null, showSql: value.show_sql !== false };
}

let attempts = 0;

export const ontology = {
  subscribe(fn: () => void) {
    listeners.add(fn);
    return () => listeners.delete(fn);
  },

  get(): OntologyState {
    return state;
  },

  /**
   * Load the profile list once and make sure a URL is selected.
   *
   * Every page calls this instead of juggling "is the list loaded / is a profile
   * selected" itself: a page opened by URL (a bookmark, a reload) has no selection, and
   * asking the store to `select('')` produced a 404 against the frontend's own origin.
   */
  async ensureReady(): Promise<string> {
    if (state.profilesFrom !== 'settings') await ontology.loadProfiles();
    if (!state.url) {
      const first = state.profiles.find(p => p.key === state.defaultKey) ?? state.profiles[0];
      if (first) {
        await ontology.select(first.url, first.key);
        return first.url;
      }
      return '';
    }
    // A remembered URL is not a loaded ontology: on a reload the store has the URL from
    // localStorage and nothing else, so a page that only called ensureReady() sat on
    // "checking…" forever instead of asking the server.
    if (!state.ontology && state.status !== 'loading') {
      await ontology.select(state.url, state.preset ?? undefined);
    }
    return state.url;
  },

  /** Read the profile list from the settings namespace; keep the fallback on failure. */
  async loadProfiles() {
    try {
      // apiClient.get returns the axios response; the settings payload is `.data`.
      const res: any = await apiClient.describeSettings();
      const ns = (res?.data?.namespaces || []).find((n: any) => n.ns === 'ontology');
      const picked = pickProfiles(ns);
      if (!picked || picked.items.length === 0) {
        emit({
          profiles: FALLBACK_PROFILES, profilesFrom: 'fallback',
          profilesError: 'the `ontology` settings namespace has no profiles',
          defaultKey: null, showSql: true,
        });
        return;
      }
      const url = state.url || picked.items.find(p => p.key === picked.defaultKey)?.url || picked.items[0].url;
      emit({
        profiles: picked.items,
        profilesFrom: 'settings',
        defaultKey: picked.defaultKey,
        showSql: picked.showSql,
        url,
        profilesError: null,
        preset: picked.items.find(p => p.url === url)?.key ?? null,
      });
    } catch (err: any) {
      emit({
        profiles: FALLBACK_PROFILES,
        profilesFrom: 'fallback',
        profilesError: String(err?.message || err),
      });
    }
  },

  /** Select a workbench, remember it, and load what it declares. */
  async select(url: string, presetKey?: string) {
    const clean = normalizeUrl(url);
    const preset = presetKey ?? state.profiles.find(p => p.url === clean)?.key ?? null;
    try {
      localStorage.setItem(STORAGE_URL, clean);
    } catch {
      /* private mode: the choice simply does not persist */
    }
    emit({ url: clean, preset, status: 'loading', error: null, ontology: null });
    try {
      const [doc, secs] = await Promise.all([
        getJson(clean, '/api/ontology', 8000),
        getJson(clean, '/api/sections', 4000).catch(() => null),
      ]);
      if (!doc.ok) throw new Error(doc.error || 'the workbench refused the profile');
      const served = Array.isArray(secs?.sections) ? secs.sections : null;
      const emit_sections = served
        ? served.map((x: any) => ({
            key: String(x.key), label: String(x.label), path: String(x.path),
            hint: String(x.hint || ''), enabled: x.enabled !== false,
          }))
        : SECTIONS.map(x => ({ ...x, enabled: true }));
      emit({
        status: 'up',
        ontology: doc,
        sections: emit_sections,
        probes: {
          ...state.probes,
          [clean]: { status: 'up', counts: doc.counts, sections: emit_sections },
        },
      });
    } catch (err: any) {
      const message = err?.name === 'TimeoutError' ? 'no answer in 8 s' : String(err?.message || err);
      emit({
        status: 'down',
        error: message,
        probes: { ...state.probes, [clean]: { status: 'down', error: message } },
      });
    }
  },

  /**
   * Ask the backend to make sure every configured workbench is up, then record what it says.
   *
   * The servers are local child processes the backend starts on demand: a user should never
   * read a URL or open a terminal, so this is the ONLY way the UI learns liveness. The first
   * call may have to spawn four processes, hence the long timeout and the bounded retry.
   */
  async probeAll() {
    try {
      const res: any = await apiClient.get('/api/ontology/workbenches', { timeout: 45000 });
      const rows: any[] = res?.data?.workbenches || [];
      const probes: OntologyState['probes'] = { ...state.probes };
      for (const r of rows) {
        const url = state.profiles.find(p => p.key === r.key)?.url || r.key;
        probes[url] = {
          status: r.up ? 'up' : 'down',
          counts: r.counts || undefined,
          error: r.error || undefined,
        };
      }
      emit({ probes });
      const down = rows.filter(r => !r.up);
      if (down.length) {
        attempts += 1;
        if (attempts <= 3) {
          emit({ starting: true });
          setTimeout(() => { void ontology.probeAll(); }, 2500 * attempts);
        } else {
          emit({ starting: false });
        }
      } else {
        attempts = 0;
        emit({ starting: false });
      }
      // load the selected profile's document so the browser and its sections follow
      const selected = rows.find(r => r.key === state.preset) ?? rows.find(r => r.up);
      if (selected?.up) {
        const url = state.profiles.find(p => p.key === selected.key)?.url;
        if (url && (!state.ontology || state.preset !== selected.key)) {
          await ontology.select(url, selected.key);
        }
      }
    } catch (err: any) {
      attempts += 1;
      if (attempts <= 3) {
        emit({ starting: true });
        setTimeout(() => { void ontology.probeAll(); }, 2500 * attempts);
        return;
      }
      emit({ starting: false });
      console.warn('[ontology] workbench status failed:', err?.message || err);
    }
  },
};

/** Subscribe a component to the store (a small external store; no provider needed). */
export function useOntology(): OntologyState {
  const [, force] = useReducer((n: number) => n + 1, 0);
  useEffect(() => {
    const unsub = ontology.subscribe(force);
    return () => {
      unsub();
    };
  }, []);
  return state;
}
