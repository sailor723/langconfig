/**
 * Copyright (c) 2025 Cade Russell (Ghost Peony)
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */

/**
 * SettingsView — DSH-style settings page (mirrors the DeepSeek Harness GUI).
 *
 * A slim left nav + clean "label → control" rows. No card galleries.
 * Sections:
 *   General          — language, theme, app behavior toggles
 *   Models           — default/fallback model dropdowns + provider list with
 *                      Edit dialogs (API key, base URL, model rows) + Add provider
 *   Search Providers — simple provider list with key edit / test / delete
 *   Workspace        — workspace path + permission toggles
 *   Storage          — storage mode
 *   About            — version info + re-run setup
 */
import { useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { themes, useTheme, type ThemeName } from '../lib/themes';
import apiClient from '../lib/api-client';

type SectionId = 'general' | 'models' | 'search' | 'workspace' | 'storage' | 'about';

const SECTIONS: { id: SectionId; label: string; icon: string }[] = [
  { id: 'general', label: 'General', icon: 'tune' },
  { id: 'models', label: 'Models', icon: 'smart_toy' },
  { id: 'search', label: 'Search Providers', icon: 'travel_explore' },
  { id: 'workspace', label: 'Workspace', icon: 'folder_open' },
  { id: 'storage', label: 'Storage', icon: 'storage' },
  { id: 'about', label: 'About', icon: 'info' },
];

// Provider name → APIKeySet field (matches backend API_PROVIDER_KEY_FIELDS).
const PROVIDER_FIELD: Record<string, string> = {
  openai: 'openai_api_key', anthropic: 'anthropic_api_key', google: 'google_api_key',
  cohere: 'cohere_api_key', replicate: 'replicate_api_key', deepseek: 'deepseek_api_key',
  glm: 'glm_api_key', minimax: 'minimax_api_key', qwen: 'qwen_api_key', kimi: 'kimi_api_key',
  agnes: 'agnes_api_key', tavily: 'tavily_api_key', serper: 'serper_api_key',
};

const PROVIDER_BASE_FIELD: Record<string, string> = {
  openai: 'openai_base_url', anthropic: 'anthropic_base_url', google: 'google_base_url',
  cohere: 'cohere_base_url', replicate: 'replicate_base_url', deepseek: 'deepseek_api_base',
  glm: 'glm_api_base', minimax: 'minimax_api_base', qwen: 'qwen_api_base', kimi: 'kimi_api_base',
  agnes: 'agnes_base_url',
};

const PROVIDER_LABEL: Record<string, string> = {
  openai: 'OpenAI', anthropic: 'Anthropic', google: 'Google', deepseek: 'DeepSeek',
  glm: 'GLM', minimax: 'MiniMax', qwen: 'Qwen', kimi: 'Kimi', cohere: 'Cohere',
  replicate: 'Replicate', agnes: 'Agnes', tavily: 'Tavily', serper: 'Serper',
};

const label = (p: string) => PROVIDER_LABEL[p] || (p.charAt(0).toUpperCase() + p.slice(1));

// ── Small presentational helpers ───────────────────────────────────

function SectionTitle({ title, desc }: { title: string; desc?: string }) {
  return (
    <div style={{ marginBottom: 20 }}>
      <h2 style={{ fontSize: 17, fontWeight: 650, margin: 0, color: 'var(--color-text-primary)' }}>{title}</h2>
      {desc && <p style={{ fontSize: 12.5, color: 'var(--color-text-muted)', margin: '4px 0 0 0', lineHeight: 1.5 }}>{desc}</p>}
    </div>
  );
}

function Row({ label: rowLabel, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 16, padding: '10px 0', borderBottom: '1px solid var(--color-border)' }}>
      <div style={{ minWidth: 0 }}>
        <div style={{ fontSize: 13, fontWeight: 500, color: 'var(--color-text-primary)' }}>{rowLabel}</div>
        {hint && <div style={{ fontSize: 11.5, color: 'var(--color-text-muted)', marginTop: 2 }}>{hint}</div>}
      </div>
      <div style={{ flexShrink: 0 }}>{children}</div>
    </div>
  );
}

function Toggle({ checked, onChange }: { checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <button
      role="switch"
      aria-checked={checked}
      onClick={() => onChange(!checked)}
      style={{
        width: 36, height: 20, borderRadius: 999, border: 'none', cursor: 'pointer', position: 'relative',
        background: checked ? 'var(--color-primary)' : 'var(--color-border-dark)', transition: 'background 0.15s', flexShrink: 0,
      }}
    >
      <span style={{
        position: 'absolute', top: 2, left: checked ? 18 : 2, width: 16, height: 16, borderRadius: '50%',
        background: '#fff', transition: 'left 0.15s',
      }} />
    </button>
  );
}

function Select({ value, onChange, options, width = 220 }: {
  value: string; onChange: (v: string) => void; options: { value: string; label: string }[]; width?: number;
}) {
  return (
    <select
      value={value}
      onChange={e => onChange(e.target.value)}
      style={{
        width, padding: '6px 10px', borderRadius: 6, fontSize: 13,
        border: '1px solid var(--color-border-dark)', background: 'var(--color-input-background, #fff)',
        color: 'var(--color-text-primary)', outline: 'none', cursor: 'pointer',
      }}
    >
      {options.map(o => <option key={'key' in o ? (o as any).key : o.value} value={o.value}>{o.label}</option>)}
    </select>
  );
}

function TextInput({ value, onChange, placeholder, mono = false, width = 280 }: {
  value: string; onChange: (v: string) => void; placeholder?: string; mono?: boolean; width?: number;
}) {
  return (
    <input
      type="text"
      value={value}
      onChange={e => onChange(e.target.value)}
      placeholder={placeholder}
      style={{
        width, padding: '6px 10px', borderRadius: 6, fontSize: 13,
        border: '1px solid var(--color-border-dark)', background: 'var(--color-input-background, #fff)',
        color: 'var(--color-text-primary)', outline: 'none',
        fontFamily: mono ? 'ui-monospace, SFMono-Regular, Menlo, monospace' : 'inherit',
      }}
    />
  );
}

function Btn({ children, onClick, variant = 'ghost', disabled }: {
  children: React.ReactNode; onClick?: () => void; variant?: 'primary' | 'ghost' | 'danger'; disabled?: boolean;
}) {
  const base: React.CSSProperties = {
    padding: '5px 12px', borderRadius: 6, fontSize: 12.5, fontWeight: 500, cursor: disabled ? 'not-allowed' : 'pointer',
    border: '1px solid var(--color-border-dark)', opacity: disabled ? 0.5 : 1, whiteSpace: 'nowrap',
  };
  if (variant === 'primary') {
    Object.assign(base, { background: 'var(--color-primary)', borderColor: 'var(--color-primary)', color: '#fff' });
  } else if (variant === 'danger') {
    Object.assign(base, { color: '#e5484d', borderColor: 'var(--color-border-dark)', background: 'transparent' });
  } else {
    Object.assign(base, { background: 'transparent', color: 'var(--color-text-primary)' });
  }
  return <button style={base} onClick={onClick} disabled={disabled}>{children}</button>;
}

// ── Settings page ──────────────────────────────────────────────────

export default function SettingsView() {
  const { i18n } = useTranslation();
  const { theme: activeTheme, setTheme } = useTheme();
  const [section, setSection] = useState<SectionId>('general');

  return (
    <div style={{ display: 'flex', height: '100%', width: '100%', overflow: 'hidden', background: 'var(--color-background-light, #f7f7f7)' }} className="dark:bg-background-dark">
      {/* ── Left nav ── */}
      <aside style={{ width: 210, flexShrink: 0, borderRight: '1px solid var(--color-border)', background: 'var(--color-panel-dark, #1e1e1e)', display: 'flex', flexDirection: 'column' }}>
        <div style={{ padding: '18px 16px 12px', fontSize: 15, fontWeight: 700, color: 'var(--color-text-primary)', display: 'flex', alignItems: 'center', gap: 8 }}>
          <span className="material-symbols-outlined" style={{ fontSize: 18 }}>settings</span>
          Settings
        </div>
        <nav style={{ flex: 1, overflowY: 'auto', padding: '4px 8px' }}>
          {SECTIONS.map(s => {
            const active = section === s.id;
            return (
              <button
                key={s.id}
                onClick={() => setSection(s.id)}
                style={{
                  display: 'flex', alignItems: 'center', gap: 10, width: '100%', padding: '8px 10px', marginBottom: 2,
                  borderRadius: 6, border: 'none', cursor: 'pointer', textAlign: 'left', fontSize: 13,
                  background: active ? 'var(--color-primary, #007acc)22' : 'transparent',
                  color: active ? 'var(--color-primary, #007acc)' : 'var(--color-text-muted)',
                  fontWeight: active ? 600 : 400,
                }}
                onMouseEnter={e => { if (!active) e.currentTarget.style.background = 'rgba(255,255,255,0.04)'; }}
                onMouseLeave={e => { if (!active) e.currentTarget.style.background = 'transparent'; }}
              >
                <span className="material-symbols-outlined" style={{ fontSize: 16 }}>{s.icon}</span>
                {s.label}
              </button>
            );
          })}
        </nav>
        <div style={{ padding: '10px 16px', borderTop: '1px solid var(--color-border)', fontSize: 11, color: 'var(--color-text-muted)', lineHeight: 1.5 }}>
          Configuration lives in <code style={{ fontFamily: 'monospace' }}>.env</code> + Settings (PostgreSQL).
        </div>
      </aside>

      {/* ── Content ── */}
      <div style={{ flex: 1, overflowY: 'auto', minWidth: 0 }}>
        <div style={{ maxWidth: 720, margin: '0 auto', padding: '32px 36px 64px' }}>
          {section === 'general' && <GeneralSection i18n={i18n} activeTheme={activeTheme.name} setTheme={setTheme} />}
          {section === 'models' && <ModelsSection />}
          {section === 'search' && <SearchSection />}
          {section === 'workspace' && <WorkspaceSection />}
          {section === 'storage' && <StorageSection />}
          {section === 'about' && <AboutSection />}
        </div>
      </div>
    </div>
  );
}

// ── General ────────────────────────────────────────────────────────

function GeneralSection({ i18n, activeTheme, setTheme }: {
  i18n: any; activeTheme: string; setTheme: (t: ThemeName) => void;
}) {
  const [gen, setGen] = useState<any>(null);
  const [language, setLanguage] = useState(i18n.language);

  const load = useCallback(async () => {
    try {
      const res = await apiClient.getGeneralSettings();
      setGen(res.data || {});
    } catch { /* backend may not have general settings yet */ }
  }, []);

  useEffect(() => { load(); }, [load]);

  const update = async (patch: Record<string, any>) => {
    setGen((prev: any) => ({ ...(prev || {}), ...patch }));
    try { await apiClient.updateGeneralSettings(patch as any); } catch { /* noop */ }
  };

  const changeLanguage = async (lang: string) => {
    setLanguage(lang);
    i18n.changeLanguage(lang);
    await update({ language: lang });
  };

  const changeTheme = async (name: ThemeName) => {
    setTheme(name);
    await update({ theme: name });
  };

  return (
    <>
      <SectionTitle title="General" desc="Applies to the whole application." />
      <div style={{ background: 'var(--color-panel-dark, #fff)', border: '1px solid var(--color-border)', borderRadius: 10, padding: '4px 20px', marginBottom: 16 }}>
        <Row label="Language" hint="Interface language">
          <Select value={language} onChange={changeLanguage} options={[{ value: 'en', label: 'English' }, { value: 'zh', label: '中文' }]} />
        </Row>
        <Row label="Appearance" hint="Color theme">
          <Select
            value={activeTheme}
            onChange={v => changeTheme(v as ThemeName)}
            options={Object.values(themes).map(th => ({ value: th.name, label: th.displayName }))}
          />
        </Row>
        <Row label="Auto-save" hint="Automatically save workflows at regular intervals">
          <Toggle checked={gen?.auto_save ?? true} onChange={v => update({ auto_save: v })} />
        </Row>
        <Row label="Confirm before deleting" hint="Show a confirmation dialog before deleting workflows or agents">
          <Toggle checked={gen?.confirm_before_delete ?? true} onChange={v => update({ confirm_before_delete: v })} />
        </Row>
        <Row label="Show notifications" hint="Display system notifications for workflow completion and errors">
          <Toggle checked={gen?.show_notifications ?? true} onChange={v => update({ show_notifications: v })} />
        </Row>
        <Row label="Anonymous usage statistics" hint="Help improve LangConfig by sharing anonymous usage data">
          <Toggle checked={gen?.telemetry ?? false} onChange={v => update({ telemetry: v })} />
        </Row>
      </div>
    </>
  );
}

// ── Models ─────────────────────────────────────────────────────────

interface ModelInfo { model_id: string; display_name?: string; provider: string; capabilities?: Record<string, any>; }

function ModelsSection() {
  const [keys, setKeys] = useState<{ provider: string; is_set: boolean; masked_key?: string | null; kind?: string }[]>([]);
  const [models, setModels] = useState<{ cloud: ModelInfo[]; local: ModelInfo[] }>({ cloud: [], local: [] });
  const [defaults, setDefaults] = useState<any>({ primary_model: '', fallback_models: [], temperature: 0, max_tokens: 0 });
  const [editing, setEditing] = useState<string | null>(null);   // provider being edited
  const [adding, setAdding] = useState(false);                    // Add provider dialog
  const [keyInput, setKeyInput] = useState('');
  const [baseUrl, setBaseUrl] = useState('');
  const [newProviderName, setNewProviderName] = useState('');
  const [testing, setTesting] = useState(false);
  const [testMsg, setTestMsg] = useState<{ ok: boolean; msg: string } | null>(null);

  const load = useCallback(async () => {
    try {
      const [keysRes, modelsRes, defaultsRes] = await Promise.all([
        apiClient.getApiKeys(),
        apiClient.listAvailableModels(),
        apiClient.getModelDefaults(),
      ]);
      setKeys(keysRes.data || []);
      setModels({
        cloud: modelsRes.data?.cloud_models || [],
        local: modelsRes.data?.local_models || [],
      });
      setDefaults(defaultsRes.data || {});
    } catch (err) {
      console.error('Failed to load models settings:', err);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const allModels: { value: string; label: string; key: string }[] = [
    ...models.cloud.map(m => ({ value: m.model_id, label: `${label(m.provider)} — ${m.display_name || m.model_id}`, key: `cloud-${m.provider}-${m.model_id}` })),
    ...models.local.map(m => ({ value: m.model_id, label: `Local — ${m.display_name || m.model_id}`, key: `local-${m.model_id}` })),
  ];

  const keySet = (provider: string) => keys.find(k => k.provider === provider)?.is_set ?? false;

  const saveKey = async (provider: string, key: string, base: string) => {
    const field = PROVIDER_FIELD[provider];
    const baseField = PROVIDER_BASE_FIELD[provider];
    if (!field) return;
    const payload: Record<string, string> = { [field]: key.trim() };
    if (base.trim() && baseField) payload[baseField] = base.trim();
    await apiClient.setApiKeys(payload as any);
  };

  const handleEditSave = async (provider: string) => {
    try {
      await saveKey(provider, keyInput, baseUrl);
      setEditing(null);
      setKeyInput(''); setBaseUrl(''); setTestMsg(null);
      await load();
    } catch (err: any) {
      setTestMsg({ ok: false, msg: err?.response?.data?.detail || 'Failed to save' });
    }
  };

  const handleTest = async (provider: string) => {
    setTesting(true); setTestMsg(null);
    try {
      const res = await apiClient.testApiKey(provider, keyInput || undefined);
      setTestMsg({ ok: !!res.data?.success, msg: res.data?.message || (res.data?.success ? '✓ Connected' : '✗ Failed') });
    } catch {
      setTestMsg({ ok: false, msg: '✗ Connection failed' });
    } finally { setTesting(false); }
  };

  const handleAddProvider = async () => {
    const name = newProviderName.trim().toLowerCase();
    if (!name) return;
    const field = PROVIDER_FIELD[name];
    if (!field) { setTestMsg({ ok: false, msg: `Unknown provider '${name}'. Use one of: ${Object.keys(PROVIDER_FIELD).join(', ')}` }); return; }
    try {
      await saveKey(name, keyInput, baseUrl);
      setAdding(false); setNewProviderName(''); setKeyInput(''); setBaseUrl(''); setTestMsg(null);
      await load();
    } catch (err: any) {
      setTestMsg({ ok: false, msg: err?.response?.data?.detail || 'Failed' });
    }
  };

  return (
    <>
      <SectionTitle title="Models" desc="Default model and API keys for the model providers." />

      {/* Default model */}
      <div style={{ background: 'var(--color-panel-dark, #fff)', border: '1px solid var(--color-border)', borderRadius: 10, padding: '4px 20px', marginBottom: 16 }}>
        <Row label="Default model" hint="Used for agents and chat unless overridden">
          <Select
            value={defaults.primary_model || ''}
            onChange={async v => { setDefaults((p: any) => ({ ...p, primary_model: v })); try { await apiClient.updateModelDefaultsSettings({ primary_model: v }); } catch {} }}
            options={[{ value: '', label: '— not set —' }, ...allModels]}
            width={320}
          />
        </Row>
        <Row label="Fallback model" hint="Used when the default model fails">
          <Select
            value={(defaults.fallback_models?.[0]) || ''}
            onChange={async v => { setDefaults((p: any) => ({ ...p, fallback_models: [v] })); try { await apiClient.updateModelDefaultsSettings({ fallback_models: [v] }); } catch {} }}
            options={[{ value: '', label: '— none —' }, ...allModels]}
            width={320}
          />
        </Row>
        <Row label="Default temperature" hint="Sampling temperature (0 = deterministic)">
          <input
            type="number" step="0.1" min="0" max="2"
            value={defaults.temperature ?? 0}
            onChange={async e => {
              const v = parseFloat(e.target.value) || 0;
              setDefaults((p: any) => ({ ...p, temperature: v }));
              try { await apiClient.updateModelDefaultsSettings({ temperature: v }); } catch {}
            }}
            style={{ width: 100, padding: '6px 10px', borderRadius: 6, fontSize: 13, border: '1px solid var(--color-border-dark)', background: 'var(--color-input-background, #fff)', color: 'var(--color-text-primary)', outline: 'none' }}
          />
        </Row>
        <Row label="Max tokens" hint="Maximum output length per call">
          <input
            type="number" step="1000" min="0"
            value={defaults.max_tokens ?? 0}
            onChange={async e => {
              const v = parseInt(e.target.value, 10) || 0;
              setDefaults((p: any) => ({ ...p, max_tokens: v }));
              try { await apiClient.updateModelDefaultsSettings({ max_tokens: v }); } catch {}
            }}
            style={{ width: 140, padding: '6px 10px', borderRadius: 6, fontSize: 13, border: '1px solid var(--color-border-dark)', background: 'var(--color-input-background, #fff)', color: 'var(--color-text-primary)', outline: 'none' }}
          />
        </Row>
      </div>

      {/* Providers */}
      <SectionTitle title="API keys" desc="Enter your API keys to use models from the following providers." />
      <div style={{ background: 'var(--color-panel-dark, #fff)', border: '1px solid var(--color-border)', borderRadius: 10, padding: '6px 0', marginBottom: 16 }}>
        {keys.length === 0 && <div style={{ padding: '14px 20px', fontSize: 12.5, color: 'var(--color-text-muted)' }}>Loading providers…</div>}
        {keys.filter(k => k.kind !== 'search').map(k => (
          <div key={k.provider} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, padding: '9px 20px', borderBottom: '1px solid var(--color-border)' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, minWidth: 0 }}>
              <span style={{ fontSize: 13, fontWeight: 500, color: 'var(--color-text-primary)' }}>{label(k.provider)}</span>
              {k.is_set
                ? <span style={{ fontSize: 11, color: '#22c55e' }}>✓ {k.masked_key || 'Key set'}</span>
                : <span style={{ fontSize: 11, color: 'var(--color-text-muted)' }}>No key</span>}
            </div>
            <Btn onClick={() => { setEditing(k.provider); setKeyInput(''); setBaseUrl(''); setTestMsg(null); }}>Edit</Btn>
          </div>
        ))}
        <div style={{ padding: '10px 20px', display: 'flex', gap: 8 }}>
          <Btn onClick={() => { setAdding(true); setKeyInput(''); setBaseUrl(''); setNewProviderName(''); setTestMsg(null); }}>Add provider</Btn>
        </div>
      </div>

      {/* Edit dialog */}
      {editing && (
        <Dialog title={label(editing)} onClose={() => setEditing(null)}>
          <Field label="Provider">
            <div style={{ fontSize: 13, color: 'var(--color-text-muted)' }}>{editing}</div>
          </Field>
          <Field label="API key">
            <TextInput value={keyInput} onChange={setKeyInput} placeholder="sk-… (leave empty to keep current)" mono />
          </Field>
          <Field label="Customized settings">
            <TextInput value={baseUrl} onChange={setBaseUrl} placeholder="https://api.example.com (optional)" mono />
          </Field>
          <Field label="Models">
            <div style={{ maxHeight: 120, overflowY: 'auto', border: '1px solid var(--color-border)', borderRadius: 6, fontSize: 12, color: 'var(--color-text-muted)' }}>
              {models.cloud.filter(m => m.provider.toLowerCase() === editing).map(m => (
                <div key={m.model_id} style={{ padding: '5px 10px', borderBottom: '1px solid var(--color-border)' }}>
                  <span style={{ color: 'var(--color-text-primary)' }}>{m.display_name || m.model_id}</span>
                  <span style={{ fontFamily: 'monospace', marginLeft: 8, fontSize: 11 }}>{m.model_id}</span>
                </div>
              ))}
              {models.cloud.filter(m => m.provider.toLowerCase() === editing).length === 0 && (
                <div style={{ padding: '8px 10px' }}>No models registered for this provider.</div>
              )}
            </div>
          </Field>
          {testMsg && <div style={{ fontSize: 12, color: testMsg.ok ? '#22c55e' : '#ef4444' }}>{testMsg.msg}</div>}
          <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', marginTop: 4 }}>
            <Btn onClick={() => handleTest(editing)} disabled={testing}>{testing ? 'Testing…' : 'Test'}</Btn>
            <Btn onClick={() => setEditing(null)}>Cancel</Btn>
            <Btn variant="primary" onClick={() => handleEditSave(editing)}>Apply</Btn>
          </div>
        </Dialog>
      )}

      {/* Add-provider dialog */}
      {adding && (
        <Dialog title="Add provider" onClose={() => setAdding(false)}>
          <Field label="Provider name">
            <TextInput value={newProviderName} onChange={setNewProviderName} placeholder="e.g. openai, deepseek, anthropic" />
          </Field>
          <Field label="API key">
            <TextInput value={keyInput} onChange={setKeyInput} placeholder="sk-…" mono />
          </Field>
          <Field label="Base URL (optional)">
            <TextInput value={baseUrl} onChange={setBaseUrl} placeholder="https://api.example.com" mono />
          </Field>
          {testMsg && <div style={{ fontSize: 12, color: testMsg.ok ? '#22c55e' : '#ef4444' }}>{testMsg.msg}</div>}
          <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', marginTop: 4 }}>
            <Btn onClick={() => setAdding(false)}>Cancel</Btn>
            <Btn variant="primary" onClick={handleAddProvider}>Save</Btn>
          </div>
        </Dialog>
      )}
    </>
  );
}

function Dialog({ title, children, onClose }: { title: string; children: React.ReactNode; onClose: () => void }) {
  return (
    <>
      <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.45)', zIndex: 90 }} onClick={onClose} />
      <div style={{
        position: 'fixed', top: '50%', left: '50%', transform: 'translate(-50%, -50%)', zIndex: 91,
        width: 460, maxWidth: 'calc(100vw - 32px)', maxHeight: '80vh', overflowY: 'auto',
        background: 'var(--color-panel-dark, #fff)', border: '1px solid var(--color-border-dark)', borderRadius: 10,
        boxShadow: '0 16px 48px rgba(0,0,0,0.35)', padding: '20px 22px',
      }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 14 }}>
          <h3 style={{ fontSize: 15, fontWeight: 650, margin: 0, color: 'var(--color-text-primary)' }}>{title}</h3>
          <button onClick={onClose} style={{ border: 'none', background: 'transparent', color: 'var(--color-text-muted)', cursor: 'pointer', fontSize: 16 }}>✕</button>
        </div>
        {children}
      </div>
    </>
  );
}

function Field({ label: lbl, children }: { label: string; children: React.ReactNode }) {
  return (
    <div style={{ marginBottom: 12 }}>
      <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--color-text-muted)', marginBottom: 5 }}>{lbl}</div>
      {children}
    </div>
  );
}

// ── Search Providers ──────────────────────────────────────────────

function SearchSection() {
  const [providers, setProviders] = useState<any[]>([]);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [keyInput, setKeyInput] = useState('');
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);

  const load = useCallback(async () => {
    try {
      const res = await apiClient.listSearchProviders();
      setProviders(res.data?.providers || []);
    } catch { /* noop */ }
  }, []);

  useEffect(() => { load(); }, [load]);

  const save = async (id: string) => {
    try {
      await apiClient.setSearchProviderKey(id, keyInput.trim());
      setEditingId(null); setKeyInput('');
      setMsg({ ok: true, text: 'API key saved ✓' });
      await load();
      setTimeout(() => setMsg(null), 2500);
    } catch (err: any) {
      setMsg({ ok: false, text: err?.response?.data?.detail || 'Failed to save' });
    }
  };

  const remove = async (id: string) => {
    try {
      await apiClient.deleteSearchProviderKey(id);
      setMsg({ ok: true, text: 'API key removed' });
      await load();
      setTimeout(() => setMsg(null), 2500);
    } catch { /* noop */ }
  };

  return (
    <>
      <SectionTitle title="Search Providers" desc="API keys for web search providers used by agents." />
      <div style={{ background: 'var(--color-panel-dark, #fff)', border: '1px solid var(--color-border)', borderRadius: 10, padding: '6px 0' }}>
        {providers.map(p => (
          <div key={p.id} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, padding: '9px 20px', borderBottom: '1px solid var(--color-border)' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, minWidth: 0 }}>
              <span style={{ fontSize: 13, fontWeight: 500, color: 'var(--color-text-primary)' }}>{p.name || p.id}</span>
              {p.has_api_key
                ? <span style={{ fontSize: 11, color: '#22c55e' }}>✓ Key set</span>
                : <span style={{ fontSize: 11, color: 'var(--color-text-muted)' }}>No key</span>}
            </div>
            <div style={{ display: 'flex', gap: 6 }}>
              {editingId === p.id ? (
                <>
                  <input
                    type="password" value={keyInput} onChange={e => setKeyInput(e.target.value)}
                    placeholder="API key"
                    autoFocus
                    style={{ width: 160, padding: '5px 8px', borderRadius: 6, fontSize: 12, border: '1px solid var(--color-border-dark)', background: 'var(--color-input-background, #fff)', color: 'var(--color-text-primary)', outline: 'none' }}
                  />
                  <Btn variant="primary" onClick={() => save(p.id)}>Save</Btn>
                  <Btn onClick={() => setEditingId(null)}>Cancel</Btn>
                </>
              ) : (
                <>
                  <Btn onClick={() => { setEditingId(p.id); setKeyInput(''); }}>Edit</Btn>
                  {p.has_api_key && <Btn variant="danger" onClick={() => remove(p.id)}>Remove</Btn>}
                </>
              )}
            </div>
          </div>
        ))}
        {providers.length === 0 && <div style={{ padding: '14px 20px', fontSize: 12.5, color: 'var(--color-text-muted)' }}>No search providers.</div>}
        {msg && <div style={{ padding: '8px 20px', fontSize: 12, color: msg.ok ? '#22c55e' : '#ef4444' }}>{msg.text}</div>}
      </div>
    </>
  );
}

// ── Workspace ──────────────────────────────────────────────────────

function WorkspaceSection() {
  const [ws, setWs] = useState<any>(null);
  const [path, setPath] = useState('');
  const [saved, setSaved] = useState(false);

  const load = useCallback(async () => {
    try {
      const res = await apiClient.getWorkspaceSettings();
      setWs(res.data || {});
      setPath(res.data?.workspace_path || '');
    } catch { /* noop */ }
  }, []);

  useEffect(() => { load(); }, [load]);

  const save = async (patch: Record<string, any>) => {
    setSaved(false);
    try {
      await apiClient.updateWorkspaceSettings(patch as any);
      setWs((prev: any) => ({ ...(prev || {}), ...patch }));
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } catch (err: any) {
      alert(err?.response?.data?.detail || 'Failed to save workspace settings');
    }
  };

  const setField = (key: string, value: any) => save({ [key]: value });

  return (
    <>
      <SectionTitle title="Workspace" desc="Where your projects, agents, uploads and generated files live." />
      <div style={{ background: 'var(--color-panel-dark, #fff)', border: '1px solid var(--color-border)', borderRadius: 10, padding: '4px 20px' }}>
        <Row label="Workspace path" hint="The root folder for all project and agent data">
          <div style={{ display: 'flex', gap: 6 }}>
            <TextInput value={path} onChange={setPath} mono placeholder="/path/to/workspace" width={300} />
            <Btn variant="primary" onClick={() => save({ workspace_path: path })}>{saved ? 'Saved ✓' : 'Save'}</Btn>
          </div>
        </Row>
        <Row label="Allow read" hint="Agents may read files inside the workspace">
          <Toggle checked={ws?.allow_read ?? true} onChange={v => setField('allow_read', v)} />
        </Row>
        <Row label="Allow write" hint="Agents may write files inside the workspace">
          <Toggle checked={ws?.allow_write ?? true} onChange={v => setField('allow_write', v)} />
        </Row>
        <Row label="Require approval for edits" hint="Ask before the agent modifies files">
          <Toggle checked={ws?.require_approval ?? true} onChange={v => setField('require_approval', v)} />
        </Row>
        <Row label="Backup before edit" hint="Keep a backup copy before the agent edits a file">
          <Toggle checked={ws?.backup_before_edit ?? true} onChange={v => setField('backup_before_edit', v)} />
        </Row>
        <Row label="Auto-detect Git" hint="Detect repositories inside the workspace">
          <Toggle checked={ws?.auto_detect_git ?? true} onChange={v => setField('auto_detect_git', v)} />
        </Row>
      </div>
    </>
  );
}

// ── Storage ────────────────────────────────────────────────────────

function StorageSection() {
  const [mode, setMode] = useState<'local' | 'db'>('local');
  const [source, setSource] = useState<'env' | 'db'>('env');

  useEffect(() => {
    apiClient.getStorageMode().then((res: any) => {
      setMode(res.data?.mode || 'local');
      setSource(res.data?.source || 'env');
    }).catch(() => {});
  }, []);

  const switchMode = async (next: 'local' | 'db') => {
    setMode(next);
    try { await apiClient.updateStorageMode({ mode: next }); } catch { /* noop */ }
  };

  return (
    <>
      <SectionTitle title="Storage" desc="Where files are persisted." />
      <div style={{ background: 'var(--color-panel-dark, #fff)', border: '1px solid var(--color-border)', borderRadius: 10, padding: '4px 20px' }}>
        <Row label="Storage mode" hint={`Source: ${source === 'db' ? 'persisted (overrides .env)' : '.env / default'}`}>
          <Select value={mode} onChange={v => switchMode(v as 'local' | 'db')} options={[
            { value: 'local', label: 'Local disk (backend/outputs)' },
            { value: 'db', label: 'PostgreSQL (BYTEA)' },
          ]} width={280} />
        </Row>
        <p style={{ fontSize: 11.5, color: 'var(--color-text-muted)', padding: '8px 0 12px', margin: 0 }}>
          Switching modes does not migrate data — use the CLI/batch scripts for that.
        </p>
      </div>
    </>
  );
}

// ── About ──────────────────────────────────────────────────────────

function AboutSection() {
  return (
    <>
      <SectionTitle title="About LangConfig" desc="Visual platform for building LangChain agents and LangGraph workflows." />
      <div style={{ background: 'var(--color-panel-dark, #fff)', border: '1px solid var(--color-border)', borderRadius: 10, padding: '4px 20px' }}>
        <Row label="Version"><span style={{ fontSize: 13, color: 'var(--color-text-muted)' }}>0.1.0</span></Row>
        <Row label="Configuration" hint="API keys and settings are stored in PostgreSQL (encrypted); the rest lives in .env">
          <span style={{ fontSize: 13, color: 'var(--color-text-muted)' }}>See .env</span>
        </Row>
        <Row label="First-time setup" hint="Re-open the setup wizard (API key + workspace)">
          <Btn variant="primary" onClick={() => window.dispatchEvent(new CustomEvent('setup:open'))}>Re-run setup wizard</Btn>
        </Row>
      </div>
    </>
  );
}
