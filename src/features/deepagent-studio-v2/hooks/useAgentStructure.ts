/**
 * useAgentStructure — fetches and normalizes an agent's data into a structure.
 */

import { useEffect, useState } from 'react';
import apiClient from '@/lib/api-client';
import type { AgentStructure } from '../types';

export function useAgentStructure(agentId: number | null) {
  const [structure, setStructure] = useState<AgentStructure | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!agentId) {
      setStructure(null);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    (async () => {
      try {
        const res: any = await apiClient.getDeepAgent(agentId);
        const agent = res?.data ?? res;
        const cfg = agent?.config || {};
        const normalized: AgentStructure = {
          id: agent?.id,
          name: agent?.name || 'Agent',
          description: agent?.description,
          model: cfg.model || 'minimax-m3',
          system_prompt: cfg.system_prompt,
          native_tools: cfg.native_tools || [],
          custom_tools: cfg.custom_tools || [],
          tools: cfg.tools || cfg.cli_tools || [],
          subagents: (cfg.skills || []).map((name: string, i: number) => ({
            id: `skill-${i}`,
            name,
            skill_type: 'Skill',
            description: cfg.skill_descriptions?.[name],
          })),
          skills: cfg.skills || [],
        };
        if (!cancelled) setStructure(normalized);
      } catch (e: any) {
        if (!cancelled) setError(e?.message || 'Failed to load agent');
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [agentId]);

  return { structure, loading, error };
}
