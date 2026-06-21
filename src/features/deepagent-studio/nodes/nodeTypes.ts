/**
 * ReactFlow node type registry for DeepAgent Studio.
 */

import MainAgentNode from './MainAgentNode';
import SubAgentNode from './SubAgentNode';
import ToolNode from './ToolNode';
import InfoNode from './InfoNode';

export const nodeTypes = {
  mainAgent: MainAgentNode,
  subAgent: SubAgentNode,
  tool: ToolNode,
  info: InfoNode,
};