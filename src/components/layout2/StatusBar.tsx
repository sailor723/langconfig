/**
 * StatusBar — thin horizontal bar at the bottom of the window.
 *
 * Shows the active model, token counts, and any running task status.
 * Modeled after VS Code's status bar — minimal and informational.
 */
import { useLayoutTokens } from './tokens';

interface StatusBarProps {
  /** Current model name (e.g. "GPT-4o") */
  model?: string;
  /** Current token usage */
  tokens?: number;
  /** Running task label (e.g. "Workflow Running") */
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
        padding: '0 12px',
        background: t.bgBase,
        borderTop: `1px solid ${t.border}`,
        fontSize: 11,
        color: t.textMuted,
        userSelect: 'none',
      }}
    >
      {/* Left side */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
        {model && (
          <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
            <span style={{ color: t.accent }}>●</span>
            {model}
          </span>
        )}
        {tokens !== undefined && (
          <span>{tokens.toLocaleString()} tokens</span>
        )}
      </div>

      {/* Right side */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
        {task && (
          <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
            <span style={{ animation: 'pulse 1s infinite' }}>○</span>
            {task}
          </span>
        )}
      </div>
    </div>
  );
}
