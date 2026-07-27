/**
 * StatusBar — VS Code-style bottom bar.
 *
 * VS Code pattern:
 *   - 22px height
 *   - Blue background (#007acc) with white text
 *   - Left: model name, token count
 *   - Right: theme selector, running task indicator
 */
import { useLayoutTokens } from './tokens';
import { useTheme } from '../../lib/themes';

interface StatusBarProps {
  model?: string;
  tokens?: number;
  task?: string | null;
}

/** Theme display config for the theme switcher */
const THEME_OPTIONS = [
  { name: 'dark',       label: 'Dark',  color: '#1e1e1e' },
  { name: 'claude',     label: 'Warm',  color: '#d97706' },
  { name: 'langconfig', label: 'Light', color: '#2E5C8A' },
] as const;

export default function StatusBar({ model, tokens, task }: StatusBarProps) {
  const t = useLayoutTokens();
  const { theme, setTheme } = useTheme();

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
        {/* Theme selector — Obsidian-style dark/warm/light dots */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 4, marginRight: 4 }}>
          {THEME_OPTIONS.map(opt => {
            const active = theme.name === opt.name;
            return (
              <button
                key={opt.name}
                onClick={() => setTheme(opt.name as any)}
                title={`${opt.label} theme`}
                style={{
                  width: active ? 10 : 8,
                  height: active ? 10 : 8,
                  borderRadius: '50%',
                  background: active ? '#fff' : opt.color,
                  border: active ? `2px solid ${opt.color}` : 'none',
                  cursor: 'pointer',
                  padding: 0,
                  transition: 'all 0.15s ease',
                }}
              />
            );
          })}
        </div>

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
