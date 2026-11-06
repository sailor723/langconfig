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

export interface OntologyState {
  url: string;
  preset: string | null;
  status: 'idle' | 'loading' | 'up' | 'down';
  error: string | null;
  ontology: Ontology | null;
  profiles: OntologyProfile[];
  /** Where the list came from: the settings document, or the compiled-in fallback. */
  profilesFrom: 'settings' | 'fallback';
  /** Why the list is the built-in fallback, when it is. A silent fallback is a lie. */
  profilesError: string | null;
  defaultKey: string | null;
  showSql: boolean;
  probes: Record<string, { status: 'unknown' | 'up' | 'down'; counts?: OntologyCounts; error?: string }>;
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
  defaultKey: null,
  showSql: true,
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
      const doc: Ontology = await getJson(clean, '/api/ontology', 8000);
      if (!doc.ok) throw new Error(doc.error || 'the workbench refused the profile');
      emit({
        status: 'up',
        ontology: doc,
        probes: { ...state.probes, [clean]: { status: 'up', counts: doc.counts } },
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

  /** Probe every configured profile in parallel — the home page shows what is running. */
  async probeAll() {
    await Promise.all(
      state.profiles.map(async p => {
        try {
          const doc = await getJson(p.url, '/api/ontology', 4000);
          emit({
            probes: {
              ...state.probes,
              [p.url]: doc.ok
                ? { status: 'up', counts: doc.counts }
                : { status: 'down', error: doc.error || 'refused the profile' },
            },
          });
        } catch (err: any) {
          emit({
            probes: {
              ...state.probes,
              [p.url]: {
                status: 'down',
                error: err?.name === 'TimeoutError' ? 'no answer in 4 s' : String(err?.message || err),
              },
            },
          });
        }
      }),
    );
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
