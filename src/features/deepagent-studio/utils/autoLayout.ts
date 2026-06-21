/**
 * Auto-layout for DeepAgent Studio: main agent center, sub-agents in a ring.
 *
 * Uses simple trigonometry (no dagre dependency) to keep bundle small.
 * Result is fed to ReactFlow as Node[] with absolute positions.
 */

import type { Node, Edge } from 'reactflow';
import type { AgentStructure } from '../types';

export interface LayoutResult {
  nodes: Node[];
  edges: Edge[];
}

const MAIN_W = 280;
const MAIN_H = 160;
const SUB_W = 180;
const SUB_H = 100;
const RING_RADIUS = 320;

export function buildLayout(structure: AgentStructure): LayoutResult {
  const nodes: Node[] = [];
  const edges: Edge[] = [];

  // Center of a typical viewport — main agent here so it appears centered
  const center = { x: 500, y: 280 };

  // Main agent — center
  nodes.push({
    id: 'main',
    type: 'mainAgent',
    position: { x: center.x - MAIN_W / 2, y: center.y - MAIN_H / 2 },
    data: {
      label: structure.main_agent.name,
      model: structure.main_agent.model,
      prompt_preview: structure.main_agent.system_prompt_preview,
      temperature: structure.main_agent.temperature,
      max_tokens: structure.main_agent.max_tokens,
      middleware: structure.main_agent.middleware,
    },
    style: { width: MAIN_W, height: MAIN_H },
    draggable: true,
    selectable: true,
  });

  // Sub-agents — in a ring around main
  const n = structure.sub_agents.length;
  if (n === 0) {
    return { nodes, edges };
  }

  structure.sub_agents.forEach((sa, idx) => {
    const angle = (2 * Math.PI * idx) / n - Math.PI / 2; // start at top
    const x = center.x + RING_RADIUS * Math.cos(angle) - SUB_W / 2;
    const y = center.y + RING_RADIUS * Math.sin(angle) - SUB_H / 2;

    nodes.push({
      id: sa.id,
      type: 'subAgent',
      position: { x, y },
      data: {
        label: sa.name,
        description: sa.description,
        source: sa.source,
        tools: sa.tools,
        instructions_preview: sa.instructions_preview,
        status: sa.status,
      },
      style: { width: SUB_W, height: SUB_H },
      draggable: true,
      selectable: true,
    });

    // Edge: main → sub-agent (delegation)
    edges.push({
      id: `main-${sa.id}`,
      source: 'main',
      target: sa.id,
      type: 'smoothstep',
      animated: false,
      style: {
        stroke: 'var(--color-primary)',
        strokeWidth: 1.5,
        opacity: 0.5,
      },
    });
  });

  return { nodes, edges };
}