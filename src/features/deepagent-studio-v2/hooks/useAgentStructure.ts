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
        // Get full subagent records first (they have prompt/system_prompt/etc.)
        const rawSubagents: any[] = cfg.subagents || [];
        const skillNames: string[] = cfg.skills || [];

        // For each subagent record, also try to enrich with /api/skills/{name}
        const subagents = await Promise.all(rawSubagents.map(async (sa: any, i: number) => {
          let skillDetail: any = {};
          if (sa.name) {
            try {
              const res = await fetch(`/api/skills/${sa.name}`);
              if (res.ok) {
                skillDetail = await res.json();
              }
            } catch {}
          }
          return {
            id: `sub-${i}`,
            name: sa.name || `Sub-agent ${i + 1}`,
            skill_type: 'Skill',
            description: sa.description || skillDetail.description,
            prompt: sa.system_prompt || skillDetail.instructions,
            tags: skillDetail.tags,
            triggers: skillDetail.triggers,
            allowed_tools: skillDetail.allowed_tools,
            version: skillDetail.version,
            author: skillDetail.author,
          };
        }));

        // If no cfg.subagents existed but cfg.skills did, fall back to skills-only
        if (subagents.length === 0 && skillNames.length > 0) {
          for (let i = 0; i < skillNames.length; i++) {
            const name = skillNames[i];
            let skillDetail: any = {};
            try {
              const res = await fetch(`/api/skills/${name}`);
              if (res.ok) skillDetail = await res.json();
            } catch {}
            subagents.push({
              id: `skill-${i}`,
              name,
              skill_type: 'Skill',
              description: cfg.skill_descriptions?.[name] || skillDetail.description,
              prompt: skillDetail.instructions,
              tags: skillDetail.tags,
              triggers: skillDetail.triggers,
              allowed_tools: skillDetail.allowed_tools,
              version: skillDetail.version,
              author: skillDetail.author,
            });
          }
        }

        const normalized: AgentStructure = {
          id: agent?.id,
          name: agent?.name || 'Agent',
          description: agent?.description,
          model: cfg.model || 'minimax-m3',
          system_prompt: cfg.system_prompt,
          native_tools: cfg.native_tools || [],
          custom_tools: cfg.custom_tools || [],
          tools: cfg.tools || cfg.cli_tools || [],
          subagents,
          skills: skillNames,
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
