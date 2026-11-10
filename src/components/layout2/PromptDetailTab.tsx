/**
 * PromptDetailTab — workspace tab showing the full content of a prompt.
 *
 * Opens when the user clicks a prompt entry in PromptBrowserSidebar.
 *
 * A system prompt is **written in markdown** — role sections in `##`, hard rules in bold, output contracts in
 * tables or fenced blocks. Showing it in a `<pre>` meant reading it as source rather than as the document it is,
 * so it renders, and the monospace view stays one click away for whoever needs to copy the exact bytes.
 */
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import MarkdownText, { MarkdownBoundary } from './MarkdownText';
import { useLayoutTokens } from './tokens';
import type { Tab } from './useLayout';

interface Props { tab: Tab }

export default function PromptDetailTab({ tab }: Props) {
  const { t: tr } = useTranslation('chat');
  const t = useLayoutTokens();
  const [view, setView] = useState<'rendered' | 'source'>('rendered');

  const { promptText: rawText, agentName, promptName } = (tab.data ?? {}) as {
    promptText?: string;
    agentName?: string;
    promptName?: string;
  };
  // A restored tab or an agent with no prompt can arrive without the field, and `promptText.length` below would
  // throw — which is indistinguishable from a blank page.
  const promptText = typeof rawText === 'string' ? rawText : '';

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
            {promptName || '(untitled prompt)'}
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
          {promptText ? (
            <>
              <div style={{ display: 'flex', gap: 4, marginBottom: 10 }}>
                {(['rendered', 'source'] as const).map(mode => (
                  <button
                    key={mode}
                    onClick={() => setView(mode)}
                    data-active={view === mode}
                    style={{
                      fontSize: 10, height: 22, padding: '0 8px', cursor: 'pointer', borderRadius: 3,
                      border: `1px solid ${view === mode ? t.accent : t.border}`,
                      background: view === mode ? `${t.accent}18` : 'transparent',
                      color: view === mode ? t.accent : t.textMuted,
                    }}
                  >
                    {mode === 'rendered' ? tr('sv_rendered') : tr('sv_source')}
                  </button>
                ))}
              </div>
              {view === 'rendered' ? (
                <MarkdownBoundary text={promptText} fallbackStyle={{ color: t.textPrimary }}>
                  <MarkdownText text={promptText} tokens={t} />
                </MarkdownBoundary>
              ) : (
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
                  {promptText}
                </pre>
              )}
            </>
          ) : (
            <div style={{ color: t.textMuted, fontSize: 12 }}>(empty prompt)</div>
          )}
        </div>
      </div>
    </div>
  );
}
