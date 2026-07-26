/**
 * NodeSidebar — right-side panel for configuring the selected
 * canvas node (agent, tool, model, etc.).
 *
 * Appears when a user clicks a node in the workflow canvas
 * and disappears when they deselect. Inspired by Obsidian's
 * right sidebar (outline/backlinks/graph).
 */
import { useLayoutState } from './useLayout';
import { useLayoutTokens } from './tokens';
import { X } from 'lucide-react';

// ── Content mappings ─────────────────────────────────────
// Renders the appropriate form/config panel based on
// rightPanelContent type.

interface ContentRenderer {
  label: string;
  render: () => React.ReactNode;
}

const CONTENT_RENDERERS: Record<string, ContentRenderer> = {
  'node-config': {
    label: 'Node Config',
    render: () => <NodeConfigPlaceholder />,
  },
};

function NodeConfigPlaceholder() {
  const t = useLayoutTokens();
  return (
    <div style={{ padding: 12 }}>
      <div style={{ marginBottom: 16 }}>
        <label style={{ display: 'block', fontSize: 11, color: t.textMuted, marginBottom: 4 }}>
          Model
        </label>
        <select
          style={{
            width: '100%',
            padding: '6px 8px',
            borderRadius: 6,
            border: `1px solid ${t.border}`,
            background: t.bgInput,
            color: t.textPrimary,
            fontSize: 13,
          }}
        >
          <option>GPT-4o</option>
          <option>GPT-4o-mini</option>
          <option>Claude 3.5 Sonnet</option>
        </select>
      </div>
    </div>
  );
}

export default function NodeSidebar() {
  const { rightPanelOpen, rightPanelContent, closeRightPanel } = useLayoutState();
  const t = useLayoutTokens();

  if (!rightPanelOpen || !rightPanelContent) return null;

  const renderer = CONTENT_RENDERERS[rightPanelContent];

  return (
    <div
      style={{
        width: 320,
        minWidth: 320,
        background: t.bgBase,
        borderLeft: `1px solid ${t.border}`,
        display: 'flex',
        flexDirection: 'column',
        overflowY: 'auto',
      }}
    >
      {/* Header */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '10px 12px',
          borderBottom: `1px solid ${t.border}`,
        }}
      >
        <span style={{ fontSize: 13, fontWeight: 600, color: t.textPrimary }}>
          {renderer?.label ?? 'Properties'}
        </span>
        <button
          onClick={closeRightPanel}
          style={{
            width: 24, height: 24,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            background: 'transparent', border: 'none', borderRadius: 4,
            color: t.textMuted, cursor: 'pointer',
          }}
        >
          <X size={16} />
        </button>
      </div>

      {/* Content */}
      {renderer?.render()}
    </div>
  );
}
