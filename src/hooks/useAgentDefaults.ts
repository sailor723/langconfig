/**
 * Create-time agent limits, read from Settings → Agents (PostgreSQL).
 *
 * The `agents` settings namespace holds one set per agent kind, because the two
 * kinds differ ~6x in the step budget they need: `recursion_limit` counts
 * LangGraph supersteps, and one LLM turn costs ~13 steps for a standard agent
 * (six default middleware × before_model + after_model) but only ~2 for a
 * DeepAgent (its middleware runs inside the model node).
 *
 * Creators read these defaults so a new agent starts from the team's numbers
 * instead of duplicating literals; Settings stays the single place to edit them.
 */
import { useEffect, useState } from 'react';

import { apiClient } from '@/lib/api-client';

export interface AgentLimits {
  /** LangGraph supersteps allowed in one chat run (NOT tool calls). */
  recursion_limit: number;
  /** Compact when a model call would exceed this many tokens (system prompt + tools + conversation). */
  summarization_threshold: number;
  /** Messages kept verbatim after compaction. */
  keep_last_messages: number;
  /** Context budget used by workflow nodes / exported apps (not enforced in chat). */
  max_total_tokens: number;
  /** Declared; must satisfy summarization < eviction < max_total. */
  eviction_threshold: number;
  enable_summarization: boolean;
  enable_auto_eviction: boolean;
}

export interface AgentDefaults {
  /** Defaults for agents created with use_deepagents = false. */
  agent?: AgentLimits;
  /** Defaults for DeepAgents. */
  deepagent?: AgentLimits;
  isLoading: boolean;
}

/** Fallback when the backend has not seeded the namespace yet. */
export const FALLBACK_LIMITS: AgentLimits = {
  recursion_limit: 400,
  summarization_threshold: 60000,
  keep_last_messages: 20,
  max_total_tokens: 100000,
  eviction_threshold: 80000,
  enable_summarization: true,
  enable_auto_eviction: true,
};

export function useAgentDefaults(): AgentDefaults {
  const [defaults, setDefaults] = useState<AgentDefaults>({ isLoading: true });

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await apiClient.describeSettings();
        const ns = (res.data?.namespaces || []).find((n: any) => n.ns === 'agents');
        const value = (ns?.value || {}) as { agent?: AgentLimits; deepagent?: AgentLimits };
        if (!cancelled) {
          setDefaults({
            agent: value.agent ?? FALLBACK_LIMITS,
            deepagent: value.deepagent ?? FALLBACK_LIMITS,
            isLoading: false,
          });
        }
      } catch {
        if (!cancelled) {
          setDefaults({ agent: FALLBACK_LIMITS, deepagent: FALLBACK_LIMITS, isLoading: false });
        }
      }
    })();
    return () => { cancelled = true; };
  }, []);

  return defaults;
}
