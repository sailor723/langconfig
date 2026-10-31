/**
 * UserPopover — "who am I" in the activity bar.
 *
 * Why it exists: with accounts, "which person am I signed in as?" stops being
 * obvious. Two people share a screen, someone inherits a browser tab, a LAN user
 * wonders why the app knows their name. This popover answers it and offers the two
 * actions an account has.
 *
 * It also states the one fact people get wrong, in the place they look:
 *   - **Accounts are not isolation.** Everyone in this install sees the same
 *     projects, agents and knowledge.
 *
 * Sign in and sign out both live on the server now: browsers sign in on the
 * dedicated page at /signin and get an opaque session cookie (7-day sliding),
 * which this popover's Sign out revokes. HTTP Basic still works for scripts
 * (curl -u), and a browser holding a cached Basic credential is suppressed by the
 * sign-out marker until it signs in again.
 */
import { useEffect, useRef, useState } from 'react';
import { useLayoutTokens } from './tokens';
import apiClient from '../../lib/api-client';
import type { UserSummary } from '../../lib/api/users';
import { Loader, LogOut, ShieldCheck, UserRound, Users } from 'lucide-react';

interface UserPopoverProps {
  anchorRef: React.RefObject<HTMLElement | null>;
  onClose: () => void;
  onOpenAccount: () => void;
  onOpenUsers: () => void;
}

export default function UserPopover({
  anchorRef,
  onClose,
  onOpenAccount,
  onOpenUsers,
}: UserPopoverProps) {
  const t = useLayoutTokens();
  const popoverRef = useRef<HTMLDivElement | null>(null);
  const [me, setMe] = useState<UserSummary | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    apiClient
      .getMe()
      .then((r) => {
        if (!cancelled) setMe(r.data);
      })
      .catch(() => {
        if (!cancelled) setFailed(true);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    const onMouseDown = (e: MouseEvent) => {
      const target = e.target as Node;
      if (
        popoverRef.current &&
        !popoverRef.current.contains(target) &&
        anchorRef.current &&
        !anchorRef.current.contains(target)
      ) {
        onClose();
      }
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('mousedown', onMouseDown);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onMouseDown);
      document.removeEventListener('keydown', onKey);
    };
  }, [anchorRef, onClose]);

  const rowStyle: React.CSSProperties = {
    display: 'flex',
    alignItems: 'center',
    gap: 10,
    width: '100%',
    padding: '8px 12px',
    border: 'none',
    background: 'transparent',
    color: t.textPrimary,
    fontSize: 12.5,
    textAlign: 'left',
    cursor: 'pointer',
  };

  return (
    <div
      ref={popoverRef}
      style={{
        position: 'absolute',
        left: 56,
        bottom: 0,
        width: 268,
        background: t.bgSidebar,
        border: `1px solid ${t.border}`,
        borderRadius: 8,
        boxShadow: '0 8px 32px rgba(0,0,0,0.4)',
        zIndex: 1000,
        overflow: 'hidden',
      }}
    >
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 10,
          padding: '12px 12px 10px',
          borderBottom: `1px solid ${t.border}`,
        }}
      >
        <div
          style={{
            width: 30,
            height: 30,
            borderRadius: 15,
            background: t.accent,
            color: '#fff',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            fontSize: 13,
            fontWeight: 600,
            flexShrink: 0,
          }}
        >
          {(me?.username ?? '?').slice(0, 1).toUpperCase()}
        </div>
        <div style={{ minWidth: 0 }}>
          {failed ? (
            <div style={{ fontSize: 12, color: t.textMuted }}>Not signed in</div>
          ) : me ? (
            <>
              <div
                style={{
                  fontSize: 12.5,
                  fontWeight: 600,
                  color: t.textPrimary,
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                  whiteSpace: 'nowrap',
                }}
              >
                {me.display_name || me.username}
              </div>
              <div style={{ fontSize: 11, color: t.textMuted, display: 'flex', alignItems: 'center', gap: 4 }}>
                {me.role === 'admin' && <ShieldCheck size={11} />}
                {me.role === 'admin' ? 'Administrator' : 'Member'}
                {me.username ? ` · ${me.username}` : ''}
              </div>
            </>
          ) : (
            <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, color: t.textMuted }}>
              <Loader size={12} style={{ animation: 'spin 1s linear infinite' }} /> Loading…
            </div>
          )}
        </div>
      </div>

      <div style={{ padding: '4px 0' }}>
        <button
          style={rowStyle}
          onClick={() => {
            onClose();
            onOpenAccount();
          }}
          onMouseEnter={(e) => (e.currentTarget.style.background = t.bgHover)}
          onMouseLeave={(e) => (e.currentTarget.style.background = 'transparent')}
        >
          <UserRound size={14} /> Your account…
        </button>

        {me?.role === 'admin' && (
          <button
            style={rowStyle}
            onClick={() => {
              onClose();
              onOpenUsers();
            }}
            onMouseEnter={(e) => (e.currentTarget.style.background = t.bgHover)}
            onMouseLeave={(e) => (e.currentTarget.style.background = 'transparent')}
          >
            <Users size={14} /> Users…
          </button>
        )}

        {/* A full navigation, not a fetch: the backend revokes the session, clears
            the cookie and redirects to the sign-in page. Client-side state cannot do
            this — the server owns the session. */}
        <button
          style={{ ...rowStyle, borderTop: `1px solid ${t.border}`, marginTop: 4 }}
          onClick={() => {
            onClose();
            window.location.assign('/api/auth/logout');
          }}
          onMouseEnter={(e) => (e.currentTarget.style.background = t.bgHover)}
          onMouseLeave={(e) => (e.currentTarget.style.background = 'transparent')}
        >
          <LogOut size={14} /> Sign out
        </button>
      </div>

      <div
        style={{
          padding: '8px 12px 10px',
          borderTop: `1px solid ${t.border}`,
          fontSize: 10.5,
          lineHeight: 1.5,
          color: t.textMuted,
        }}
      >
        Signing out ends this browser&apos;s session on the server. A browser that
        signed in through the old Basic-auth prompt also has its saved credential
        suppressed until it signs in again.
      </div>
    </div>
  );
}
