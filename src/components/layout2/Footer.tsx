/**
 * Footer — thin bottom bar carrying the app name and company copyright line.
 * Mounted once in the app shell (App.tsx) so it appears at the foot of
 * every page: app name on the left, copyright pushed to the right edge.
 */
import { useLayoutTokens } from './tokens';

export default function Footer() {
  const t = useLayoutTokens();

  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        height: 20,
        minHeight: 20,
        padding: '0 24px',
        background: t.bgBase,
        borderTop: `1px solid ${t.border}`,
        fontSize: 11,
        color: t.textMuted,
        userSelect: 'none',
      }}
    >
      {/* App name — bottom left */}
      <span>Carrier Studio</span>
      {/* Company copyright — bottom right, padded from the edge */}
      <span style={{ paddingRight: 12 }}>Copyright © EBL 2026</span>
    </div>
  );
}
