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
import { useLayoutTokens } from './tokens';
import apiClient from '../../lib/api-client';
import type { UserSummary } from '../../lib/api/users';
import { Check, Loader, ShieldCheck, Trash2, UserRound, X } from 'lucide-react';

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
            title="Close"
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
const SHARED_DATA_NOTE =
  'Accounts are separate. Everything else in this install — projects, agents, chats, tools and knowledge — is shared with every account.';

// ── account (self-service) ──────────────────────────────────────────────────

export function AccountDialog({ onClose }: { onClose: () => void }) {
  const t = useLayoutTokens();
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
          text: err?.response?.data?.detail ?? 'Could not load your account.',
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
      setNameMessage({ tone: 'ok', text: 'Saved.' });
    } catch (err: any) {
      setNameMessage({
        tone: 'error',
        text: err?.response?.data?.detail ?? 'Could not save your name.',
      });
    } finally {
      setSavingName(false);
    }
  };

  const savePassword = async () => {
    if (newPassword !== repeatPassword) {
      setPasswordMessage({ tone: 'error', text: 'The two new passwords do not match.' });
      return;
    }
    setSavingPassword(true);
    setPasswordMessage(null);
    try {
      await apiClient.changeMyPassword({ current_password: currentPassword, new_password: newPassword });
      setCurrentPassword('');
      setNewPassword('');
      setRepeatPassword('');
      setPasswordMessage({ tone: 'ok', text: 'Password changed.' });
    } catch (err: any) {
      setPasswordMessage({
        tone: 'error',
        text: err?.response?.data?.detail ?? 'Could not change your password.',
      });
    } finally {
      setSavingPassword(false);
    }
  };

  return (
    <DialogShell title="Your account" subtitle="The name and password you sign in with." onClose={onClose}>
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

          <Field label="Display name" hint="Shown next to your work. Your username stays as it is.">
            <TextInput
              value={displayName}
              placeholder={me.username}
              onChange={(e) => setDisplayName(e.target.value)}
              maxLength={128}
            />
          </Field>
          <Field
            label="Nickname"
            hint="Sign in with this instead of your username — shorter is easier. Letters, digits, dot, dash, underscore."
          >
            <TextInput
              value={nickname}
              placeholder="e.g. alice"
              onChange={(e) => setNickname(e.target.value)}
              maxLength={32}
              autoCapitalize="none"
              autoCorrect="off"
              spellCheck={false}
            />
          </Field>
          <div style={{ marginBottom: 20 }}>
            <Button variant="primary" busy={savingName} onClick={saveName}>
              Save name
            </Button>
          </div>

          <div style={{ height: 1, background: t.border, margin: '4px 0 18px' }} />

          <div style={{ fontSize: 13, fontWeight: 600, color: t.textPrimary, marginBottom: 10 }}>
            Change password
          </div>
          {passwordMessage && <Notice tone={passwordMessage.tone}>{passwordMessage.text}</Notice>}

          <Field label="Current password">
            <TextInput
              type="password"
              value={currentPassword}
              onChange={(e) => setCurrentPassword(e.target.value)}
              autoComplete="current-password"
            />
          </Field>
          <Field label="New password" hint="At least 8 characters.">
            <TextInput
              type="password"
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              autoComplete="new-password"
            />
          </Field>
          <Field label="Repeat new password">
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
            Change password
          </Button>

          <div style={{ marginTop: 20 }}>
            <Notice tone="info">{SHARED_DATA_NOTE}</Notice>
          </div>
        </>
      )}
    </DialogShell>
  );
}

// ── users (admin) ───────────────────────────────────────────────────────────

export function UsersDialog({ onClose }: { onClose: () => void }) {
  const t = useLayoutTokens();
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
      setError(err?.response?.data?.detail ?? 'Could not load accounts.');
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
      setCreateError(err?.response?.data?.detail ?? 'Could not create the account.');
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
      setError(err?.response?.data?.detail ?? 'Could not update the account.');
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
      setError(err?.response?.data?.detail ?? 'Could not set that nickname.');
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
      setResetMessage({ tone: 'ok', text: `Password reset for ${user.username}. Tell them the new one.` });
    } catch (err: any) {
      setResetMessage({
        tone: 'error',
        text: err?.response?.data?.detail ?? 'Could not reset the password.',
      });
    } finally {
      setBusyId(null);
    }
  };

  return (
    <DialogShell
      title="Users"
      subtitle="Who may sign in to this install. Administrators can also manage accounts."
      onClose={onClose}
      width={720}
    >
      {error && <Notice tone="error">{error}</Notice>}
      {resetMessage && <Notice tone={resetMessage.tone}>{resetMessage.text}</Notice>}

      {loading ? (
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12, color: t.textMuted }}>
          <Loader size={14} style={{ animation: 'spin 1s linear infinite' }} /> Loading accounts…
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
              <div>Account</div>
              <div>Role</div>
              <div>Status</div>
              <div style={{ textAlign: 'right' }}>Actions</div>
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
                  <div>
                    <div style={{ fontSize: 13, color: t.textPrimary }}>
                      {user.display_name || user.username}
                      {isMe && (
                        <span style={{ marginLeft: 6, fontSize: 10, color: t.textMuted }}>(you)</span>
                      )}
                    </div>
                    <div style={{ fontSize: 11, color: t.textMuted }}>
                      {user.username}
                      {user.nickname ? ` · signs in as “${user.nickname}”` : ''}
                      {user.last_login_at
                        ? ` · last sign-in ${user.last_login_at.slice(0, 16).replace('T', ' ')}`
                        : ' · never signed in'}
                    </div>
                  </div>

                  <div>
                    <select
                      value={user.role}
                      disabled={busy || isMe}
                      onChange={(e) => patch(user, { role: e.target.value as 'admin' | 'member' })}
                      title={isMe ? 'You cannot change your own role' : 'Change role'}
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
                      <option value="member">Member</option>
                      <option value="admin">Admin</option>
                    </select>
                  </div>

                  <div style={{ fontSize: 11, color: user.is_active ? '#4ade80' : t.textMuted }}>
                    {user.is_active ? 'Active' : 'Disabled'}
                  </div>

                  <div style={{ display: 'flex', gap: 6, justifyContent: 'flex-end' }}>
                    <button
                      onClick={() => {
                        setResetFor(resetFor === user.id ? null : user.id);
                        setResetPassword('');
                        setResetMessage(null);
                      }}
                      title="Set a new password for this account"
                      style={{
                        height: 24,
                        padding: '0 8px',
                        fontSize: 11,
                        color: t.textPrimary,
                        background: 'transparent',
                        border: `1px solid ${t.border}`,
                        borderRadius: 5,
                        cursor: 'pointer',
                      }}
                    >
                      Reset
                    </button>
                    <button
                      onClick={() => {
                        setNicknameFor(nicknameFor === user.id ? null : user.id);
                        setNicknameDraft(user.nickname ?? '');
                        setError(null);
                      }}
                      title={
                        user.nickname
                          ? 'Change or remove the nickname they can sign in with'
                          : 'Give this account a nickname they can sign in with'
                      }
                      style={{
                        height: 24,
                        padding: '0 8px',
                        fontSize: 11,
                        color: t.textPrimary,
                        background: 'transparent',
                        border: `1px solid ${t.border}`,
                        borderRadius: 5,
                        cursor: 'pointer',
                      }}
                    >
                      Nick
                    </button>
                    <button
                      onClick={() => patch(user, { is_active: !user.is_active })}
                      disabled={busy || isMe}
                      title={
                        isMe
                          ? 'You cannot disable your own account'
                          : user.is_active
                            ? 'Block sign-in for this account'
                            : 'Allow this account to sign in again'
                      }
                      style={{
                        width: 24,
                        height: 24,
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        color: isMe ? t.textDim : user.is_active ? '#f87171' : '#4ade80',
                        background: 'transparent',
                        border: `1px solid ${t.border}`,
                        borderRadius: 5,
                        cursor: busy || isMe ? 'default' : 'pointer',
                      }}
                    >
                      {user.is_active ? <Trash2 size={12} /> : <Check size={12} />}
                    </button>
                  </div>

                  {nicknameFor === user.id && (
                    <div style={{ gridColumn: '1 / -1', display: 'flex', gap: 8, marginTop: 8 }}>
                      <TextInput
                        placeholder="Nickname for sign-in (empty = remove it)"
                        value={nicknameDraft}
                        onChange={(e) => setNicknameDraft(e.target.value)}
                        maxLength={32}
                        autoCapitalize="none"
                        autoCorrect="off"
                        spellCheck={false}
                      />
                      <Button variant="primary" busy={busy} onClick={() => submitNickname(user)}>
                        Save nickname
                      </Button>
                    </div>
                  )}

                  {resetFor === user.id && (
                    <div style={{ gridColumn: '1 / -1', display: 'flex', gap: 8, marginTop: 8 }}>
                      <TextInput
                        type="password"
                        placeholder="New password (min 8 characters)"
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
                        Set password
                      </Button>
                    </div>
                  )}
                </div>
              );
            })}
          </div>

          <div style={{ marginTop: 20, fontSize: 13, fontWeight: 600, color: t.textPrimary, marginBottom: 10 }}>
            Add an account
          </div>
          {createError && <Notice tone="error">{createError}</Notice>}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
            <Field label="Username" hint="2–64 characters: letters, digits, . _ -">
              <TextInput
                ref={inputRef}
                value={newUsername}
                onChange={(e) => setNewUsername(e.target.value)}
                placeholder="e.g. alice"
                autoComplete="off"
              />
            </Field>
            <Field label="Nickname" hint="Optional. They can sign in with this too.">
              <TextInput
                value={newNickname}
                onChange={(e) => setNewNickname(e.target.value)}
                placeholder="e.g. alice"
                maxLength={32}
                autoCapitalize="none"
                autoCorrect="off"
                spellCheck={false}
              />
            </Field>
            <Field label="Display name" hint="Optional">
              <TextInput
                value={newDisplayName}
                onChange={(e) => setNewDisplayName(e.target.value)}
                placeholder="Alice Chan"
                maxLength={128}
              />
            </Field>
            <Field label="Initial password" hint="At least 8 characters. There is no email reset — tell them the password.">
              <TextInput
                type="password"
                value={newPassword}
                onChange={(e) => setNewPassword(e.target.value)}
                autoComplete="new-password"
              />
            </Field>
            <Field label="Role">
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
                <option value="member">Member — manages their own account only</option>
                <option value="admin">Admin — also manages accounts</option>
              </select>
            </Field>
          </div>
          <Button
            variant="primary"
            busy={creating}
            disabled={newUsername.trim().length < 2 || newPassword.length < 8}
            onClick={createUser}
          >
            <UserRound size={13} /> Create account
          </Button>

          <div style={{ marginTop: 18 }}>
            <Notice tone="info">{SHARED_DATA_NOTE}</Notice>
          </div>
        </>
      )}
    </DialogShell>
  );
}
