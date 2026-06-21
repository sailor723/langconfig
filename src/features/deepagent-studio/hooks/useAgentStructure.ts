/**
 * Hook to assemble a render-ready AgentStructure from the backend.
 * Pulls together: DeepAgent config + Skill details + Tool list.
 */

import { useEffect, useState } from 'react';
import apiClient from '@/lib/api-client';
import axios from 'axios';
import type { AgentStructure, MainAgentInfo, SubAgent, Capability } from '../types';

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
        // Fetch DeepAgent config
        const agentRes = await apiClient.getDeepAgent(agentId);
        const agent = (agentRes as any).data ?? agentRes;
        const config = agent.config ?? agent;

        // Fetch all skills (we'll filter by IDs)
        const skillIds: string[] = config.skills ?? [];
        let skillMap: Record<string, any> = {};
        if (skillIds.length > 0) {
          try {
            const baseURL = (apiClient as any).client?.defaults?.baseURL ?? 'http://localhost:8765';
            const skillsRes = await axios.get(`${baseURL}/api/skills`);
            const skills = (skillsRes as any).data ?? skillsRes;
            for (const s of skills) {
              skillMap[s.skill_id ?? s.id] = s;
            }
          } catch {
            // Skills endpoint may be unavailable — degrade gracefully
          }
        }

        if (cancelled) return;

        // Build MainAgentInfo
        const mainAgent: MainAgentInfo = {
          id: String(agent.id),
          name: config.name ?? agent.name ?? `Agent ${agent.id}`,
          description: config.description ?? '',
          model: config.model ?? 'unknown',
          system_prompt_preview: (config.system_prompt ?? '').slice(0, 200),
          temperature: config.temperature ?? 0.7,
          max_tokens: config.max_tokens ?? 4096,
          tools: config.native_tools ?? config.tools ?? [],
          middleware: config.middleware ?? [],
          subagents_config: config.subagents ?? [],
        };

        // Build sub-agents
        const subAgents: SubAgent[] = [];

        // From skills (auto-generated per-skill subagents)
        for (const skillId of skillIds) {
          const skill = skillMap[skillId];
          subAgents.push({
            id: skillId,
            name: skillId,
            description: skill?.description ?? `Skill sub-agent: ${skillId}`,
            source: 'skill',
            model: config.model,
            tools: skill?.allowed_tools ?? [],
            instructions_preview: skill?.instructions?.slice(0, 150),
            status: 'idle',
          });
        }

        // From user-configured subagents
        for (const sa of config.subagents ?? []) {
          if (subAgents.find(s => s.id === sa.name)) continue; // skip duplicate
          subAgents.push({
            id: sa.name,
            name: sa.name,
            description: sa.description ?? '',
            source: 'user',
            model: sa.model ?? config.model,
            tools: sa.tools ?? [],
            instructions_preview: sa.system_prompt?.slice(0, 150),
            status: 'idle',
          });
        }

        // Build capabilities
        const capabilities: Capability[] = [];
        for (const t of (config.native_tools ?? config.tools ?? []).slice(0, 12)) {
          capabilities.push({ type: 'tool', label: t, value: '', enabled: true });
        }
        if (config.use_local_sandbox) {
          capabilities.push({
            type: 'sandbox',
            label: 'Sandbox',
            value: config.sandbox_dir ?? 'outputs/',
            enabled: true,
          });
        }
        if (config.enable_memory || config.memory) {
          capabilities.push({ type: 'memory', label: 'Memory', value: 'enabled', enabled: true });
        }
        if (config.skill_router_model) {
          capabilities.push({
            type: 'router',
            label: 'Router LLM',
            value: config.skill_router_model,
            enabled: true,
          });
        }
        capabilities.push({
          type: 'prompt',
          label: 'System Prompt',
          value: `${(config.system_prompt ?? '').length} chars`,
          enabled: !!config.system_prompt,
        });

        const result: AgentStructure = {
          main_agent: mainAgent,
          sub_agents: subAgents,
          capabilities,
          meta: {
            fetched_at: new Date().toISOString(),
            skill_count: skillIds.length,
            tool_count: (config.native_tools ?? []).length,
            is_valid: true,
          },
        };

        if (!cancelled) setStructure(result);
      } catch (e: any) {
        if (!cancelled) setError(e?.message ?? 'Failed to load agent');
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();

    return () => { cancelled = true; };
  }, [agentId]);

  return { structure, loading, error };
}