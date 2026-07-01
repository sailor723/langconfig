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

const SUB_FAN_RADIUS_X = 320;
const SUB_FAN_RADIUS_Y = 220;

const TOOL_BASE_Y = 520;       // first row of tools below center

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
      description: 'The language model powering this agent',
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
      description: 'Defines the agent\'s behavior, workflow, and guidelines',
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

  // Common tool descriptions for better UX
  const toolDescMap: Record<string, string> = {
    web_search: 'Search the web via DuckDuckGo',
    tavily_search: 'AI-powered web search',
    web_fetch: 'Fetch and read webpage content',
    ls: 'List files in a directory',
    read_file: 'Read file contents',
    write_file: 'Write content to a file',
    edit_file: 'Edit an existing file',
    glob: 'Find files by name pattern',
    grep: 'Search file contents by pattern',
    reasoning_chain: 'Multi-step reasoning and analysis',
    task: 'Delegate work to sub-agents',
    memory_store: 'Store data in long-term memory',
    memory_recall: 'Recall data from long-term memory',
    graphindex_search: 'Search project documents (RAG)',
    graphindex_load: 'Load document into graph index',
    graphindex_list_docs: 'List indexed documents',
    graphindex_multi_doc_load: 'Load multiple documents',
  };

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
          prompt: sub.prompt || structure.system_prompt || '',
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

  // 4) Tools — arrange in 2 rows below center
  const tools = [...(structure.native_tools || []), ...(structure.tools || [])];
  if (tools.length > 0) {
    const perRow = Math.ceil(tools.length / 2);
    const toolSpacingX = 120;
    const toolSpacingY = 60;
    const row1Width = Math.min(perRow, tools.length) * toolSpacingX;
    const row2Width = (tools.length - perRow) * toolSpacingX;
    const startX1 = MAIN_X - row1Width / 2;
    const startX2 = MAIN_X - row2Width / 2;
    tools.forEach((tool, i) => {
      const row = i < perRow ? 0 : 1;
      const idxInRow = row === 0 ? i : i - perRow;
      const startX = row === 0 ? startX1 : startX2;
      const x = startX + idxInRow * toolSpacingX;
      const y = TOOL_BASE_Y + row * toolSpacingY;
      const id = `tool-${i}`;
      nodes.push({
        id,
        type: 'tool',
        position: { x, y },
        data: {
          label: tool,
          tool_type: 'native',
          description: toolDescMap[tool as keyof typeof toolDescMap] || undefined,
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
