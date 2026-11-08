/**
 * ontologyStore — the ontologies this account can open, and the one currently selected.
 *
 * WHERE THE LIST COMES FROM: the `ontology` settings namespace (Settings → Ontology), so
 * which profiles exist is a decision someone made rather than four URLs compiled into the
 * bundle. The built-in list below is only a fallback for a first run before the settings
 * document is seeded — it is labelled as such in the UI's error path, never silently mixed in.
 *
 * Three facts are kept apart because they come from three places: the selected profile
 * (localStorage), whether the app can compile it (a fetch of `/api/ontology/{key}/document`), and what it
 * declares (that same document). The document is replaced on every profile switch and never merged — a
 * browser showing clinic declarations under a TPC-H header is the failure mode this tool exists to
 * prevent, and it is also why a missing page never falls back to another ontology's.
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

/**
 * Fallback only: what THIS app ships when the settings document has not been seeded yet.
 *
 * `profile` is relative to `backend/features/ontology/profiles/` — the declarations are part of this
 * repository, so a fresh checkout lists them without fetching anything. `url` is the profile's
 * DEVELOPMENT workbench port (see deploy/workbench.yml); the app compiles and serves every page itself.
 * The real list is a setting (Settings → Ontology); this one is labelled as the fallback in the UI.
 */
export const FALLBACK_PROFILES: OntologyProfile[] = [
  { key: 'clinic', label: 'Clinic', url: 'http://127.0.0.1:8096', profile: 'clinic/clinic_settings.json', note: 'built by a DeepAgent from clinic_db — 门诊 / 收费 / 理赔' },
  { key: 'retail', label: 'Retail', url: 'http://127.0.0.1:8092', profile: 'retail/settings.json', note: 'the hand-built reference: orders, customers, stores, two lanes' },
  { key: 'logistics', label: 'Logistics', url: 'http://127.0.0.1:8098', profile: 'logistics/logistics_settings.json', note: 'cold-chain trips, stops and complaints — with a dashboard declaration' },
  { key: 'tpch', label: 'TPC-H', url: 'http://127.0.0.1:8093', profile: 'tpch/tpch_settings.json', note: 'SF0.1 benchmark — historical data, so the guard refuses windows' },
  { key: 'abc', label: 'ABC', url: 'http://127.0.0.1:8094', profile: 'abc/abc_settings.json', note: 'cold-chain training set with declared writes (lane C)' },
];

const STORAGE_URL = 'langconfig.ontology.url';
/**
 * The KEY is the identity; the URL is only where the ontology USED to be served.
 *
 * Every installed ontology is served from this origin, so `url` is '' for all of them — and a store
 * keyed by url then treats them as ONE ontology. Measured on the deployment: clicking one ontology
 * showed another, because the fallback `profiles.find(p => p.url === s.url)` returned the first row
 * for every row, and a reload (which forgets the in-memory `preset`) landed on whatever row sorted
 * first. The key is persisted now, so a reload re-opens the ontology that was open.
 */
const STORAGE_KEY = 'langconfig.ontology.key';

/**
 * A section of one ontology, and there are two kinds — the list shows them side by side:
 *
 *  · `section` — a page of this ontology (graph view, query, actions, design, tutorial), served by THIS
 *    app at `/api/ontology/{key}/page/…` and rendered in a frame. The profile declares which of these it
 *    actually has (`features`), and a section it does not have is not offered.
 *  · `app`     — a page of THIS application (`/ontology/dashboard`): a React route that reads the ontology
 *    through the app's own API, so framing it would be a second copy of the app itself.
 *
 * They sit in ONE list because a reader does not care which process answers — Query and Dashboard are the
 * two ways to read a number, and they belong next to each other.
 */
export interface OntologySection {
  key: string;
  label: string;
  path: string;
  hint: string;
  enabled: boolean;
  kind?: 'app' | 'workbench';
}

/** Pages of this app that belong in an ontology's section list (never framed). */
export const APP_SECTIONS: OntologySection[] = [
  {
    key: 'dashboard', label: 'Dashboard', path: '/ontology/dashboard', kind: 'app', enabled: true,
    hint: 'the board: declared metrics, an opening assessment, cross-filter — served by the app, every number compiled by the ontology',
  },
];

export const SECTIONS: Array<Omit<OntologySection, 'enabled'> & { enabled?: boolean }> = [
  // the page IS the generated graph + documentation (graph_view.py); the key stays `home` for old links
  { key: 'home', label: 'Graph view', path: '/', kind: 'workbench', hint: 'the graph and the documentation generated from the TTL, with live numbers' },
  { key: 'query', label: 'Query', path: '/query', kind: 'workbench', hint: 'ask in your own words; rules first, model only when unsure' },
  ...APP_SECTIONS,
  { key: 'actions', label: 'Actions', path: '/actions', kind: 'workbench', hint: 'declared writes: compiled preconditions, dry-run, audit' },
  { key: 'design', label: 'Design', path: '/design', kind: 'workbench', hint: 'the architecture of this ontology: two lanes, one question' },
  { key: 'tutorial', label: 'Tutorial', path: '/tutorial', kind: 'workbench', hint: 'a guided walk through the axioms and their numbers' },
];

/**
 * Merge the app's own pages into the sections the profile reports.
 *
 * The server replaces the compiled list wholesale, so an app page added only to `SECTIONS` vanished as soon
 * as a profile answered `/api/sections`. This is the one place that keeps the two kinds together, and it
 * puts the dashboard directly after Query — the two ways to read a number belong next to each other.
 */
export function mergeSections(served: OntologySection[]): OntologySection[] {
  const list = served.map(s => ({ ...s, kind: s.kind ?? 'workbench' as const }));
  const missing = APP_SECTIONS.filter(a => !list.some(s => s.key === a.key));
  if (!missing.length) return list;
  const afterQuery = list.findIndex(s => s.key === 'query');
  const at = afterQuery >= 0 ? afterQuery + 1 : list.length;
  return [...list.slice(0, at), ...missing, ...list.slice(at)];
}

/** Everything the frame needs: the page, no page chrome, and the host app's look. */
export function framedUrl(url: string, sectionPath: string, theme: 'dark' | 'light', lang?: string): string {
  const base = normalizeUrl(url);
  const sep = sectionPath.includes('?') ? '&' : '?';
  const params = new URLSearchParams({ embed: '1', theme });
  if (lang) params.set('lang', lang);
  return `${base}${sectionPath}${sep}${params.toString()}`;
}

/**
 * Where one ontology's section is served: THIS app, by section key.
 *
 * The five workbench servers used to answer these paths on their own ports (`/`, `/query`, `/actions`,
 * `/design`, `/tutorial`). Each is now a same-origin asset of the app under `/api/ontology/{key}/page/…`,
 * so the frame in `OntologySectionPage` loads a page from the origin the user is already on — no port
 * list, no CORS, and no second resolver to disagree about which ontology the page belongs to.
 */
export function sectionPageUrl(key: string, sectionKey: string): string {
  const name: Record<string, string> = {
    home: 'graph', graph: 'graph', design: 'design', tutorial: 'tutorial', query: 'query', actions: 'actions',
  };
  const page = name[sectionKey] ?? sectionKey;
  return apiFor(key, `/page/${page}`);
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
  /** A compile of every ontology is in flight, so the UI says 'compiling' instead of 'refused'. */
  starting: boolean;
  /** Why the list is the built-in fallback, when it is. A silent fallback is a lie. */
  profilesError: string | null;
  defaultKey: string | null;
  showSql: boolean;
  /** Sections this profile serves (from the server, not a compiled list). */
  sections: OntologySection[];
  /**
   * Per-ontology liveness, keyed by the ontology's KEY.
   *
   * It used to be keyed by `url`, which is '' for every same-origin ontology — so all seven shared
   * one entry: one ontology's up/down dot and metric counts were displayed on every row, and the
   * sections listed under a row belonged to whichever profile probed last.
   */
  probes: Record<string, {
    status: 'unknown' | 'up' | 'down';
    counts?: OntologyCounts;
    error?: string;
    /** That profile's own sections — a peeked row must not list the selected one's. */
    sections?: OntologySection[];
  }>;
}

/**
 * Is THIS row the open ontology?
 *
 * The sidebar used `s.url === p.url`, and that test became true for every row the day the app started
 * serving the pages itself: four roster rows carry the same legacy url (`http://127.0.0.1:8765`) and the
 * installed-only rows carry `''`, so clicking one ontology highlighted all the others (measured, then
 * reported back as "I click v6 and every other one is highlighted"). The KEY is the identity; a url is
 * only consulted for a row that still names one and is not the one already open.
 */
export function profileIsActive(p: OntologyProfile, s: Pick<OntologyState, 'url' | 'preset'>): boolean {
  if (s.preset) return s.preset === p.key;
  return !!p.url && s.url === p.url;
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
const storedKey = (() => {
  try {
    return localStorage.getItem(STORAGE_KEY) || '';
  } catch {
    return '';
  }
})();

let state: OntologyState = {
  url: storedUrl || '',
  preset: storedKey || null,
  status: 'idle',
  error: null,
  ontology: null,
  profiles: FALLBACK_PROFILES,
  profilesFrom: 'fallback',
  profilesError: null,
  starting: false,
  defaultKey: null,
  showSql: true,
  sections: mergeSections(SECTIONS.map(x => ({ ...x, enabled: x.key !== 'actions' && x.key !== 'tutorial' }))),
  probes: {},
};

const listeners = new Set<() => void>();

function emit(next: Partial<OntologyState>) {
  state = { ...state, ...next };
  listeners.forEach(fn => fn());
}

/**
 * Where the documents come from: THIS application.
 *
 * They used to be fetched from a per-ontology workbench server (`http://127.0.0.1:8098/api/ontology`),
 * which is why five processes had to be running before a page could render. The compiler is inside the
 * app now, so the same shapes are served at `/api/ontology/{key}/…` — one origin, no ports, and no
 * second resolver to disagree about which ontology a page belongs to.
 */
export function apiFor(key: string, path: string): string {
  return `/api/ontology/${encodeURIComponent(key)}${path}`;
}

async function getJson(url: string, path: string, ms: number): Promise<any> {
  const res = await fetch(normalizeUrl(url) + path, { signal: AbortSignal.timeout(ms) });
  const body = await res.json();
  if (!res.ok) throw new Error(body?.error || body?.detail || `HTTP ${res.status}`);
  return body;
}

/** One ontology's document, card list or section list — from this app, keyed by the ontology's key. */
async function getAppJson(key: string, path: string, ms: number): Promise<any> {
  const res = await fetch(apiFor(key, path), { signal: AbortSignal.timeout(ms) });
  const body = await res.json();
  if (!res.ok) throw new Error(body?.error || body?.detail || `HTTP ${res.status}`);
  return body;
}

/**
 * An INSTALLED ontology exists whether or not a settings row mentions it.
 *
 * The `ontology` settings namespace used to be the whole roster: a published ontology that nobody added
 * a row for was invisible in the activity and in this browser (measured twice — v6 compiled 48/48 then
 * 32/32, gates green, and could not be found). Existence now comes from the profiles on disk
 * (`GET /api/ontology/installed`); the settings rows only decide the human-facing label, the note, the
 * order and whether an ontology is shown at all.
 */
function mergeInstalled(decided: OntologyProfile[], installed: any[]): OntologyProfile[] {
  const byKey = new Map(decided.map(p => [p.key, p]));
  const merged: OntologyProfile[] = [];
  for (const p of decided) merged.push(p);                     // settings order wins
  for (const row of installed || []) {
    const key = String(row?.key || '');
    if (!key || byKey.has(key)) continue;                      // already listed (and possibly relabelled)
    merged.push({
      key,
      label: String(row.label || key),
      url: '',                                                 // same-origin: the app serves every page
      profile: row.profile ?? null,
      note: row.installed ? 'installed · appears automatically (no roster entry)' : null,
      enabled: true,
    });
  }
  return merged;
}

function pickProfiles(ns: any): { items: OntologyProfile[]; defaultKey: string | null; showSql: boolean } | null {
  const value = ns?.value;
  if (!value || !Array.isArray(value.items)) return null;
  const items = value.items
    .filter((i: any) => i && i.key && i.enabled !== false)
    .map((i: any) => ({
      key: String(i.key),
      label: String(i.label || i.key),
      url: i.url ? normalizeUrl(String(i.url)) : '',
      profile: i.profile ?? null,
      note: i.note ?? null,
      enabled: i.enabled !== false,
    }));
  return { items, defaultKey: value.default_key ?? null, showSql: value.show_sql !== false };
}

export interface MetricCard {
  name: string;
  label?: string | null;
  sql?: string;
  value?: string | number | null;
  plan_rows?: number;
  ms?: number;
  error?: string;
  run_error?: string;
  aggregate?: string | null;
  formula?: string | null;
  grain?: string | null;
  universe?: string | null;
  where?: string | null;
  groupBy?: string[];
  numerator?: string | null;
  denominator?: string | null;
  scale?: string | null;
  unit?: string | null;
  notes?: string[];
  guard_notes?: string[];
}

/** Every metric as a card — one call, because the values come from
 *  the database under the guardrails and a card without its number is half a card. */
export async function fetchMetricCards(key: string): Promise<MetricCard[]> {
  const body = await getAppJson(key, '/metrics/cards', 120000);
  if (!body?.ok) throw new Error(body?.error || body?.detail || 'the card list was refused');
  return (body.cards || []) as MetricCard[];
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
    // A stored url from BEFORE the app served its own pages names a workbench port that no roster row
    // claims any more. It is not a selection — it is a leftover — so the remembered KEY decides.
    const urlIsKnown = !!state.url && state.profiles.some(p => p.url === state.url);
    if (!state.preset && (!state.url || !urlIsKnown)) {
      // the remembered KEY wins (a reload keeps which ontology was open), then the declared default,
      // then the first row — and never `profiles[0]` on its own, which is how a reload landed on
      // whichever ontology sorted first instead of the one that was open.
      const first = state.profiles.find(p => p.key === storedKey)
        ?? state.profiles.find(p => p.key === state.defaultKey)
        ?? state.profiles[0];
      if (first) {
        await ontology.select(first.url, first.key);
        return first.url;
      }
      return '';
    }
    // A remembered selection is not a loaded ontology: on a reload the store has the URL/key from
    // localStorage and nothing else, so a page that only called ensureReady() sat on
    // "checking…" forever instead of asking the server.
    if (!state.ontology && state.status !== 'loading') {
      await ontology.select(state.url, state.preset ?? storedKey ?? undefined);
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
      let installedRows: any[] = [];
      try {
        const inst: any = await apiClient.get('/api/ontology/installed');
        installedRows = inst?.data?.installed || [];
      } catch { installedRows = []; }
      const withInstalled = picked
        ? { ...picked, items: mergeInstalled(picked.items, installedRows) }
        : (installedRows.length
            ? { items: mergeInstalled([], installedRows), defaultKey: null, showSql: true }
            : null);
      if (!withInstalled || withInstalled.items.length === 0) {
        emit({
          profiles: FALLBACK_PROFILES, profilesFrom: 'fallback',
          profilesError: 'the `ontology` settings namespace has no profiles',
          defaultKey: null, showSql: true,
        });
        return;
      }
      const items = withInstalled.items;
      const url = state.url || items.find(p => p.key === withInstalled.defaultKey)?.url || items[0]?.url || '';
      emit({
        profiles: items,
        profilesFrom: 'settings',
        defaultKey: withInstalled.defaultKey,
        showSql: withInstalled.showSql,
        url,
        profilesError: null,
        preset: items.find(p => p.url === url)?.key ?? null,
      });
    } catch (err: any) {
      emit({
        profiles: FALLBACK_PROFILES,
        profilesFrom: 'fallback',
        profilesError: String(err?.message || err),
      });
    }
  },

  /** Select an ontology, remember it, and load what it declares. */
  async select(url: string, presetKey?: string) {
    const clean = normalizeUrl(url);
    // the KEY decides which ontology this is. A url is only consulted when the caller did not name a
    // key, and only when it is not empty — every installed ontology has `url: ''`, so matching on
    // '' made seven different ontologies resolve to the same (first) row.
    const preset = presetKey
      || (clean ? state.profiles.find(p => p.url === clean)?.key : undefined)
      || state.preset
      || null;
    try {
      localStorage.setItem(STORAGE_URL, clean);
      if (preset) localStorage.setItem(STORAGE_KEY, preset);
      else localStorage.removeItem(STORAGE_KEY);
    } catch {
      /* private mode: the choice simply does not persist */
    }
    emit({ url: clean, preset, status: 'loading', error: null, ontology: null });
    if (!preset) {
      // every document now comes from `/api/ontology/{key}/…`, so a profile the app cannot name has no
      // documents — saying so beats framing a URL that only a workbench process would answer
      const message = 'this ontology is not in the app\'s list, so the app has no key to load it by';
      emit({ status: 'down', error: message });
      return;
    }
    try {
      const [doc, secs] = await Promise.all([
        getAppJson(preset, '/document', 20000),
        getAppJson(preset, '/sections', 8000).catch(() => null),
      ]);
      if (!doc.ok) throw new Error(doc.error || 'the app refused to compile this ontology');
      const served = Array.isArray(secs?.sections) ? secs.sections : null;
      const emit_sections = served
        ? served.map((x: any) => ({
            key: String(x.key), label: String(x.label), path: String(x.path),
            hint: String(x.hint || ''), enabled: x.enabled !== false,
            // KEEP the kind. Dropping it made the server's own dashboard entry arrive as
            // `undefined`, mergeSections turned that into 'workbench', and because the server
            // already lists key 'dashboard' the app's `kind: 'app'` entry was never merged back.
            // Symptom: clicking Dashboard navigated to /ontology/app?view=dashboard, which
            // frames /api/ontology/{key}/page/dashboard and 404s ("no page 'dashboard'") —
            // while the route /ontology/dashboard worked.
            kind: (x.kind === 'app' ? 'app' : 'workbench') as 'app' | 'workbench',
          }))
        : SECTIONS.map(x => ({ ...x, enabled: true }));
      const with_app = mergeSections(emit_sections);
      emit({
        status: 'up',
        ontology: doc,
        sections: with_app,
        probes: {
          ...state.probes,
          ...(preset ? { [preset]: { status: 'up' as const, counts: doc.counts, sections: with_app } } : {}),
        },
      });
    } catch (err: any) {
      const message = err?.name === 'TimeoutError' ? 'no answer in 20 s' : String(err?.message || err);
      emit({
        status: 'down',
        error: message,
        probes: {
          ...state.probes,
          ...(preset ? { [preset]: { status: 'down' as const, error: message } } : {}),
        },
      });
    }
  },

  /**
   * Ask the APP, per ontology, whether it can compile it — and record the answer.
   *
   * This used to ask the backend to START five workbench servers and report their ports. Nothing is
   * started any more: every document is compiled in the app, so liveness is a question the app answers
   * about itself (`/api/ontology/{key}/document`). One request per profile, in parallel, no retries:
   * a compile that fails says why in the same breath, and a retry loop over it would only hide that.
   */
  async probeAll() {
    emit({ starting: true });
    const probes: OntologyState['probes'] = { ...state.probes };
    const results = await Promise.all(state.profiles.map(async p => {
      try {
        // the document is the same compile the section pages need, and it carries the counts the cards
        // show — so liveness and the numbers are one answer, not two that can disagree
        const [body, secs] = await Promise.all([
          getAppJson(p.key, '/document', 60000),
          getAppJson(p.key, '/sections', 8000).catch(() => null),
        ]);
        const sections = Array.isArray(secs?.sections)
          ? secs.sections.map((x: any) => ({
              key: String(x.key), label: String(x.label), path: String(x.path),
              hint: String(x.hint || ''), enabled: x.enabled !== false,
            }))
          : undefined;
        return { key: p.key, url: p.url, up: true as const, counts: body?.counts, sections };
      } catch (err: any) {
        return { key: p.key, url: p.url, up: false as const, error: String(err?.message || err) };
      }
    }));
    for (const r of results) {
      probes[r.key] = r.up
        ? { status: 'up', counts: r.counts, sections: (r as any).sections }
        : { status: 'down', error: r.error };
    }
    emit({ probes, starting: false });

    // load the selected profile's document so the browser and its sections follow. NOT gated on
    // `chosen.url`: every same-origin ontology has url '' — the old `&& chosen.url` guard meant a
    // probe never selected anything, and the pages fell back to "the first row".
    const chosen = results.find(r => r.key === state.preset) ?? results.find(r => r.up);
    if (chosen?.up && (!state.ontology || state.preset !== chosen.key)) {
      await ontology.select(chosen.url, chosen.key);
    }
  }
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
