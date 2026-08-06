/**
 * Graph Engineering studio page — the "workbench" for code-defined LangGraph
 * agents: canvas (graph structure), run console, inspector, and chat input.
 *
 * Backed by the native graph_studio router on the LangConfig backend.
 */
import { useEffect, useRef, useState, type MouseEvent as ReactMouseEvent } from 'react';
import { useLayoutTokens } from '../../components/layout2/tokens';
import { studio, useStudioState } from './studioStore';
import { GraphCanvas } from './GraphCanvas';
import RunConsole from './RunConsole';
import Inspector from './Inspector';

// Rail width clamp (chat console + inspector).
const RAIL_MIN = 240;
const RAIL_MAX = 640;
const RAIL_DEFAULT = 300;

export default function GraphStudioPage() {
  const t = useLayoutTokens();
  const { assistants, activeAssistantId, apiOnline, running } = useStudioState();
  // Resizable right rail width (px).
  const [railWidth, setRailWidth] = useState(RAIL_DEFAULT);
  const railDragRef = useRef<{ startX: number; startWidth: number } | null>(null);

  // Drag the rail divider: dragging left widens the rail (width = start - dx).
  const onRailResizeStart = (e: ReactMouseEvent) => {
    e.preventDefault();
    railDragRef.current = { startX: e.clientX, startWidth: railWidth };
    const onMove = (ev: MouseEvent) => {
      const drag = railDragRef.current;
      if (!drag) return;
      const next = drag.startWidth - (ev.clientX - drag.startX);
      setRailWidth(Math.min(RAIL_MAX, Math.max(RAIL_MIN, next)));
    };
    const onUp = () => {
      railDragRef.current = null;
      window.removeEventListener('mousemove', onMove);
      window.removeEventListener('mouseup', onUp);
    };
    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', onUp);
  };

  // Load the code-defined assistants on mount.
  useEffect(() => {
    void studio.loadAssistants();
  }, []);

  const active = assistants.find((a) => a.assistant_id === activeAssistantId);

  return (
    <div
      style={{
        flex: 1,
        minHeight: 0,
        display: 'flex',
        flexDirection: 'column',
        background: t.bgContent,
        color: t.textPrimary,
        overflow: 'hidden',
      }}
    >
      {/* Header */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 8,
          height: 36,
          padding: '0 12px',
          flexShrink: 0,
          background: t.bgTabBar,
          borderBottom: `1px solid ${t.border}`,
        }}
      >
        <span style={{ fontSize: 11, fontWeight: 600, textTransform: 'uppercase', letterSpacing: 0.6, color: t.textMuted }}>
          Graph Engineering
        </span>
        <span style={{ width: 1, height: 14, background: t.border }} />
        <span style={{ fontSize: 12.5, color: t.textPrimary }}>{active?.name ?? '—'}</span>
        {running && (
          <span style={{ fontSize: 11, color: t.accent, display: 'flex', alignItems: 'center', gap: 4 }}>
            <span style={{ width: 6, height: 6, borderRadius: '50%', background: t.accent }} />
            running
          </span>
        )}
        <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 5, fontSize: 11, color: t.textDim }}>
          <span style={{ width: 7, height: 7, borderRadius: '50%', background: apiOnline ? '#4caf50' : '#e5484d' }} />
          {apiOnline ? 'connected' : 'offline'}
        </div>
      </div>

      {/* Body: canvas + resizable right rail */}
      <div style={{ flex: 1, minHeight: 0, display: 'flex' }}>
        <main style={{ flex: 1, minWidth: 0 }}>
          <GraphCanvas />
        </main>
        {/* Drag handle to resize the chat/inspector rail */}
        <div
          onMouseDown={onRailResizeStart}
          title="Drag to resize"
          style={{
            width: 4,
            flexShrink: 0,
            cursor: 'col-resize',
            background: t.border,
            transition: 'background 0.15s ease',
          }}
          onMouseEnter={(e) => (e.currentTarget.style.background = t.accent)}
          onMouseLeave={(e) => (e.currentTarget.style.background = t.border)}
        />
        <aside
          style={{
            width: railWidth,
            flexShrink: 0,
            display: 'flex',
            flexDirection: 'column',
            minHeight: 0,
            background: t.bgSidebar,
            borderLeft: `1px solid ${t.border}`,
          }}
        >
          <RunConsole />
          <div style={{ flex: 1, minHeight: 0, overflow: 'hidden' }}>
            <Inspector />
          </div>
        </aside>
      </div>
    </div>
  );
}
