/**
 * Account & Users dialogs.
 *
 * Two surfaces, deliberately separated the same way the API is:
 *
 *   - **AccountDialog** (everyone) — who am I, rename myself, change my own
 *     password. Changing a password asks for the current one even though the
 *     browser is already authenticated: an unlocked laptop is not consent.
 *   - **UsersDialog** (admins) — list/create/promote/disable/reset. The last
 *     admin cannot be demoted or disabled, and nobody can lock themselves out;
 *     both guards live on the server too, so a UI that forgets them is not a
 *     security hole.
 *
 * Neither dialog logs anyone in or out. Authentication is the browser's Basic
 * prompt against the LAN gate, so "sign out" is a browser action (private
 * window, or quit the browser) — there is no token to discard here.
 *
 * Opened by window events (`account:open`, `users:open`) from the user popover in
 * the activity bar, matching how the settings modal is opened by `settings:open`.
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useLayoutTokens } from './tokens';
import apiClient from '../../lib/api-client';
import type { UserSummary } from '../../lib/api/users';
import { AtSign, Ban, CheckCircle2, KeyRound, Loader, ShieldCheck, UserRound, X } from 'lucide-react';

/**
 * One 24px icon button for the users table.
 *
 * Why a component instead of three inline styles: the actions kept drifting (a
 * red trash for "disable", a bare text button, no hover state), and the row is
 * the one place an admin clicks destructive things by reflex. One shape, one
 * hover, one disabled look — the `title` carries the wording.
 */
function IconAction({
  title,
  onClick,
  active = false,
  disabled = false,
  tone = 'plain',
  children,
}: {
  title: string;
  onClick: () => void;
  active?: boolean;
  disabled?: boolean;
  tone?: 'plain' | 'danger' | 'ok' | 'muted';
  children: React.ReactNode;
}) {
  const t = useLayoutTokens();
  const colour =
    tone === 'danger' ? '#f87171' : tone === 'ok' ? '#4ade80' : tone === 'muted' ? t.textDim : t.textPrimary;
  const [hover, setHover] = useState(false);
  return (
    <button
      type="button"
      title={title}
      aria-label={title}
      disabled={disabled}
      onClick={onClick}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      style={{
        width: 24,
        height: 24,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: 0,
        color: disabled ? t.textDim : colour,
        background: active ? t.bgSelected : hover && !disabled ? t.bgHover : 'transparent',
        border: `1px solid ${active ? t.border : 'transparent'}`,
        borderRadius: 5,
        cursor: disabled ? 'default' : 'pointer',
      }}
    >
      {children}
    </button>
  );
}

// ── shared shell ────────────────────────────────────────────────────────────

function DialogShell({
  title,
  subtitle,
  onClose,
  width = 560,
  children,
  footer,
}: {
  title: string;
  subtitle?: string;
  onClose: () => void;
  width?: number;
  children: React.ReactNode;
  footer?: React.ReactNode;
}) {
  const t = useLayoutTokens();
  const { t: tr } = useTranslation('chat');

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [onClose]);

  return (
    <div
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
      style={{
        position: 'fixed',
        inset: 0,
        background: 'rgba(0,0,0,0.45)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        zIndex: 2000,
      }}
    >
      <div
        style={{
          width,
          maxWidth: 'calc(100vw - 48px)',
          maxHeight: 'calc(100vh - 80px)',
          display: 'flex',
          flexDirection: 'column',
          background: t.bgSidebar,
          border: `1px solid ${t.border}`,
          borderRadius: 12,
          boxShadow: '0 16px 48px rgba(0,0,0,0.5)',
          overflow: 'hidden',
        }}
      >
        <div
          style={{
            display: 'flex',
            alignItems: 'flex-start',
            gap: 12,
            padding: '16px 18px 12px',
            borderBottom: `1px solid ${t.border}`,
          }}
        >
          <div style={{ flex: 1 }}>
            <div style={{ fontSize: 15, fontWeight: 600, color: t.textPrimary }}>{title}</div>
            {subtitle && (
              <div style={{ marginTop: 3, fontSize: 12, color: t.textMuted }}>{subtitle}</div>
            )}
          </div>
          <button
            onClick={onClose}
            title={tr('ua_close')}
            style={{
              width: 28,
              height: 28,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              background: 'transparent',
              border: 'none',
              borderRadius: 6,
              cursor: 'pointer',
              color: t.textMuted,
            }}
          >
            <X size={16} />
          </button>
        </div>

        <div style={{ padding: 18, overflowY: 'auto', flex: 1 }}>{children}</div>

        {footer && (
          <div
            style={{
              display: 'flex',
              justifyContent: 'flex-end',
              gap: 8,
              padding: '12px 18px',
              borderTop: `1px solid ${t.border}`,
            }}
          >
            {footer}
          </div>
        )}
      </div>
    </div>
  );
}

function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: React.ReactNode;
}) {
  const t = useLayoutTokens();
  return (
    <label style={{ display: 'block', marginBottom: 14 }}>
      <div style={{ fontSize: 12, fontWeight: 600, color: t.textPrimary, marginBottom: 5 }}>
        {label}
      </div>
      {children}
      {hint && <div style={{ marginTop: 4, fontSize: 11, color: t.textMuted }}>{hint}</div>}
    </label>
  );
}

function TextInput({
  ref,
  ...props
}: React.InputHTMLAttributes<HTMLInputElement> & { ref?: React.Ref<HTMLInputElement> }) {
  const t = useLayoutTokens();
  return (
    <input
      ref={ref}
      {...props}
      style={{
        width: '100%',
        height: 32,
        padding: '0 10px',
        fontSize: 13,
        color: t.textPrimary,
        background: t.bgInput,
        border: `1px solid ${t.border}`,
        borderRadius: 6,
        outline: 'none',
        boxSizing: 'border-box',
        ...props.style,
      }}
    />
  );
}

function Button({
  variant = 'secondary',
  busy,
  children,
  ...rest
}: React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: 'primary' | 'secondary' | 'danger';
  busy?: boolean;
}) {
  const t = useLayoutTokens();
  const background =
    variant === 'primary' ? t.accent : variant === 'danger' ? '#b91c1c' : 'transparent';
  const color = variant === 'secondary' ? t.textPrimary : '#ffffff';
  return (
    <button
      {...rest}
      disabled={rest.disabled || busy}
      style={{
        height: 30,
        padding: '0 14px',
        display: 'inline-flex',
        alignItems: 'center',
        gap: 6,
        fontSize: 12,
        fontWeight: 500,
        color,
        background,
        border: variant === 'secondary' ? `1px solid ${t.border}` : 'none',
        borderRadius: 6,
        cursor: rest.disabled || busy ? 'default' : 'pointer',
        opacity: rest.disabled || busy ? 0.6 : 1,
      }}
    >
      {busy && <Loader size={13} style={{ animation: 'spin 1s linear infinite' }} />}
      {children}
    </button>
  );
}

function Notice({ tone, children }: { tone: 'error' | 'ok' | 'info'; children: React.ReactNode }) {
  const t = useLayoutTokens();
  const color = tone === 'error' ? '#f87171' : tone === 'ok' ? '#4ade80' : t.textMuted;
  return (
    <div
      style={{
        fontSize: 12,
        lineHeight: 1.5,
        color,
        border: `1px solid ${tone === 'info' ? t.border : color}55`,
        borderRadius: 6,
        padding: '8px 10px',
        marginBottom: 12,
        background: tone === 'info' ? 'transparent' : `${color}14`,
      }}
    >
      {children}
    </div>
  );
}

/** The one thing a new admin most needs to know, stated where it is read. */
// The note is a dictionary entry now; kept as a key so both dialogs stay one string.

// ── account (self-service) ──────────────────────────────────────────────────

export function AccountDialog({ onClose }: { onClose: () => void }) {
  const t = useLayoutTokens();
  const { t: tr } = useTranslation('chat');
  const [me, setMe] = useState<UserSummary | null>(null);
  const [displayName, setDisplayName] = useState('');
  const [nickname, setNickname] = useState('');
  const [savingName, setSavingName] = useState(false);
  const [nameMessage, setNameMessage] = useState<{ tone: 'error' | 'ok'; text: string } | null>(null);

  const [currentPassword, setCurrentPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [repeatPassword, setRepeatPassword] = useState('');
  const [savingPassword, setSavingPassword] = useState(false);
  const [passwordMessage, setPasswordMessage] = useState<{ tone: 'error' | 'ok'; text: string } | null>(null);

  useEffect(() => {
    let cancelled = false;
    apiClient
      .getMe()
      .then((r) => {
        if (cancelled) return;
        setMe(r.data);
        setDisplayName(r.data.display_name ?? '');
        setNickname(r.data.nickname ?? '');
      })
      .catch((err: any) => {
        if (cancelled) return;
        setNameMessage({
          tone: 'error',
          text: err?.response?.data?.detail ?? tr('ua_err_load'),
        });
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const saveName = async () => {
    setSavingName(true);
    setNameMessage(null);
    try {
      const r = await apiClient.updateMe({
        display_name: displayName.trim() || null,
        // "" clears the alias; the server treats a missing field as "leave alone".
        nickname: nickname.trim(),
      });
      setMe(r.data);
      setNameMessage({ tone: 'ok', text: tr('ua_saved') });
    } catch (err: any) {
      setNameMessage({
        tone: 'error',
        text: err?.response?.data?.detail ?? tr('ua_err_save_name'),
      });
    } finally {
      setSavingName(false);
    }
  };

  const savePassword = async () => {
    if (newPassword !== repeatPassword) {
      setPasswordMessage({ tone: 'error', text: tr('ua_err_pw_mismatch') });
      return;
    }
    setSavingPassword(true);
    setPasswordMessage(null);
    try {
      await apiClient.changeMyPassword({ current_password: currentPassword, new_password: newPassword });
      setCurrentPassword('');
      setNewPassword('');
      setRepeatPassword('');
      setPasswordMessage({ tone: 'ok', text: tr('ua_pw_changed') });
    } catch (err: any) {
      setPasswordMessage({
        tone: 'error',
        text: err?.response?.data?.detail ?? tr('ua_err_pw'),
      });
    } finally {
      setSavingPassword(false);
    }
  };

  return (
    <DialogShell title={tr('ua_your_account')} subtitle={tr('ua_your_account_sub')} onClose={onClose}>
      {!me ? (
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12, color: t.textMuted }}>
          <Loader size={14} style={{ animation: 'spin 1s linear infinite' }} /> Loading…
        </div>
      ) : (
        <>
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 10,
              padding: '10px 12px',
              marginBottom: 16,
              border: `1px solid ${t.border}`,
              borderRadius: 8,
            }}
          >
            <div
              style={{
                width: 34,
                height: 34,
                borderRadius: 17,
                background: t.accent,
                color: '#fff',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                fontWeight: 600,
                fontSize: 14,
              }}
            >
              {me.username.slice(0, 1).toUpperCase()}
            </div>
            <div style={{ flex: 1 }}>
              <div style={{ fontSize: 13, fontWeight: 600, color: t.textPrimary }}>{me.username}</div>
              <div style={{ fontSize: 11, color: t.textMuted }}>
                {me.role === 'admin' ? 'Administrator' : 'Member'}
                {me.last_login_at ? ` · last sign-in ${me.last_login_at.slice(0, 16).replace('T', ' ')}` : ''}
              </div>
            </div>
            {me.role === 'admin' && <ShieldCheck size={18} color={t.accent} />}
          </div>

          {nameMessage && <Notice tone={nameMessage.tone}>{nameMessage.text}</Notice>}

          <Field label={tr('ua_display_name')} hint={tr('ua_display_name_hint')}>
            <TextInput
              value={displayName}
              placeholder={me.username}
              onChange={(e) => setDisplayName(e.target.value)}
              maxLength={128}
            />
          </Field>
          <Field
            label={tr('ua_nickname')}
            hint={tr('ua_nickname_hint')}
          >
            <TextInput
              value={nickname}
              placeholder={tr('ua_alice_ph')}
              onChange={(e) => setNickname(e.target.value)}
              maxLength={32}
              autoCapitalize="none"
              autoCorrect="off"
              spellCheck={false}
            />
          </Field>
          <div style={{ marginBottom: 20 }}>
            <Button variant="primary" busy={savingName} onClick={saveName}>
              {tr('ua_save_name')}
            </Button>
          </div>

          <div style={{ height: 1, background: t.border, margin: '4px 0 18px' }} />

          <div style={{ fontSize: 13, fontWeight: 600, color: t.textPrimary, marginBottom: 10 }}>
            {tr('ua_change_pw')}
          </div>
          {passwordMessage && <Notice tone={passwordMessage.tone}>{passwordMessage.text}</Notice>}

          <Field label={tr('ua_current_pw')}>
            <TextInput
              type="password"
              value={currentPassword}
              onChange={(e) => setCurrentPassword(e.target.value)}
              autoComplete="current-password"
            />
          </Field>
          <Field label={tr('ua_new_pw')} hint={tr('ua_new_pw_hint')}>
            <TextInput
              type="password"
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              autoComplete="new-password"
            />
          </Field>
          <Field label={tr('ua_repeat_pw')}>
            <TextInput
              type="password"
              value={repeatPassword}
              onChange={(e) => setRepeatPassword(e.target.value)}
              autoComplete="new-password"
            />
          </Field>
          <Button
            variant="primary"
            busy={savingPassword}
            disabled={!currentPassword || newPassword.length < 8}
            onClick={savePassword}
          >
            {tr('ua_change_pw')}
          </Button>

          <div style={{ marginTop: 20 }}>
            <Notice tone="info">{tr('ua_shared_note')}</Notice>
          </div>
        </>
      )}
    </DialogShell>
  );
}

// ── users (admin) ───────────────────────────────────────────────────────────

export function UsersDialog({ onClose }: { onClose: () => void }) {
  const t = useLayoutTokens();
  const { t: tr } = useTranslation('chat');
  const [users, setUsers] = useState<UserSummary[]>([]);
  const [me, setMe] = useState<UserSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<number | null>(null);

  const [newUsername, setNewUsername] = useState('');
  const [newNickname, setNewNickname] = useState('');
  const [newDisplayName, setNewDisplayName] = useState('');
  // Which row is having its nickname edited, and the draft for it.
  const [nicknameFor, setNicknameFor] = useState<number | null>(null);
  const [nicknameDraft, setNicknameDraft] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [newRole, setNewRole] = useState<'member' | 'admin'>('member');
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);

  const [resetFor, setResetFor] = useState<number | null>(null);
  const [resetPassword, setResetPassword] = useState('');
  const [resetMessage, setResetMessage] = useState<{ tone: 'error' | 'ok'; text: string } | null>(null);

  const inputRef = useRef<HTMLInputElement | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [list, mine] = await Promise.all([apiClient.listUsers(), apiClient.getMe()]);
      setUsers(list.data);
      setMe(mine.data);
    } catch (err: any) {
      setError(err?.response?.data?.detail ?? tr('ua_err_load_accounts'));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const createUser = async () => {
    setCreating(true);
    setCreateError(null);
    try {
      await apiClient.createUser({
        username: newUsername.trim(),
        password: newPassword,
        nickname: newNickname.trim() || null,
        display_name: newDisplayName.trim() || null,
        role: newRole,
      });
      setNewUsername('');
      setNewNickname('');
      setNewDisplayName('');
      setNewPassword('');
      setNewRole('member');
      await load();
      inputRef.current?.focus();
    } catch (err: any) {
      setCreateError(err?.response?.data?.detail ?? tr('ua_err_update'));
    } finally {
      setCreating(false);
    }
  };

  const patch = async (user: UserSummary, data: Parameters<typeof apiClient.updateUser>[1]) => {
    setBusyId(user.id);
    setError(null);
    try {
      await apiClient.updateUser(user.id, data);
      await load();
    } catch (err: any) {
      setError(err?.response?.data?.detail ?? tr('ua_err_update'));
    } finally {
      setBusyId(null);
    }
  };

  const submitNickname = async (user: UserSummary) => {
    setBusyId(user.id);
    setError(null);
    try {
      // "" removes the alias — that is also how a leaked nickname is taken away.
      await apiClient.updateUser(user.id, { nickname: nicknameDraft.trim() });
      setNicknameFor(null);
      setNicknameDraft('');
      await load();
    } catch (err: any) {
      setError(err?.response?.data?.detail ?? tr('ua_err_nick'));
    } finally {
      setBusyId(null);
    }
  };

  const submitReset = async (user: UserSummary) => {
    setBusyId(user.id);
    setResetMessage(null);
    try {
      await apiClient.adminSetPassword(user.id, { new_password: resetPassword });
      setResetFor(null);
      setResetPassword('');
      setResetMessage({ tone: 'ok', text: tr('ua_pw_reset_ok', { username: user.username }) });
    } catch (err: any) {
      setResetMessage({
        tone: 'error',
        text: err?.response?.data?.detail ?? tr('ua_err_reset'),
      });
    } finally {
      setBusyId(null);
    }
  };

  return (
    <DialogShell
      title={tr('up_users')}
      subtitle={tr('ua_users_sub')}
      onClose={onClose}
      width={720}
    >
      {error && <Notice tone="error">{error}</Notice>}
      {resetMessage && <Notice tone={resetMessage.tone}>{resetMessage.text}</Notice>}

      {loading ? (
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12, color: t.textMuted }}>
          <Loader size={14} style={{ animation: 'spin 1s linear infinite' }} /> {tr('ua_loading')}
        </div>
      ) : (
        <>
          <div style={{ border: `1px solid ${t.border}`, borderRadius: 8, overflow: 'hidden' }}>
            <div
              style={{
                display: 'grid',
                gridTemplateColumns: '1.4fr 1fr 80px 110px',
                gap: 8,
                padding: '8px 12px',
                fontSize: 11,
                fontWeight: 600,
                textTransform: 'uppercase',
                letterSpacing: 0.3,
                color: t.textMuted,
                borderBottom: `1px solid ${t.border}`,
              }}
            >
              <div>{tr('ua_col_account')}</div>
              <div>{tr('ua_col_role')}</div>
              <div>{tr('ua_col_status')}</div>
              <div style={{ textAlign: 'right' }}>{tr('ua_col_actions')}</div>
            </div>

            {users.map((user) => {
              const isMe = me?.id === user.id;
              const busy = busyId === user.id;
              return (
                <div
                  key={user.id}
                  style={{
                    display: 'grid',
                    gridTemplateColumns: '1.4fr 1fr 80px 110px',
                    gap: 8,
                    alignItems: 'center',
                    padding: '10px 12px',
                    borderBottom: `1px solid ${t.border}`,
                    opacity: user.is_active ? 1 : 0.6,
                  }}
                >
                  <div style={{ minWidth: 0 }}>
                    {/* Nickname first: the inline 昵称 editor changes that field, so a
                        row that showed display_name looked like the save had failed
                        (nickname=phil, display_name=Raymond → still "Raymond"). */}
                    <div style={{ fontSize: 13, color: t.textPrimary, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {user.nickname || user.display_name || user.username}
                      {isMe && (
                        <span style={{ marginLeft: 6, fontSize: 10, color: t.textMuted }}>{tr('ua_you')}</span>
                      )}
                    </div>
                    <div style={{ fontSize: 11, color: t.textMuted, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {user.username}
                      {user.display_name && user.display_name !== (user.nickname || user.username)
                        ? ` · ${user.display_name}` : ''}
                      {' · '}
                      {user.last_login_at
                        ? tr('ua_last_signin', { when: user.last_login_at.slice(0, 16).replace('T', ' ') })
                        : tr('ua_never_signed')}
                    </div>
                  </div>

                  <div>
                    <select
                      value={user.role}
                      disabled={busy || isMe}
                      onChange={(e) => patch(user, { role: e.target.value as 'admin' | 'member' })}
                      title={isMe ? tr('ua_title_role_locked') : tr('ua_title_change_role')}
                      style={{
                        height: 26,
                        fontSize: 12,
                        color: t.textPrimary,
                        background: t.bgInput,
                        border: `1px solid ${t.border}`,
                        borderRadius: 5,
                        padding: '0 6px',
                      }}
                    >
                      <option value="member">{tr('up_member')}</option>
                      <option value="admin">{tr('ua_admin')}</option>
                    </select>
                  </div>

                  <div style={{ fontSize: 11, color: user.is_active ? '#4ade80' : t.textMuted }}>
                    {user.is_active ? 'Active' : 'Disabled'}
                  </div>

                  <div style={{ display: 'flex', gap: 4, justifyContent: 'flex-end' }}>
                    {/* Three small icon buttons instead of two text buttons plus a
                        trash-can. The trash read as "delete this account" but only
                        disabled it — the shape now says what each click does. */}
                    <IconAction
                      title={tr('ua_title_reset_pw')}
                      onClick={() => {
                        setResetFor(resetFor === user.id ? null : user.id);
                        setResetPassword('');
                        setResetMessage(null);
                      }}
                      active={resetFor === user.id}
                    >
                      <KeyRound size={13} />
                    </IconAction>
                    <IconAction
                      title={user.nickname ? tr('ua_title_nick_edit') : tr('ua_title_nick_add')}
                      onClick={() => {
                        setNicknameFor(nicknameFor === user.id ? null : user.id);
                        setNicknameDraft(user.nickname ?? '');
                        setError(null);
                      }}
                      active={nicknameFor === user.id}
                    >
                      <AtSign size={13} />
                    </IconAction>
                    <IconAction
                      title={
                        isMe
                          ? tr('ua_title_self_disable')
                          : user.is_active
                            ? tr('ua_title_block')
                            : tr('ua_title_allow')
                      }
                      onClick={() => patch(user, { is_active: !user.is_active })}
                      disabled={busy || isMe}
                      tone={isMe ? 'muted' : user.is_active ? 'danger' : 'ok'}
                    >
                      {user.is_active ? <Ban size={13} /> : <CheckCircle2 size={13} />}
                    </IconAction>
                  </div>

                  {nicknameFor === user.id && (
                    <div style={{ gridColumn: '1 / -1', display: 'flex', gap: 8, marginTop: 8 }}>
                      <TextInput
                        placeholder={tr('ua_nick_ph')}
                        value={nicknameDraft}
                        onChange={(e) => setNicknameDraft(e.target.value)}
                        maxLength={32}
                        autoCapitalize="none"
                        autoCorrect="off"
                        spellCheck={false}
                      />
                      <Button variant="primary" busy={busy} onClick={() => submitNickname(user)}>
                        {tr('ua_save_nick')}
                      </Button>
                    </div>
                  )}

                  {resetFor === user.id && (
                    <div style={{ gridColumn: '1 / -1', display: 'flex', gap: 8, marginTop: 8 }}>
                      <TextInput
                        type="password"
                        placeholder={tr('ua_pw_reset_ph')}
                        value={resetPassword}
                        onChange={(e) => setResetPassword(e.target.value)}
                        autoComplete="new-password"
                      />
                      <Button
                        variant="primary"
                        busy={busy}
                        disabled={resetPassword.length < 8}
                        onClick={() => submitReset(user)}
                      >
                        {tr('ua_set_password')}
                      </Button>
                    </div>
                  )}
                </div>
              );
            })}
          </div>

          <div style={{ marginTop: 20, fontSize: 13, fontWeight: 600, color: t.textPrimary, marginBottom: 10 }}>
            {tr('ua_add_account')}
          </div>
          {createError && <Notice tone="error">{createError}</Notice>}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
            <Field label={tr('ua_username')} hint={tr('ua_username_hint')}>
              <TextInput
                ref={inputRef}
                value={newUsername}
                onChange={(e) => setNewUsername(e.target.value)}
                placeholder={tr('ua_alice_ph')}
                autoComplete="off"
              />
            </Field>
            <Field label={tr('ua_nickname')} hint={tr('ua_nickname_optional_hint')}>
              <TextInput
                value={newNickname}
                onChange={(e) => setNewNickname(e.target.value)}
                placeholder={tr('ua_alice_ph')}
                maxLength={32}
                autoCapitalize="none"
                autoCorrect="off"
                spellCheck={false}
              />
            </Field>
            <Field label={tr('ua_display_name')} hint={tr('ua_display_optional')}>
              <TextInput
                value={newDisplayName}
                onChange={(e) => setNewDisplayName(e.target.value)}
                placeholder={tr('ua_display_ph')}
                maxLength={128}
              />
            </Field>
            <Field label={tr('ua_initial_pw')} hint={tr('ua_initial_pw_hint')}>
              <TextInput
                type="password"
                value={newPassword}
                onChange={(e) => setNewPassword(e.target.value)}
                autoComplete="new-password"
              />
            </Field>
            <Field label={tr('ua_role')}>
              <select
                value={newRole}
                onChange={(e) => setNewRole(e.target.value as 'member' | 'admin')}
                style={{
                  width: '100%',
                  height: 32,
                  fontSize: 13,
                  color: t.textPrimary,
                  background: t.bgInput,
                  border: `1px solid ${t.border}`,
                  borderRadius: 6,
                  padding: '0 8px',
                  boxSizing: 'border-box',
                }}
              >
                <option value="member">{tr('ua_role_member')}</option>
                <option value="admin">{tr('ua_role_admin')}</option>
              </select>
            </Field>
          </div>
          <Button
            variant="primary"
            busy={creating}
            disabled={newUsername.trim().length < 2 || newPassword.length < 8}
            onClick={createUser}
          >
            <UserRound size={13} /> {tr('ua_create_account')}
          </Button>

          <div style={{ marginTop: 18 }}>
            <Notice tone="info">{tr('ua_shared_note')}</Notice>
          </div>
        </>
      )}
    </DialogShell>
  );
}
