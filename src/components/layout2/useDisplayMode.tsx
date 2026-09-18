/**
 * useDisplayMode — global UI display mode ("verbose" | "direct").
 *
 * Sourced from the `general` settings document (DSH-style). Loaded once on
 * mount and refreshed whenever the `settings:updated` window event fires.
 *
 * Verbose (default): catalog activities (Tools, Agents, DeepAgents,
 *   Skills, Knowledge, Prompt) render their full HomePage on entry —
 *   the marketing hero ("what is X…") + template grid at the bottom.
 *
 * Direct: the same six activities skip their HomePage and jump straight
 *   to the activity's natural studio / "new item" tab — no catalog
 *   detour. Matches the Graph activity's existing behavior (click Graph
 *   → studio; no landing page).
 *
 * The "what to open" decision lives in App.tsx (`directModeTabFor`).
 */
import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from 'react';
import apiClient from '../../lib/api-client';

export type DisplayMode = 'verbose' | 'direct';

export interface DisplayModeContextValue {
  /** Current display mode (defaults to 'verbose' before settings load). */
  displayMode: DisplayMode;
  /** Setter used by Settings > General to flip modes. */
  setDisplayMode: (mode: DisplayMode) => Promise<void>;
  /** True once the settings fetch has completed at least once. */
  loaded: boolean;
}

const DisplayModeContext = createContext<DisplayModeContextValue | null>(null);

export function useDisplayMode(): DisplayModeContextValue {
  const ctx = useContext(DisplayModeContext);
  if (!ctx) throw new Error('useDisplayMode must be used inside <DisplayModeProvider>');
  return ctx;
}

/** Read the current `display_mode` value from the general settings document.
 *  Tolerates the document being missing or stale (falls back to 'verbose'). */
async function fetchDisplayMode(): Promise<DisplayMode> {
  try {
    const res = await apiClient.describeSettings();
    const ns = (res.data?.namespaces || []).find((n: any) => n.ns === 'general');
    const v = ns?.value?.display_mode;
    return v === 'direct' ? 'direct' : 'verbose';
  } catch {
    return 'verbose';
  }
}

/** Write `display_mode` to the general settings document via the DSH
 *  describe/mutate wire API. */
async function persistDisplayMode(mode: DisplayMode): Promise<boolean> {
  try {
    await apiClient.mutateSettings({
      ns: 'general',
      ops: [{ op: 'set', path: ['display_mode'], value: mode }],
    });
    return true;
  } catch {
    return false;
  }
}

export function DisplayModeProvider({ children }: { children: ReactNode }) {
  const [displayMode, setDisplayModeState] = useState<DisplayMode>('verbose');
  const [loaded, setLoaded] = useState(false);

  // Load once on mount.
  useEffect(() => {
    let cancelled = false;
    fetchDisplayMode().then((v) => {
      if (!cancelled) {
        setDisplayModeState(v);
        setLoaded(true);
      }
    });
    return () => { cancelled = true; };
  }, []);

  // Refresh when the Settings modal broadcasts an update.
  useEffect(() => {
    const handler = () => {
      fetchDisplayMode().then((v) => setDisplayModeState(v));
    };
    window.addEventListener('settings:updated', handler);
    return () => window.removeEventListener('settings:updated', handler);
  }, []);

  const setDisplayMode = useCallback(async (mode: DisplayMode) => {
    // Optimistic update so the UI reflects the toggle immediately.
    setDisplayModeState(mode);
    const ok = await persistDisplayMode(mode);
    if (ok) {
      // Notify other listeners (e.g. this provider's other useEffects).
      window.dispatchEvent(new CustomEvent('settings:updated'));
    }
  }, []);

  return (
    <DisplayModeContext.Provider value={{ displayMode, setDisplayMode, loaded }}>
      {children}
    </DisplayModeContext.Provider>
  );
}