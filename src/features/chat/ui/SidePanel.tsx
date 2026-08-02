/**
 * SidePanel — resizable right-side panel wrapper (Metrics / Files).
 *
 * Renders a drag handle on the left edge plus the panel content at the
 * caller-provided width. Shared by ChatPage and GlobalChatModal so the
 * resize markup isn't duplicated.
 */
import { GripVertical } from 'lucide-react';

interface SidePanelProps {
  /** Current panel width in px */
  width: number;
  /** True while the panel is being resized (highlights the handle) */
  isResizing: boolean;
  /** Mouse-down handler that starts the drag resize */
  onResizeStart: (e: React.MouseEvent) => void;
  children: React.ReactNode;
}

export default function SidePanel({ width, isResizing, onResizeStart, children }: SidePanelProps) {
  return (
    <div className="flex flex-shrink-0" style={{ width }}>
      {/* Drag handle — left edge of the panel */}
      <div
        onMouseDown={onResizeStart}
        className="w-2 cursor-col-resize flex items-center justify-center hover:bg-primary/10 active:bg-primary/20 transition-colors flex-shrink-0"
        style={{
          backgroundColor: isResizing ? 'var(--color-primary)' : 'transparent',
        }}
      >
        <GripVertical className="w-3 h-3 opacity-30 hover:opacity-60 transition-opacity" />
      </div>
      {/* Panel content */}
      <div className="flex-1 min-w-0 border-l" style={{ borderColor: 'var(--color-border-dark)' }}>
        {children}
      </div>
    </div>
  );
}
