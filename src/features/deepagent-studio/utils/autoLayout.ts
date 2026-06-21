/**
 * Auto-layout for DeepAgent Studio:
 *   - Main agent at center
 *   - LLM (InfoNode) on the left
 *   - Prompt (InfoNode) on the right
 *   - Tools as pills at the bottom (when no sub-agents)
 *   - Sub-agents in a ring around main (when present)
 */

import type { Node, Edge } from 'reactflow';
import type { AgentStructure } from '../types';

/** Snap to 10px grid so edges and boxes align cleanly. */
const snap = (n: number) => Math.round(n / 10) * 10;

export interface LayoutResult {
  nodes: Node[];
  edges: Edge[];
}

const MAIN_W = 160;
const MAIN_H = 110;
const INFO_W = 170;
const INFO_H = 130;
const PROMPT_W = 200;
const PROMPT_H = 200;
const SUB_W = 130;
const SUB_H = 80;
const RING_RADIUS = 260;

// Claude theme — warm orange/cream professional palette
const THEMES = {
  llm: { bg: '#F5E6DC', accent: '#C75F3D', border: '#D97757' },
  prompt: { bg: '#FAF9F5', accent: '#A85A2E', border: '#C75F3D' },
  tool: { accent: '#C8B6A6' },
  main: { bg: '#D97757', accent: '#FFFFFF', border: '#A85A2E' },
};

export function buildLayout(structure: AgentStructure): LayoutResult {
  const nodes: Node[] = [];
  const edges: Edge[] = [];

  // Center of a typical viewport — main agent here so it appears centered
  const center = { x: 500, y: 280 };

  // Main agent — center
  nodes.push({
    id: 'main',
    type: 'mainAgent',
    position: { x: snap(center.x - MAIN_W / 2), y: snap(center.y - MAIN_H / 2) },
    data: {
      label: structure.main_agent.name,
      model: structure.main_agent.model,
      description: structure.main_agent.description,
    },
    style: { width: MAIN_W, height: MAIN_H },
    draggable: true,
    selectable: true,
  });

  // LLM info node — LEFT of main
  nodes.push({
    id: 'info-llm',
    type: 'info',
    position: { x: snap(center.x - MAIN_W / 2 - INFO_W - 60), y: snap(center.y - INFO_H / 2) },
    data: {
      kind: 'llm',
      label: 'LLM',
      model: structure.main_agent.model,
      temperature: structure.main_agent.temperature,
      max_tokens: structure.main_agent.max_tokens,
      bg: THEMES.llm.bg,
      accent: THEMES.llm.accent,
      border: THEMES.llm.border,
    },
    style: { width: INFO_W, height: INFO_H },
    draggable: true,
    selectable: true,
  });
  edges.push({
    id: 'main-info-llm',
    source: 'main',
    sourceHandle: 'llm-out',
    target: 'info-llm',
    type: 'smoothstep',
    animated: false,
    style: { stroke: THEMES.llm.accent, strokeWidth: 1.5, opacity: 0.6 },
  });

  // Prompt info node — RIGHT of main
  nodes.push({
    id: 'info-prompt',
    type: 'info',
    position: { x: snap(center.x + MAIN_W / 2 + 60), y: snap(center.y - PROMPT_H / 2) },
    data: {
      kind: 'prompt',
      label: 'System Prompt',
      prompt: structure.main_agent.system_prompt_preview,
      bg: THEMES.prompt.bg,
      accent: THEMES.prompt.accent,
      border: THEMES.prompt.border,
    },
    style: { width: PROMPT_W, height: PROMPT_H },
    draggable: true,
    selectable: true,
  });
  edges.push({
    id: 'main-info-prompt',
    source: 'main',
    sourceHandle: 'prompt-out',
    target: 'info-prompt',
    type: 'smoothstep',
    animated: false,
    style: { stroke: THEMES.prompt.accent, strokeWidth: 1.5, opacity: 0.6 },
  });

  // Tools + Sub-agents
  const tools = structure.main_agent.tools ?? [];
  const subAgents = structure.sub_agents;

  if (subAgents.length > 0) {
    // Sub-agents in a ring
    const n = subAgents.length;
    subAgents.forEach((sa, idx) => {
      const angle = (2 * Math.PI * idx) / n - Math.PI / 2; // start at top
      const x = snap(center.x + RING_RADIUS * Math.cos(angle) - SUB_W / 2);
      const y = snap(center.y + RING_RADIUS * Math.sin(angle) - SUB_H / 2);

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
      edges.push({
        id: `main-${sa.id}`,
        source: 'main',
        sourceHandle: 'tools-out',
        target: sa.id,
        type: 'smoothstep',
        animated: false,
        style: { stroke: '#A85A2E', strokeWidth: 1.5, opacity: 0.5 },
      });
    });
  }

  // Tools as pills at the BOTTOM (always shown if any).
  // Wrap into multiple rows when there are too many to fit on one row.
  if (tools.length > 0) {
    const TOOL_W = 200;
    const TOOL_H = 90;
    const SPACING = 220;
    const PER_ROW = 4;  // wrap every 4 tools to a new row
    tools.forEach((toolName, idx) => {
      const row = Math.floor(idx / PER_ROW);
      const col = idx % PER_ROW;
      const itemsInThisRow = Math.min(PER_ROW, tools.length - row * PER_ROW);
      const rowWidth = (itemsInThisRow - 1) * SPACING;
      const x = snap(center.x - rowWidth / 2 + col * SPACING - TOOL_W / 2);
      const y = snap(center.y + MAIN_H / 2 + 180 + row * (TOOL_H + 20));
      const id = `tool-${toolName}`;
      nodes.push({
        id,
        type: 'tool',
        position: { x, y },
        data: { label: toolName },
        style: { width: TOOL_W, height: TOOL_H },
        draggable: true,
        selectable: true,
      });
      edges.push({
        id: `main-${id}`,
        source: 'main',
        sourceHandle: 'tools-out',
        target: id,
        type: 'smoothstep',
        animated: false,
        style: { stroke: THEMES.tool.accent, strokeWidth: 1, opacity: 0.4 },
      });
    });
  }

  return { nodes, edges };
}