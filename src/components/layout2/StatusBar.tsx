/**
 * StatusBar — VS Code-style bottom bar.
 *
 * VS Code pattern:
 *   - 22px height
 *   - Blue background (#007acc) with white text
 *   - Left: default model (from localStorage), token count
 *   - Right: theme selector, running task indicator
 */
import { useEffect, useState } from 'react';
import { useLayoutTokens } from './tokens';

interface StatusBarProps {
  /** Optional override (e.g. selected node model); falls back to localStorage */
  model?: string;
  tokens?: number;
  task?: string | null;
}

const DEFAULT_MODEL_KEY = 'langconfig.defaultModel';

export default function StatusBar({ model, tokens, task }: StatusBarProps) {
  const t = useLayoutTokens();
  const [defaultModel, setDefaultModel] = useState(() => localStorage.getItem(DEFAULT_MODEL_KEY) || '');

  // Re-read localStorage when the user sets a new default in the Models sidebar
  useEffect(() => {
    const handler = (e: StorageEvent) => {
      if (e.key === DEFAULT_MODEL_KEY) setDefaultModel(e.newValue || '');
    };
    window.addEventListener('storage', handler);
    // Same-tab updates from setItem need a polling fallback since 'storage' is cross-tab only
    const interval = setInterval(() => {
      const fresh = localStorage.getItem(DEFAULT_MODEL_KEY) || '';
      if (fresh !== defaultModel) setDefaultModel(fresh);
    }, 500);
    return () => {
      window.removeEventListener('storage', handler);
      clearInterval(interval);
    };
  }, [defaultModel]);

  const displayModel = model || defaultModel;

  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        height: 22,
        minHeight: 22,
        padding: '0 10px',
        background: t.bgStatusBar,
        fontSize: 12,
        color: t.textWhite,
        userSelect: 'none',
      }}
    >
      {/* Left side */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
        {displayModel && <span style={{ opacity: 0.9 }}>{displayModel}</span>}
        {tokens !== undefined && (
          <span style={{ opacity: 0.7 }}>{tokens.toLocaleString()} tokens</span>
        )}
      </div>

      {/* Right side */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        {task && (
          <span style={{ display: 'flex', alignItems: 'center', gap: 4, opacity: 0.9 }}>
            <span style={{ animation: 'pulse 1s infinite' }}>●</span>
            {task}
          </span>
        )}
      </div>
    </div>
  );
}
