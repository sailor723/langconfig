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

  // No sub-agents: show native tools as small pills instead
  if (n === 0) {
    const tools = structure.main_agent.tools ?? [];
    const toolCount = tools.length;
    if (toolCount === 0) {
      return { nodes, edges };
    }
    // Spread tools below the main agent in a horizontal row
    const TOOL_W = 130;
    const TOOL_H = 32;
    const ROW_Y = center.y + 200;
    const SPACING = 160;
    const totalWidth = (toolCount - 1) * SPACING;
    tools.forEach((toolName, idx) => {
      const x = center.x - totalWidth / 2 + idx * SPACING - TOOL_W / 2;
      const id = `tool-${toolName}`;
      nodes.push({
        id,
        type: 'tool',
        position: { x, y: ROW_Y },
        data: { label: toolName },
        style: { width: TOOL_W, height: TOOL_H },
        draggable: true,
        selectable: true,
      });
      edges.push({
        id: `main-${id}`,
        source: 'main',
        target: id,
        type: 'smoothstep',
        animated: false,
        style: { stroke: '#3b82f6', strokeWidth: 1, opacity: 0.4 },
      });
    });
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