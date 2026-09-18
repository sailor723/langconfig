/**
 * PromptDetailTab — workspace tab showing the full content of a prompt.
 *
 * Opens when the user clicks a prompt entry in PromptBrowserSidebar.
 * Displays the prompt text in a clean, readable monospace view.
 */
import { useLayoutTokens } from './tokens';
import type { Tab } from './useLayout';

interface Props { tab: Tab }

export default function PromptDetailTab({ tab }: Props) {
  const t = useLayoutTokens();

  const { promptText, agentName, promptName } = (tab.data ?? {}) as {
    promptText: string;
    agentName?: string;
    promptName: string;
  };

  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
      {/* Header */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 10,
          padding: '16px 20px',
          borderBottom: `1px solid ${t.border}`,
          flexShrink: 0,
        }}
      >
        <span style={{ fontSize: 16 }}>📝</span>
        <div>
          <h2 style={{ fontSize: 16, fontWeight: 600, color: t.textPrimary, margin: 0 }}>
            {promptName}
          </h2>
          <p style={{ fontSize: 11, color: t.textMuted, margin: '2px 0 0 0' }}>
            {agentName || 'Standalone Prompt'}
            <span style={{ margin: '0 6px' }}>·</span>
            {promptText.length.toLocaleString()} characters
          </p>
        </div>
      </div>

      {/* Prompt content */}
      <div style={{ flex: 1, overflow: 'auto', padding: '16px 20px' }}>
        <div
          style={{
            background: t.bgContent,
            border: `1px solid ${t.border}`,
            borderRadius: 6,
            padding: 16,
            minHeight: 200,
          }}
        >
          <pre
            style={{
              margin: 0,
              fontFamily: '"SF Mono", "Fira Code", monospace',
              fontSize: 13,
              lineHeight: 1.6,
              color: t.textPrimary,
              whiteSpace: 'pre-wrap',
              wordBreak: 'break-word',
            }}
          >
            {promptText || '(empty prompt)'}
          </pre>
        </div>
      </div>
    </div>
  );
}
