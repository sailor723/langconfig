/**
 * ToolsPicker — native/custom tool grid shared by the agent editors.
 *
 * Pure presentation: the toggle handlers stay in each editor (AgentEditor
 * only updates React state, DeepAgentEditor also syncs jsonEdit), so this
 * component receives callbacks rather than owning state.
 */
import type { LayoutTokens } from './tokens';

export interface NativeTool {
  id: string;
  name: string;
  description: string;
}

export interface CustomTool {
  id: number;
  tool_id: string;
  name: string;
  description: string;
}

interface ToolsPickerProps {
  selectedNativeTools: string[];
  selectedCustomTools: string[];
  onToggleNative: (id: string) => void;
  onToggleCustom: (id: string) => void;
  showAllTools: boolean;
  onShowAllChange: (v: boolean) => void;
  toolsLoading: boolean;
  groupedByCategory: Record<string, NativeTool[]>;
  availableCustomTools: CustomTool[];
  t: LayoutTokens;
}

export default function ToolsPicker({
  selectedNativeTools,
  selectedCustomTools,
  onToggleNative,
  onToggleCustom,
  showAllTools,
  onShowAllChange,
  toolsLoading,
  groupedByCategory,
  availableCustomTools,
  t,
}: ToolsPickerProps) {
  const cardStyle: React.CSSProperties = {
    background: t.bgContent,
    border: `1px solid ${t.border}`,
    borderRadius: 4,
    padding: 10,
    marginBottom: 10,
  };
  const labelStyle: React.CSSProperties = {
    fontSize: 11,
    color: t.textMuted,
    textTransform: 'uppercase',
    letterSpacing: 0.4,
    marginBottom: 4,
  };
  const valueStyle: React.CSSProperties = {
    fontSize: 13,
    color: t.textPrimary,
  };

  const nativeCount = selectedNativeTools.length;
  const customCount = selectedCustomTools.length;
  const totalCount = nativeCount + customCount;
  const allNativeLoaded = Object.values(groupedByCategory).flat();

  // Reusable tool card (matches ModelCardsGridTab style)
  const toolCard = (
    tool: { id: string; name: string; description: string },
    checked: boolean,
    onToggle: () => void,
  ) => (
    <label
      key={tool.id}
      style={{
        display: 'flex', flexDirection: 'column', gap: 6,
        padding: 10, borderRadius: 6, cursor: 'pointer',
        border: `1px solid ${t.border}`,
        background: t.bgSidebar,
        minHeight: 80,
        boxSizing: 'border-box',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 8 }}>
        <input
          type="checkbox"
          checked={checked}
          onChange={onToggle}
          style={{ accentColor: t.accent, flexShrink: 0, marginTop: 2 }}
        />
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{
            color: t.textPrimary, fontWeight: 600, fontSize: 12,
            overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
          }}>
            {tool.name}
          </div>
          <div style={{
            fontSize: 10, color: t.textMuted, fontFamily: 'monospace',
            overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
          }}>
            {tool.id}
          </div>
        </div>
      </div>
      <div style={{
        fontSize: 11, color: t.textMuted, lineHeight: 1.4,
        display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical',
        overflow: 'hidden',
      }}>
        {tool.description}
      </div>
    </label>
  );

  const toggleBtn = (label: string, active: boolean, onClick: () => void) => (
    <button
      onClick={onClick}
      style={{
        padding: '2px 10px',
        fontSize: 11,
        border: `1px solid ${active ? t.accent : t.border}`,
        background: active ? t.accent + '20' : 'transparent',
        color: active ? t.accent : t.textMuted,
        borderRadius: 10,
        cursor: 'pointer',
        fontWeight: active ? 600 : 400,
      }}
    >
      {label}
    </button>
  );

  // Filter helper: when showAllTools=false, only include checked tools
  const filterTools = <T extends { id: string }>(tools: T[]): T[] =>
    showAllTools ? tools : tools.filter(tt => selectedNativeTools.includes(tt.id));

  return (
    <div style={{ padding: 4 }}>
      {/* Native tools grouped by category */}
      <div style={cardStyle}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
          <div style={labelStyle}>
            Native Tools ({nativeCount}/{allNativeLoaded.length} selected)
          </div>
          <div style={{ flex: 1 }} />
          {toggleBtn('All', showAllTools, () => onShowAllChange(true))}
          {toggleBtn('Selected', !showAllTools, () => onShowAllChange(false))}
        </div>
        {toolsLoading ? (
          <div style={{ ...valueStyle, color: t.textMuted, fontStyle: 'italic' }}>Loading tools...</div>
        ) : allNativeLoaded.length === 0 ? (
          <div style={{ ...valueStyle, color: t.textMuted, fontStyle: 'italic' }}>(none available)</div>
        ) : (
          Object.entries(groupedByCategory).map(([cat, tools]) => {
            const catTools = filterTools(tools);
            if (catTools.length === 0) return null;
            return (
              <div key={cat} style={{ marginBottom: 10 }}>
                <div style={{
                  fontSize: 10, color: t.textMuted, textTransform: 'uppercase',
                  letterSpacing: 0.3, marginBottom: 6, fontWeight: 600,
                }}>
                  {cat}
                </div>
                <div style={{
                  display: 'grid',
                  gridTemplateColumns: 'repeat(4, 1fr)',
                  gap: 8,
                }}>
                  {catTools.map(tool => toolCard(
                    tool,
                    selectedNativeTools.includes(tool.id),
                    () => onToggleNative(tool.id),
                  ))}
                </div>
              </div>
            );
          })
        )}
      </div>

      {/* Custom tools */}
      <div style={cardStyle}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
          <div style={labelStyle}>
            Custom Tools ({customCount}/{availableCustomTools.length} selected)
          </div>
          <div style={{ flex: 1 }} />
          {toggleBtn('All', showAllTools, () => onShowAllChange(true))}
          {toggleBtn('Selected', !showAllTools, () => onShowAllChange(false))}
        </div>
        {availableCustomTools.length === 0 ? (
          <div style={{ ...valueStyle, color: t.textMuted, fontStyle: 'italic' }}>
            (no custom tools — create one in the Tools activity)
          </div>
        ) : (
          <div style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(4, 1fr)',
            gap: 8,
          }}>
            {(showAllTools
              ? availableCustomTools
              : availableCustomTools.filter(tt => selectedCustomTools.includes(tt.tool_id))
            ).map(tool => toolCard(
              { id: tool.tool_id, name: tool.name, description: tool.description },
              selectedCustomTools.includes(tool.tool_id),
              () => onToggleCustom(tool.tool_id),
            ))}
          </div>
        )}
      </div>

      {/* Quick summary of selected tools as chips */}
      {totalCount > 0 && (
        <div style={cardStyle}>
          <div style={labelStyle}>Selected ({totalCount})</div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
            {selectedNativeTools.map(id => (
              <span key={`n-${id}`} style={{
                fontSize: 11, padding: '2px 6px', background: t.bgHover,
                border: `1px solid ${t.border}`, borderRadius: 3,
                color: t.textPrimary, fontFamily: 'monospace',
              }}>{id}</span>
            ))}
            {selectedCustomTools.map(id => (
              <span key={`c-${id}`} style={{
                fontSize: 11, padding: '2px 6px', background: t.bgHover,
                border: `1px solid ${t.accent}40`, borderRadius: 3,
                color: t.textPrimary, fontFamily: 'monospace',
              }}>{id}</span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
