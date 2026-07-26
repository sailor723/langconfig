/**
 * StatusBar — VS Code-style bottom bar.
 *
 * VS Code pattern:
 *   - 22px height
 *   - Blue background (#007acc) with white text
 *   - Left: model name, token count
 *   - Right: running task indicator
 */
import { useLayoutTokens } from './tokens';

interface StatusBarProps {
  model?: string;
  tokens?: number;
  task?: string | null;
}

export default function StatusBar({ model, tokens, task }: StatusBarProps) {
  const t = useLayoutTokens();

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
        {model && <span style={{ opacity: 0.9 }}>{model}</span>}
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
