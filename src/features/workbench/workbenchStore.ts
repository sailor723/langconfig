/**
 * workbenchStore — the ontologies the Workbench activity can open, and the selected one.
 *
 * Three facts drive the UI and they come from three different places, so they are kept
 * apart here: which workbench URL is selected (localStorage), whether it answers (a fetch
 * of /api/ontology), and what it declares (the document that same call returns). Nothing is
 * cached across profiles — a browser showing the clinic ontology while the header says
 * TPC-H would be the worst possible failure for a tool whose job is "what is declared".
 */
import { useEffect, useReducer } from 'react';

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

export interface WorkbenchPreset {
  key: string;
  label: string;
  url: string;
  profile: string;
  note: string;
}

/**
 * The four profiles that exist on disk. A preset is data, not logic: adding a fifth
 * ontology means adding a row here (or typing its URL in the bar).
 */
export const PRESETS: WorkbenchPreset[] = [
  {
    key: 'clinic',
    label: 'Clinic',
    url: 'http://127.0.0.1:8096',
    profile: 'ontologies/clinic/clinic_settings.json',
    note: 'built by DeepAgent 348 from clinic_db — 门诊 / 收费 / 理赔，28 metrics',
  },
  {
    key: 'retail',
    label: 'Retail',
    url: 'http://127.0.0.1:8092',
    profile: 'retail_graph/settings.json',
    note: 'the hand-built reference: orders, customers, stores, two lanes',
  },
  {
    key: 'tpch',
    label: 'TPC-H',
    url: 'http://127.0.0.1:8093',
    profile: 'retail_graph/tpch_settings.json',
    note: 'SF0.1 benchmark — historical data, so the guard refuses windows',
  },
  {
    key: 'abc',
    label: 'ABC',
    url: 'http://127.0.0.1:8094',
    profile: 'retail_graph/abc_settings.json',
    note: 'cold-chain training set with declared writes (lane C)',
  },
];

const STORAGE_URL = 'langconfig.workbench.url';

export interface WorkbenchState {
  url: string;
  preset: string | null;
  status: 'idle' | 'loading' | 'up' | 'down';
  error: string | null;
  ontology: Ontology | null;
  /** Every preset with its last probe, so the home page can show what is actually running. */
  probes: Record<string, { status: 'unknown' | 'up' | 'down'; counts?: OntologyCounts; error?: string }>;
}

const initial: WorkbenchState = {
  url: (() => {
    try {
      return localStorage.getItem(STORAGE_URL) || PRESETS[0].url;
    } catch {
      return PRESETS[0].url;
    }
  })(),
  preset: null,
  status: 'idle',
  error: null,
  ontology: null,
  probes: {},
};

let state: WorkbenchState = { ...initial, preset: PRESETS.find(p => p.url === initial.url)?.key ?? null };
const listeners = new Set<() => void>();

function emit(next: Partial<WorkbenchState>) {
  state = { ...state, ...next };
  listeners.forEach(fn => fn());
}

/** trim a trailing slash once, so `http://host:8096/` and `http://host:8096` are one thing */
export function normalizeUrl(raw: string): string {
  return raw.trim().replace(/\/+$/, '');
}

async function getJson(url: string, path: string, ms: number): Promise<any> {
  const res = await fetch(normalizeUrl(url) + path, { signal: AbortSignal.timeout(ms) });
  const body = await res.json();
  if (!res.ok) throw new Error(body?.error || `HTTP ${res.status}`);
  return body;
}

export const workbench = {
  subscribe(fn: () => void) {
    listeners.add(fn);
    return () => listeners.delete(fn);
  },

  get(): WorkbenchState {
    return state;
  },

  /** Select a workbench, remember it, and load what it declares. */
  async select(url: string, presetKey?: string) {
    const clean = normalizeUrl(url);
    let preset = presetKey ?? PRESETS.find(p => p.url === clean)?.key ?? null;
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

  /** Probe every preset in parallel — the home page shows what is actually running. */
  async probeAll() {
    await Promise.all(
      PRESETS.map(async p => {
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

  /** Human name of the profile currently loaded, from the document itself. */
  profileName(): string {
    return state.ontology?.profile || '';
  },
};

/** Subscribe a component to the store (a small external store; no provider needed). */
export function useWorkbench(): WorkbenchState {
  const [, force] = useReducer((n: number) => n + 1, 0);
  useEffect(() => {
    const unsub = workbench.subscribe(force);
    return () => {
      unsub();
    };
  }, []);
  return state;
}
