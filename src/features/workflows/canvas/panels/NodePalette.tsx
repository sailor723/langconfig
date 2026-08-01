/**
 * Copyright (c) 2025 Cade Russell (Ghost Peony)
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */

import { memo, useState, useCallback, useRef, useEffect } from 'react';
import { Play, StopCircle, GitBranch, Repeat, UserCheck, Wrench, GripVertical, Sparkles } from 'lucide-react';

const STORAGE_KEY = 'langconfig-nodepalette-position';

interface DragPosition {
  x: number;
  y: number;
}

function loadSavedPosition(): DragPosition {
  try {
    const saved = localStorage.getItem(STORAGE_KEY);
    if (saved) {
      const pos = JSON.parse(saved);
      if (typeof pos.x === 'number' && typeof pos.y === 'number') {
        return pos;
      }
    }
  } catch { /* ignore */ }
  return { x: 10, y: 10 };
}

/**
 * Control node types that can be added to a workflow canvas.
 */
export interface ControlNodeTemplate {
  type: string;
  label: string;
  description: string;
  icon: typeof Play;
  color: string;
  bgColor: string;
}

export const CONTROL_NODE_TEMPLATES: ControlNodeTemplate[] = [
  {
    type: 'LLM_NODE',
    label: 'LLM',
    description: 'Direct LLM call with prompt — no tools or agent wrapping.',
    icon: Sparkles,
    color: '#a855f7',
    bgColor: 'rgba(168, 85, 247, 0.1)',
  },
  {
    type: 'START_NODE',
    label: 'Start',
    description: 'Workflow entry point.',
    icon: Play,
    color: '#10b981',
    bgColor: 'rgba(16, 185, 129, 0.1)',
  },
  {
    type: 'END_NODE',
    label: 'End',
    description: 'Workflow exit point.',
    icon: StopCircle,
    color: '#ef4444',
    bgColor: 'rgba(239, 68, 68, 0.1)',
  },
  {
    type: 'CONDITIONAL_NODE',
    label: 'Conditional',
    description: 'Branch flow based on a condition.',
    icon: GitBranch,
    color: '#8b5cf6',
    bgColor: 'rgba(139, 92, 246, 0.1)',
  },
  {
    type: 'LOOP_NODE',
    label: 'Loop',
    description: 'Repeat flow until exit condition.',
    icon: Repeat,
    color: '#3b82f6',
    bgColor: 'rgba(59, 130, 246, 0.1)',
  },
  {
    type: 'APPROVAL_NODE',
    label: 'Approval',
    description: 'Human-in-the-loop approval gate.',
    icon: UserCheck,
    color: '#f59e0b',
    bgColor: 'rgba(245, 158, 11, 0.1)',
  },
  {
    type: 'TOOL_NODE',
    label: 'Tool',
    description: 'Standalone tool call - no LLM reasoning.',
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
 * Draggable floating palette for adding control nodes to the canvas.
 * - Drag the **header bar** (the "Nodes" title bar) to reposition.
 * - Click a node item to add at canvas center.
 * - Drag a node item (HTML5 DnD) to drop at a specific position.
 * Position is persisted in localStorage.
 */
const NodePalette = memo(function NodePalette({
  onAddNode,
  isCollapsed,
  onToggleCollapse,
}: NodePaletteProps) {
  // ── Drag-to-move state ──
  const [position, setPosition] = useState<DragPosition>(loadSavedPosition);
  const [isDragging, setIsDragging] = useState(false);
  const dragRef = useRef<{ startX: number; startY: number; offsetX: number; offsetY: number } | null>(null);
  const didDragRef = useRef(false);
  const paletteRef = useRef<HTMLDivElement>(null);

  // Persist position changes
  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(position));
  }, [position]);

  // ── Drag start: record mouse offset from palette top-left ──
  const handleMouseDown = useCallback((e: React.MouseEvent) => {
    // Only allow drag on the header bar
    if (!paletteRef.current) return;
    const rect = paletteRef.current.getBoundingClientRect();
    dragRef.current = {
      startX: e.clientX,
      startY: e.clientY,
      offsetX: e.clientX - rect.left,
      offsetY: e.clientY - rect.top,
    };
    didDragRef.current = false;
    setIsDragging(true);
    e.preventDefault();
  }, []);

  // ── Drag move ──
  const handleMouseMove = useCallback((e: MouseEvent) => {
    if (!dragRef.current || !isDragging) return;
    if (
      Math.abs(e.clientX - dragRef.current.startX) > 3 ||
      Math.abs(e.clientY - dragRef.current.startY) > 3
    ) {
      didDragRef.current = true;
    }
    const newX = e.clientX - dragRef.current.offsetX;
    const newY = e.clientY - dragRef.current.offsetY;
    setPosition({ x: Math.max(0, newX), y: Math.max(0, newY) });
  }, [isDragging]);

  // ── Drag end ──
  const handleMouseUp = useCallback(() => {
    setIsDragging(false);
    dragRef.current = null;
  }, []);

  // Attach global mousemove/mouseup during drag
  useEffect(() => {
    if (!isDragging) return;
    window.addEventListener('mousemove', handleMouseMove);
    window.addEventListener('mouseup', handleMouseUp);
    return () => {
      window.removeEventListener('mousemove', handleMouseMove);
      window.removeEventListener('mouseup', handleMouseUp);
    };
  }, [isDragging, handleMouseMove, handleMouseUp]);

  const handleDragStart = (e: React.DragEvent<HTMLDivElement>, type: string) => {
    e.dataTransfer.setData('application/x-langconfig-node', type);
    e.dataTransfer.effectAllowed = 'move';
  };

  const handleClick = (type: string) => {
    onAddNode(type);
  };

  return (
    <div
      ref={paletteRef}
      className="fixed z-50 rounded-lg border shadow-lg overflow-hidden select-none"
      style={{
        left: position.x,
        top: position.y,
        backgroundColor: 'var(--color-panel, #ffffff)',
        borderColor: 'var(--color-border-dark)',
        width: isCollapsed ? '52px' : '200px',
        transition: isDragging ? 'none' : 'width 0.2s ease',
        cursor: isDragging ? 'grabbing' : 'default',
        boxShadow: isDragging
          ? '0 8px 32px rgba(0,0,0,0.25)'
          : '0 4px 16px rgba(0,0,0,0.12)',
      }}
    >
      {/* Header — acts as both drag handle and collapse toggle */}
      <div
        onMouseDown={handleMouseDown}
        onClick={() => {
          if (didDragRef.current) {
            didDragRef.current = false;
            return;
          }
          onToggleCollapse();
        }}
        className="w-full px-3 py-2.5 flex items-center justify-between text-xs font-bold uppercase tracking-wider border-b"
        style={{
          backgroundColor: 'var(--color-primary)',
          color: 'white',
          borderColor: 'var(--color-primary)',
          cursor: isDragging ? 'grabbing' : 'grab',
        }}
        title={isCollapsed ? 'Expand node palette' : 'Collapse node palette'}
      >
        <div className="flex items-center gap-1.5">
          <GripVertical className="w-3 h-3 opacity-70" />
          {isCollapsed ? (
            <Wrench className="w-4 h-4" />
          ) : (
            <span>Nodes</span>
          )}
        </div>
        {!isCollapsed && (
          <span className="text-base leading-none select-none">◀</span>
        )}
      </div>

      {/* Node buttons */}
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
                style={{ color: template.color }}
                onMouseEnter={(e) => { e.currentTarget.style.backgroundColor = template.bgColor; }}
                onMouseLeave={(e) => { e.currentTarget.style.backgroundColor = 'transparent'; }}
                title={`${template.label} - ${template.description}\n\nClick to add at center, or drag to position.`}
              >
                <Icon className="w-4 h-4 flex-shrink-0" />
                <div className="flex-1 min-w-0">
                  <div className="text-xs font-semibold leading-tight" style={{ color: 'var(--color-text-primary)' }}>
                    {template.label}
                  </div>
                  <div className="text-[10px] leading-tight opacity-70 truncate" style={{ color: 'var(--color-text-secondary)' }}>
                    {template.description}
                  </div>
                </div>
              </div>
            );
          })}

          <div
            className="mt-2 pt-2 border-t text-[10px] leading-tight"
            style={{
              borderColor: 'var(--color-border-dark)',
              color: 'var(--color-text-secondary)',
            }}
          >
            <strong>Click</strong> to add at center | <strong>Drag</strong> header to move
          </div>
        </div>
      )}
    </div>
  );
});

export default NodePalette;
