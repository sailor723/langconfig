/**
 * Copyright (c) 2025 Cade Russell (Ghost Peony)
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */

import { memo } from 'react';
import { Panel } from 'reactflow';
import { Play, StopCircle, GitBranch, Repeat, UserCheck, Wrench } from 'lucide-react';

/**
 * Control node types that can be added to a workflow canvas.
 * The `type` field matches the agentType used in NodeConfigPanel.tsx
 * and the backend executor's node handling.
 */
export interface ControlNodeTemplate {
  type: string;          // Matches agentType: START_NODE, END_NODE, CONDITIONAL_NODE, LOOP_NODE, APPROVAL_NODE, TOOL_NODE
  label: string;         // Display name
  description: string;   // Hover tooltip
  icon: typeof Play;     // lucide-react icon component
  color: string;         // Accent color for the button
  bgColor: string;       // Background color when hovered/active
}

export const CONTROL_NODE_TEMPLATES: ControlNodeTemplate[] = [
  {
    type: 'START_NODE',
    label: 'Start',
    description: 'Workflow entry point. Receives the initial input.',
    icon: Play,
    color: '#10b981',
    bgColor: 'rgba(16, 185, 129, 0.1)',
  },
  {
    type: 'END_NODE',
    label: 'End',
    description: 'Workflow exit point. Marks successful completion.',
    icon: StopCircle,
    color: '#ef4444',
    bgColor: 'rgba(239, 68, 68, 0.1)',
  },
  {
    type: 'CONDITIONAL_NODE',
    label: 'Conditional',
    description: 'Branch the flow based on a condition (if/else).',
    icon: GitBranch,
    color: '#8b5cf6',
    bgColor: 'rgba(139, 92, 246, 0.1)',
  },
  {
    type: 'LOOP_NODE',
    label: 'Loop',
    description: 'Repeat a sub-flow until an exit condition is met.',
    icon: Repeat,
    color: '#3b82f6',
    bgColor: 'rgba(59, 130, 246, 0.1)',
  },
  {
    type: 'APPROVAL_NODE',
    label: 'Approval',
    description: 'Human-in-the-loop approval gate. Pauses until a human approves.',
    icon: UserCheck,
    color: '#f59e0b',
    bgColor: 'rgba(245, 158, 11, 0.1)',
  },
  {
    type: 'TOOL_NODE',
    label: 'Tool',
    description: 'Standalone tool call. Runs a single tool (custom, MCP, or CLI) with fixed parameters - no LLM reasoning.',
    icon: Wrench,
    color: '#06b6d4',
    bgColor: 'rgba(6, 182, 212, 0.1)',
  },
];

interface NodePaletteProps {
  onAddNode: (type: string, position?: { x: number; y: number }) => void;
  isCollapsed: boolean;
  onToggleCollapse: () => void;
}

/**
 * Floating left-side panel listing all available control nodes.
 * Each item supports BOTH:
 *   1. Click - adds a node at the canvas center
 *   2. Drag - drops a node at the cursor position
 *
 * Drag uses the HTML5 Drag and Drop API with the custom data type
 * 'application/langconfig-node-type' to communicate which node was dragged.
 */
const NodePalette = memo(function NodePalette({
  onAddNode,
  isCollapsed,
  onToggleCollapse,
}: NodePaletteProps) {

  /**
   * Set the drag data so the canvas can identify which node to add.
   * The 'application/x-langconfig-node' MIME type is custom for this app.
   */
  const handleDragStart = (e: React.DragEvent<HTMLDivElement>, type: string) => {
    e.dataTransfer.setData('application/x-langconfig-node', type);
    e.dataTransfer.effectAllowed = 'move';
  };

  const handleClick = (type: string) => {
    onAddNode(type);
  };

  return (
    <Panel
      position="top-left"
      className="z-50"
      style={{ pointerEvents: 'auto', left: '10px', top: '10px' }}
    >
      <div
        className="rounded-lg border shadow-lg overflow-hidden"
        style={{
          backgroundColor: 'var(--color-panel, #ffffff)',
          borderColor: 'var(--color-border-dark)',
          width: isCollapsed ? '52px' : '200px',
          transition: 'width 0.2s ease',
        }}
      >
        {/* Header - acts as collapse/expand toggle */}
        <button
          onClick={onToggleCollapse}
          className="w-full px-3 py-2.5 flex items-center justify-between text-xs font-bold uppercase tracking-wider border-b"
          style={{
            backgroundColor: 'var(--color-primary)',
            color: 'white',
            borderColor: 'var(--color-primary)',
          }}
          title={isCollapsed ? 'Expand node palette' : 'Collapse node palette'}
        >
          {isCollapsed ? (
            <Wrench className="w-4 h-4" />
          ) : (
            <>
              <span>Nodes</span>
              <span className="text-base leading-none">{isCollapsed ? '▶' : '◀'}</span>
            </>
          )}
        </button>

        {/* Node buttons - hidden when collapsed */}
        {!isCollapsed && (
          <div className="p-2 space-y-1.5">
            {CONTROL_NODE_TEMPLATES.map((template) => {
              const Icon = template.icon;
              return (
                <div
                  key={template.type}
                  draggable
                  onDragStart={(e) => handleDragStart(e, template.type)}
                  onClick={() => handleClick(template.type)}
                  className="flex items-center gap-2 px-2.5 py-2 rounded cursor-grab active:cursor-grabbing transition-colors border border-transparent hover:border-current"
                  style={{
                    color: template.color,
                  }}
                  onMouseEnter={(e) => {
                    e.currentTarget.style.backgroundColor = template.bgColor;
                  }}
                  onMouseLeave={(e) => {
                    e.currentTarget.style.backgroundColor = 'transparent';
                  }}
                  title={`${template.label} - ${template.description}\n\nClick to add at canvas center, or drag to a specific position.`}
                >
                  <Icon className="w-4 h-4 flex-shrink-0" />
                  <div className="flex-1 min-w-0">
                    <div className="text-xs font-semibold leading-tight" style={{ color: 'var(--color-text-primary, #1a1a1a)' }}>
                      {template.label}
                    </div>
                    <div className="text-[10px] leading-tight opacity-70 truncate" style={{ color: 'var(--color-text-secondary, #6b7280)' }}>
                      {template.description}
                    </div>
                  </div>
                </div>
              );
            })}

            {/* Helper text */}
            <div
              className="mt-2 pt-2 border-t text-[10px] leading-tight"
              style={{
                borderColor: 'var(--color-border-dark)',
                color: 'var(--color-text-secondary, #6b7280)',
              }}
            >
              💡 <strong>Click</strong> to add at center, or <strong>drag</strong> to position.
            </div>
          </div>
        )}
      </div>
    </Panel>
  );
});

export default NodePalette;
