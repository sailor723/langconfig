/**
 * AutoLayout v2 — central-core layout (LangChain aesthetic).
 * Main agent at center. Sub-agents arranged in a fan above.
 * Tools arranged in a row below.
 * InfoNodes (LLM, Prompt) flanking left/right.
 */

import { Node, Edge } from 'reactflow';
import type { AgentStructure } from '../types';

const MAIN_X = 400;
const MAIN_Y = 300;

const SUB_FAN_TOP = 80;        // sub-agents fan upward from center
const SUB_FAN_RADIUS_X = 320;
const SUB_FAN_RADIUS_Y = 220;

const TOOL_BASE_Y = 520;       // tools array below center
const TOOL_SPACING_X = 110;

const INFO_OFFSET_X = 240;
const INFO_Y = 300;

export function autoLayout(structure: AgentStructure): { nodes: Node[]; edges: Edge[] } {
  if (!structure) return { nodes: [], edges: [] };

  const nodes: Node[] = [];
  const edges: Edge[] = [];

  // 1) Main agent at center
  nodes.push({
    id: 'main',
    type: 'mainAgent',
    position: { x: MAIN_X, y: MAIN_Y },
    data: {
      label: structure.name || 'Agent',
      model: structure.model || 'unknown',
      description: structure.description,
      system_prompt: structure.system_prompt,
    },
    draggable: true,
  });

  // 2) InfoNodes — LLM (left), Prompt (right)
  nodes.push({
    id: 'info-llm',
    type: 'info',
    position: { x: MAIN_X - INFO_OFFSET_X, y: INFO_Y - 60 },
    data: {
      label: 'Model',
      value: structure.model || '—',
      icon: '🧠',
    },
    draggable: true,
  });
  edges.push({
    id: 'e-llm',
    source: 'main',
    target: 'info-llm',
    type: 'curve',
    style: { stroke: '#006DDD', strokeWidth: 1.5, opacity: 0.6 },
  });

  nodes.push({
    id: 'info-prompt',
    type: 'info',
    position: { x: MAIN_X + INFO_OFFSET_X, y: INFO_Y - 60 },
    data: {
      label: 'System Prompt',
      value: structure.system_prompt || '(empty — click to add one)',
      icon: '📜',
    },
    draggable: true,
  });
  edges.push({
    id: 'e-prompt',
    source: 'main',
    target: 'info-prompt',
    type: 'curve',
    style: { stroke: '#006DDD', strokeWidth: 1.5, opacity: 0.6 },
  });

  // 3) Sub-agents — fan layout upward
  const subs = structure.subagents || [];
  if (subs.length > 0) {
    const angleStep = Math.PI / Math.max(subs.length + 1, 4);
    const startAngle = Math.PI / 2; // start at top
    subs.forEach((sub: any, i: number) => {
      const angle = startAngle - (i + 0.5) * angleStep * (subs.length > 1 ? 1 : 0);
      const radiusScale = Math.min(subs.length, 4) * 0.5 + 1;
      const x = MAIN_X + Math.cos(angle - Math.PI / 2) * SUB_FAN_RADIUS_X * radiusScale;
      const y = MAIN_Y - Math.abs(Math.sin(angle - Math.PI / 2)) * SUB_FAN_RADIUS_Y - 50;

      nodes.push({
        id: `sub-${sub.id || i}`,
        type: 'subAgent',
        position: { x: Math.max(40, x - 70), y: Math.max(20, y - 30) },
        data: {
          label: sub.name || `Sub-agent ${i + 1}`,
          description: sub.description,
          skill_type: sub.skill_type || 'Skill',
        },
        draggable: true,
      });
      edges.push({
        id: `e-sub-${i}`,
        source: 'main',
        target: `sub-${sub.id || i}`,
        type: 'curve',
        style: { stroke: '#7FC8FF', strokeWidth: 2, opacity: 0.7 },
        animated: true,
      });
    });
  }

  // 4) Tools — horizontal row below
  const tools = [...(structure.native_tools || []), ...(structure.tools || [])];
  if (tools.length > 0) {
    const totalWidth = tools.length * TOOL_SPACING_X;
    const startX = MAIN_X - totalWidth / 2;
    tools.forEach((tool, i) => {
      const id = `tool-${i}`;
      nodes.push({
        id,
        type: 'tool',
        position: { x: startX + i * TOOL_SPACING_X, y: TOOL_BASE_Y },
        data: {
          label: tool,
          tool_type: 'native',
        },
        draggable: true,
      });
      edges.push({
        id: `e-tool-${i}`,
        source: 'main',
        target: id,
        type: 'curve',
        style: { stroke: '#7FC8FF', strokeWidth: 1.5, opacity: 0.5 },
      });
    });
  }

  return { nodes, edges };
}
