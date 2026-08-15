/**
 * SettingsModal — DSH-style settings, replicated from the DeepSeek Harness
 * GUI source (packages/client/ui-settings-general + ui-settings-models):
 *
 * - A centered modal panel (800×min(800,100vh−48), r24, layer-2 fill, lv3
 *   shadow) over a dimmed full-viewport mask — opened by the activity-bar
 *   gear via the 'settings:open' window event.
 * - Inside: a 188px nav rail (Settings title 16/500; 40px r12 nav cells with
 *   an active fill) + a content column (54px header with a 28×28 round close,
 *   scrollable options area, section max-width 720px).
 * - DSH visual language: 14/22 body, 12/18 captions, capsule buttons
 *   (h36 r18; dense h28 r14), h32 r8 inputs, hairline borders, provider rows
 *   as outlined cards with credential dots, filled editor modules, dashed
 *   add-provider buttons.
 */
import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { themes, useTheme, type ThemeName } from '../lib/themes'
import apiClient from '../lib/api-client'

type SectionId = 'general' | 'models' | 'search' | 'workspace' | 'storage' | 'about'

const SECTIONS: { id: SectionId; label: string; icon: string }[] = [
  { id: 'general', label: 'General', icon: 'tune' },
  { id: 'models', label: 'Models', icon: 'smart_toy' },
  { id: 'search', label: 'Search Providers', icon: 'travel_explore' },
  { id: 'workspace', label: 'Workspace', icon: 'folder_open' },
  { id: 'storage', label: 'Storage', icon: 'storage' },
  { id: 'about', label: 'About', icon: 'info' },
]

const PROVIDER_FIELD: Record<string, string> = {
  openai: 'openai_api_key', anthropic: 'anthropic_api_key', google: 'google_api_key',
  cohere: 'cohere_api_key', replicate: 'replicate_api_key', deepseek: 'deepseek_api_key',
  glm: 'glm_api_key', minimax: 'minimax_api_key', qwen: 'qwen_api_key', kimi: 'kimi_api_key',
  agnes: 'agnes_api_key', tavily: 'tavily_api_key', serper: 'serper_api_key',
}

const PROVIDER_BASE_FIELD: Record<string, string> = {
  openai: 'openai_base_url', anthropic: 'anthropic_base_url', google: 'google_base_url',
  cohere: 'cohere_base_url', replicate: 'replicate_base_url', deepseek: 'deepseek_api_base',
  glm: 'glm_api_base', minimax: 'minimax_api_base', qwen: 'qwen_api_base', kimi: 'kimi_api_base',
  agnes: 'agnes_base_url',
}

const PROVIDER_LABEL: Record<string, string> = {
  openai: 'OpenAI', anthropic: 'Anthropic', google: 'Google', deepseek: 'DeepSeek',
  glm: 'GLM', minimax: 'MiniMax', qwen: 'Qwen', kimi: 'Kimi', cohere: 'Cohere',
  replicate: 'Replicate', agnes: 'Agnes', tavily: 'Tavily', serper: 'Serper',
}

const label = (p: string) => PROVIDER_LABEL[p] || (p.charAt(0).toUpperCase() + p.slice(1))

// Token mapping: DSH --dsw-alias-* → LangConfig CSS variables.
const tok = {
  labelPrimary: 'var(--color-text-primary)',
  labelSecondary: 'var(--color-text-muted)',
  labelTertiary: 'var(--color-text-muted)',
  borderL2: 'var(--color-border)',
  borderL3: 'var(--color-border-dark)',
  layer1: 'var(--color-input-background, var(--color-background-light))',
  layer2: 'var(--color-panel-dark)',
  module: 'rgba(127,127,127,0.08)',
  hover: 'rgba(127,127,127,0.12)',
  navActive: 'rgba(127,127,127,0.16)',
  primary: 'var(--color-primary)',
  success: '#22c55e',
  error: '#e5484d',
}

// ── Small presentational pieces (DSH vocabulary) ──────────────────

function SectionTitle({ title, desc }: { title: string; desc?: string }) {
  return (
    <div style={{ marginBottom: 12 }}>
      <h2 style={{ margin: 0, fontSize: 16, lineHeight: '24px', fontWeight: 500, color: tok.labelPrimary }}>{title}</h2>
      {desc && <p style={{ margin: '2px 0 0', fontSize: 14, lineHeight: '22px', color: tok.labelTertiary }}>{desc}</p>}
    </div>
  )
}

function Row({ label: rowLabel, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 16, padding: '12px 0', borderBottom: '1px solid var(--color-border)' }}>
      <div style={{ minWidth: 0 }}>
        <div style={{ fontSize: 14, lineHeight: '22px', fontWeight: 400, color: tok.labelPrimary }}>{rowLabel}</div>
        {hint && <div style={{ fontSize: 12, lineHeight: '18px', color: tok.labelTertiary, marginTop: 1 }}>{hint}</div>}
      </div>
      <div style={{ flexShrink: 0 }}>{children}</div>
    </div>
  )
}

function Toggle({ checked, onChange }: { checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <button
      role="switch" aria-checked={checked} onClick={() => onChange(!checked)}
      style={{
        width: 34, height: 20, borderRadius: 999, border: 'none', cursor: 'pointer', position: 'relative', flexShrink: 0,
        background: checked ? tok.primary : 'var(--color-border-dark)', transition: 'background 0.15s',
      }}
    >
      <span style={{ position: 'absolute', top: 2, left: checked ? 16 : 2, width: 16, height: 16, borderRadius: '50%', background: '#fff', transition: 'left 0.15s' }} />
    </button>
  )
}

function Select({ value, onChange, options, width = 220 }: {
  value: string; onChange: (v: string) => void; options: { value: string; label: string; key?: string }[]; width?: number;
}) {
  return (
    <select
      value={value} onChange={e => onChange(e.target.value)}
      style={{
        width, maxWidth: 240, boxSizing: 'border-box', height: 32, padding: '0 32px 0 10px', borderRadius: 8, fontSize: 14, lineHeight: '22px',
        border: `1px solid ${tok.borderL2}`, background: `var(--color-input-background, ${tok.layer1})`, color: tok.labelPrimary,
        outline: 'none', cursor: 'pointer', appearance: 'none', fontFamily: 'inherit',
        backgroundImage: `url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 12 12' fill='none'%3E%3Cpath d='M3 4.5L6 7.5L9 4.5' stroke='%2381858C' stroke-width='1.5' stroke-linecap='round' stroke-linejoin='round'/%3E%3C/svg%3E")`,
        backgroundRepeat: 'no-repeat', backgroundPosition: 'right 12px center', backgroundSize: '12px 12px',
      }}
    >
      {options.map(o => <option key={o.key || o.value} value={o.value}>{o.label}</option>)}
    </select>
  )
}

function Input({ value, onChange, placeholder, mono = false, width = 280, type = 'text' }: {
  value: string; onChange: (v: string) => void; placeholder?: string; mono?: boolean; width?: number | string; type?: string;
}) {
  return (
    <input
      type={type} value={value} onChange={e => onChange(e.target.value)} placeholder={placeholder}
      style={{
        width, boxSizing: 'border-box', height: 32, padding: '0 10px', borderRadius: 8, fontSize: 14, lineHeight: '22px',
        border: `1px solid ${tok.borderL2}`, background: `var(--color-input-background, ${tok.layer1})`, color: tok.labelPrimary,
        outline: 'none', fontFamily: mono ? 'ui-monospace, SFMono-Regular, Menlo, monospace' : 'inherit',
      }}
    />
  )
}

function Btn({ children, onClick, variant = 'ghost', disabled, dense = false }: {
  children: React.ReactNode; onClick?: () => void; variant?: 'primary' | 'ghost' | 'danger'; disabled?: boolean; dense?: boolean;
}) {
  const h = dense ? 28 : 36
  const base: React.CSSProperties = {
    boxSizing: 'border-box', display: 'inline-flex', alignItems: 'center', justifyContent: 'center', gap: 6,
    height: h, padding: dense ? '0 10px' : '0 14px', borderRadius: h / 2,
    fontSize: dense ? 12 : 14, lineHeight: dense ? '18px' : '22px', fontWeight: 400,
    cursor: disabled ? 'default' : 'pointer', opacity: disabled ? 0.4 : 1, whiteSpace: 'nowrap', fontFamily: 'inherit',
  }
  if (variant === 'primary') Object.assign(base, { border: 'none', background: tok.primary, color: '#fff' })
  else if (variant === 'danger') Object.assign(base, { border: 'none', background: 'transparent', color: tok.error })
  else Object.assign(base, { border: `1px solid ${tok.borderL2}`, background: 'transparent', color: tok.labelPrimary })
  return <button style={base} onClick={onClick} disabled={disabled}>{children}</button>
}

function Dot({ state }: { state: 'configured' | 'missing' }) {
  return (
    <span
      role="img" title={state === 'configured' ? 'Configured' : 'Missing key'}
      style={{ display: 'inline-block', width: 8, height: 8, borderRadius: '50%', flex: 'none', background: state === 'configured' ? tok.success : tok.error }}
    />
  )
}

// ── The modal shell ───────────────────────────────────────────────

export default function SettingsModal({ onClose }: { onClose: () => void }) {
  const { i18n } = useTranslation()
  const { theme: activeTheme, setTheme } = useTheme()
  const [section, setSection] = useState<SectionId>('general')

  useEffect(() => {
    const h = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', h)
    return () => document.removeEventListener('keydown', h)
  }, [onClose])

  return (
    <div style={{ position: 'fixed', inset: 0, zIndex: 1000, display: 'flex', alignItems: 'center', justifyContent: 'center' }} role="presentation">
      <div onClick={onClose} aria-hidden="true" style={{ position: 'absolute', inset: 0, background: 'rgba(0,0,0,0.24)', backdropFilter: 'blur(2px)' }} />
      <div
        role="dialog" aria-modal="true"
        style={{
          position: 'relative', zIndex: 1, display: 'flex',
          width: 800, height: 'min(800px, calc(100vh - 48px))', maxWidth: 'calc(100vw - 48px)',
          borderRadius: 24, overflow: 'hidden',
          background: tok.layer2, boxShadow: '0 16px 48px rgba(0,0,0,0.35)',
        }}
      >
        {/* Nav rail (188px) */}
        <nav style={{ flex: 'none', display: 'flex', flexDirection: 'column', gap: 18, width: 188, padding: '22px 12px 0', boxSizing: 'border-box' }}>
          <div style={{ padding: '0 12px', fontSize: 16, lineHeight: '24px', fontWeight: 500, color: tok.labelPrimary }}>Settings</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            {SECTIONS.map(s => {
              const active = section === s.id
              return (
                <button
                  key={s.id} type="button" onClick={() => setSection(s.id)} aria-current={active ? 'true' : undefined}
                  style={{
                    display: 'flex', alignItems: 'center', gap: 8, height: 40, padding: '9px 16px 9px 12px', boxSizing: 'border-box',
                    border: 'none', borderRadius: 12, cursor: 'pointer', textAlign: 'left', fontFamily: 'inherit',
                    fontSize: 14, lineHeight: '22px', fontWeight: 400, color: tok.labelPrimary,
                    background: active ? tok.navActive : 'transparent',
                  }}
                  onMouseEnter={e => { if (!active) e.currentTarget.style.background = tok.hover }}
                  onMouseLeave={e => { if (!active) e.currentTarget.style.background = 'transparent' }}
                >
                  <span className="material-symbols-outlined" style={{ fontSize: 16, flex: 'none' }}>{s.icon}</span>
                  <span style={{ flex: 1, minWidth: 0, overflow: 'hidden', whiteSpace: 'nowrap', textOverflow: 'ellipsis' }}>{s.label}</span>
                </button>
              )
            })}
          </div>
        </nav>

        {/* Content column */}
        <div style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column' }}>
          <div style={{ flex: 'none', display: 'flex', alignItems: 'flex-start', justifyContent: 'flex-end', gap: 8, height: 54, padding: '10px 14px 8px 10px', boxSizing: 'border-box' }}>
            <button
              type="button" onClick={onClose}
              style={{ display: 'inline-flex', alignItems: 'center', justifyContent: 'center', width: 28, height: 28, padding: 0, border: 'none', borderRadius: '50%', background: 'transparent', cursor: 'pointer', color: tok.labelPrimary, fontSize: 14 }}
              onMouseEnter={e => { e.currentTarget.style.background = tok.hover }}
              onMouseLeave={e => { e.currentTarget.style.background = 'transparent' }}
              title="Close"
            >✕</button>
          </div>
          <div style={{ flex: 1, minHeight: 0, padding: '0 24px 24px', overflowY: 'auto' }}>
            <div style={{ maxWidth: 720 }}>
              {section === 'general' && <GeneralSection i18n={i18n} activeTheme={activeTheme.name} setTheme={setTheme} />}
              {section === 'models' && <ModelsSection />}
              {section === 'search' && <SearchSection />}
              {section === 'workspace' && <WorkspaceSection />}
              {section === 'storage' && <StorageSection />}
              {section === 'about' && <AboutSection />}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

// ── General ───────────────────────────────────────────────────────

function GeneralSection({ i18n, activeTheme, setTheme }: {
  i18n: any; activeTheme: string; setTheme: (t: ThemeName) => void;
}) {
  const [gen, setGen] = useState<any>(null)
  const [language, setLanguage] = useState(i18n.language)

  const load = useCallback(async () => {
    try { const res = await apiClient.getGeneralSettings(); setGen(res.data || {}) } catch { /* noop */ }
  }, [])
  useEffect(() => { load() }, [load])

  const update = async (patch: Record<string, any>) => {
    setGen((prev: any) => ({ ...(prev || {}), ...patch }))
    try { await apiClient.updateGeneralSettings(patch as any) } catch { /* noop */ }
  }
  const changeLanguage = async (lang: string) => { setLanguage(lang); i18n.changeLanguage(lang); await update({ language: lang }) }
  const changeTheme = async (name: ThemeName) => { setTheme(name); await update({ theme: name }) }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', width: '100%' }}>
      <Row label="Language" hint="Interface language">
        <Select value={language} onChange={changeLanguage} options={[{ value: 'en', label: 'English' }, { value: 'zh', label: '中文' }]} />
      </Row>
      <Row label="Appearance" hint="Color theme">
        <Select value={activeTheme} onChange={v => changeTheme(v as ThemeName)} options={Object.values(themes).map(th => ({ value: th.name, label: th.displayName }))} />
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
  )
}

// ── Models ────────────────────────────────────────────────────────

interface ModelInfo { model_id: string; display_name?: string; provider: string; capabilities?: Record<string, any> }

function ModelsSection() {
  const [keys, setKeys] = useState<{ provider: string; is_set: boolean; masked_key?: string | null; kind?: string }[]>([])
  const [models, setModels] = useState<{ cloud: ModelInfo[]; local: ModelInfo[] }>({ cloud: [], local: [] })
  const [defaults, setDefaults] = useState<any>({ primary_model: '', fallback_models: [], temperature: 0, max_tokens: 0 })
  const [editing, setEditing] = useState<string | null>(null)
  const [adding, setAdding] = useState(false)
  const [keyInput, setKeyInput] = useState('')
  const [baseUrl, setBaseUrl] = useState('')
  const [newProviderName, setNewProviderName] = useState('')
  const [testing, setTesting] = useState(false)
  const [testMsg, setTestMsg] = useState<{ ok: boolean; msg: string } | null>(null)

  const load = useCallback(async () => {
    try {
      const [keysRes, modelsRes, defaultsRes] = await Promise.all([
        apiClient.getApiKeys(), apiClient.listAvailableModels(), apiClient.getModelDefaults(),
      ])
      setKeys(keysRes.data || [])
      setModels({ cloud: modelsRes.data?.cloud_models || [], local: modelsRes.data?.local_models || [] })
      setDefaults(defaultsRes.data || {})
    } catch (err) { console.error('Failed to load models settings:', err) }
  }, [])
  useEffect(() => { load() }, [load])

  const allModels: { value: string; label: string; key: string }[] = [
    ...models.cloud.map(m => ({ value: m.model_id, label: `${label(m.provider)} — ${m.display_name || m.model_id}`, key: `cloud-${m.provider}-${m.model_id}` })),
    ...models.local.map(m => {
      // Local models identify by `name` (they have no model_id).
      const id = String(m.model_id || (m as any).name || (m as any).id || 'local-model')
      return { value: id, label: `Local — ${m.display_name || id}`, key: `local-${id}` }
    }),
  ]

  const keySet = (provider: string) => keys.find(k => k.provider === provider)?.is_set ?? false

  const saveKey = async (provider: string, key: string, base: string) => {
    const field = PROVIDER_FIELD[provider]
    const baseField = PROVIDER_BASE_FIELD[provider]
    if (!field) return
    const payload: Record<string, string> = { [field]: key.trim() }
    if (base.trim() && baseField) payload[baseField] = base.trim()
    await apiClient.setApiKeys(payload as any)
  }

  const handleEditSave = async (provider: string) => {
    try {
      await saveKey(provider, keyInput, baseUrl)
      setEditing(null); setKeyInput(''); setBaseUrl(''); setTestMsg(null)
      await load()
    } catch (err: any) { setTestMsg({ ok: false, msg: err?.response?.data?.detail || 'Failed to save' }) }
  }

  const handleTest = async (provider: string) => {
    setTesting(true); setTestMsg(null)
    try {
      const res = await apiClient.testApiKey(provider, keyInput || undefined)
      setTestMsg({ ok: !!res.data?.success, msg: res.data?.message || (res.data?.success ? '✓ Connected' : '✗ Failed') })
    } catch { setTestMsg({ ok: false, msg: '✗ Connection failed' }) } finally { setTesting(false) }
  }

  const handleAddProvider = async () => {
    const name = newProviderName.trim().toLowerCase()
    if (!name) return
    const field = PROVIDER_FIELD[name]
    if (!field) { setTestMsg({ ok: false, msg: `Unknown provider '${name}'. Use one of: ${Object.keys(PROVIDER_FIELD).join(', ')}` }); return }
    try {
      await saveKey(name, keyInput, baseUrl)
      setAdding(false); setNewProviderName(''); setKeyInput(''); setBaseUrl(''); setTestMsg(null)
      await load()
    } catch (err: any) { setTestMsg({ ok: false, msg: err?.response?.data?.detail || 'Failed' }) }
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12, width: '100%' }}>
      <SectionTitle title="Models" desc="Default model and API keys for the model providers." />

      {/* Default model rows */}
      <Row label="Default model" hint="Used for agents and chat unless overridden">
        <Select
          value={defaults.primary_model || ''} width={280}
          onChange={async v => { setDefaults((p: any) => ({ ...p, primary_model: v })); try { await apiClient.updateModelDefaultsSettings({ primary_model: v }) } catch {} }}
          options={[{ value: '', label: '— not set —' }, ...allModels]}
        />
      </Row>
      <Row label="Fallback model" hint="Used when the default model fails">
        <Select
          value={defaults.fallback_models?.[0] || ''} width={280}
          onChange={async v => { setDefaults((p: any) => ({ ...p, fallback_models: [v] })); try { await apiClient.updateModelDefaultsSettings({ fallback_models: [v] }) } catch {} }}
          options={[{ value: '', label: '— none —' }, ...allModels]}
        />
      </Row>
      <div style={{ display: 'flex', gap: 24 }}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          <span style={{ fontSize: 12, lineHeight: '18px', fontWeight: 500, color: tok.labelSecondary }}>Temperature</span>
          <Input
            value={String(defaults.temperature ?? 0)} type="number" width={110}
            onChange={async v => { const n = parseFloat(v) || 0; setDefaults((p: any) => ({ ...p, temperature: n })); try { await apiClient.updateModelDefaultsSettings({ temperature: n }) } catch {} }}
          />
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          <span style={{ fontSize: 12, lineHeight: '18px', fontWeight: 500, color: tok.labelSecondary }}>Max tokens</span>
          <Input
            value={String(defaults.max_tokens ?? 0)} type="number" width={140}
            onChange={async v => { const n = parseInt(v, 10) || 0; setDefaults((p: any) => ({ ...p, max_tokens: n })); try { await apiClient.updateModelDefaultsSettings({ max_tokens: n }) } catch {} }}
          />
        </div>
      </div>

      <SectionTitle title="API keys" desc="Enter your API keys to use models from the following providers." />

      {/* Provider rows (outlined cards + credential dot) */}
      <ul style={{ listStyle: 'none', margin: 0, padding: 0, display: 'flex', flexDirection: 'column', gap: 8 }}>
        {keys.length === 0 && <li style={{ fontSize: 14, color: tok.labelTertiary, padding: '8px 0' }}>Loading providers…</li>}
        {keys.filter(k => k.kind !== 'search').map(k => (
          <li key={k.provider} style={{ border: `1px solid ${tok.borderL2}`, borderRadius: 12, padding: '12px 14px', display: 'flex', flexDirection: 'column', gap: 12 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, minWidth: 0 }}>
                <span style={{ fontSize: 14, lineHeight: '22px', fontWeight: 500, color: tok.labelPrimary }}>{label(k.provider)}</span>
                <Dot state={k.is_set ? 'configured' : 'missing'} />
              </span>
              <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4, marginLeft: 'auto' }}>
                <Btn dense onClick={() => { setEditing(k.provider); setKeyInput(''); setBaseUrl(''); setTestMsg(null) }}>Edit</Btn>
              </span>
            </div>
            {editing === k.provider && (
              <div style={{ borderRadius: 12, background: tok.module, padding: '14px 16px', display: 'flex', flexDirection: 'column', gap: 14 }}>
                <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
                  <span style={{ fontSize: 14, lineHeight: '22px', fontWeight: 500, color: tok.labelPrimary }}>{label(k.provider)}</span>
                  <span style={{ fontSize: 12, lineHeight: '18px', color: tok.labelTertiary }}>{k.provider}</span>
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                  <span style={{ fontSize: 12, lineHeight: '18px', fontWeight: 500, color: tok.labelSecondary }}>API key</span>
                  <Input value={keyInput} onChange={setKeyInput} placeholder="sk-… (leave empty to keep current)" mono width="100%" />
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                  <span style={{ fontSize: 12, lineHeight: '18px', fontWeight: 500, color: tok.labelSecondary }}>Customized settings</span>
                  <Input value={baseUrl} onChange={setBaseUrl} placeholder="https://api.example.com (optional)" mono width="100%" />
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                  <span style={{ fontSize: 12, lineHeight: '18px', fontWeight: 500, color: tok.labelSecondary }}>Models</span>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                    {models.cloud.filter(m => m.provider.toLowerCase() === k.provider).map(m => (
                      <div key={m.model_id} style={{ border: `1px solid ${tok.borderL2}`, borderRadius: 8, padding: '6px', display: 'grid', gridTemplateColumns: 'minmax(0,1.4fr) minmax(0,1fr)', gap: 6, alignItems: 'center' }}>
                        <span style={{ fontSize: 13, color: tok.labelPrimary, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{m.display_name || m.model_id}</span>
                        <span style={{ fontSize: 12, color: tok.labelTertiary, fontFamily: 'monospace' }}>{m.model_id}</span>
                      </div>
                    ))}
                    {models.cloud.filter(m => m.provider.toLowerCase() === k.provider).length === 0 && (
                      <div style={{ padding: 12, border: `1px dashed ${tok.borderL3}`, borderRadius: 8, textAlign: 'center', fontSize: 12, color: tok.labelTertiary }}>No models registered for this provider.</div>
                    )}
                  </div>
                </div>
                {testMsg && <div style={{ fontSize: 12, lineHeight: '18px', color: testMsg.ok ? tok.success : tok.error }}>{testMsg.msg}</div>}
                <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
                  <Btn onClick={() => handleTest(k.provider)} disabled={testing}>{testing ? 'Testing…' : 'Test'}</Btn>
                  <Btn onClick={() => setEditing(null)}>Cancel</Btn>
                  <Btn variant="primary" onClick={() => handleEditSave(k.provider)}>Apply</Btn>
                </div>
              </div>
            )}
          </li>
        ))}
      </ul>

      {/* Add provider (dashed, DSH style) */}
      {adding ? (
        <div style={{ borderRadius: 12, background: tok.module, padding: '14px 16px', display: 'flex', flexDirection: 'column', gap: 14 }}>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            <span style={{ fontSize: 12, lineHeight: '18px', fontWeight: 500, color: tok.labelSecondary }}>Provider name</span>
            <Input value={newProviderName} onChange={setNewProviderName} placeholder="e.g. openai, deepseek, anthropic" width="100%" />
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            <span style={{ fontSize: 12, lineHeight: '18px', fontWeight: 500, color: tok.labelSecondary }}>API key</span>
            <Input value={keyInput} onChange={setKeyInput} placeholder="sk-…" mono width="100%" />
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            <span style={{ fontSize: 12, lineHeight: '18px', fontWeight: 500, color: tok.labelSecondary }}>Base URL (optional)</span>
            <Input value={baseUrl} onChange={setBaseUrl} placeholder="https://api.example.com" mono width="100%" />
          </div>
          {testMsg && <div style={{ fontSize: 12, lineHeight: '18px', color: testMsg.ok ? tok.success : tok.error }}>{testMsg.msg}</div>}
          <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
            <Btn onClick={() => setAdding(false)}>Cancel</Btn>
            <Btn variant="primary" onClick={handleAddProvider}>Save</Btn>
          </div>
        </div>
      ) : (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10 }}>
          <button
            type="button" onClick={() => { setAdding(true); setKeyInput(''); setBaseUrl(''); setNewProviderName(''); setTestMsg(null) }}
            style={{
              flex: '1 1 0', minWidth: 180, gap: 6, height: 44, boxSizing: 'border-box',
              display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
              border: `1px dashed ${tok.borderL3}`, borderRadius: 12, background: 'transparent',
              color: tok.labelPrimary, fontFamily: 'inherit', fontSize: 14, lineHeight: '22px', cursor: 'pointer',
            }}
            onMouseEnter={e => { e.currentTarget.style.background = tok.hover }}
            onMouseLeave={e => { e.currentTarget.style.background = 'transparent' }}
          >
            <span className="material-symbols-outlined" style={{ fontSize: 16 }}>add</span>
            Add provider
          </button>
        </div>
      )}
    </div>
  )
}

// ── Search Providers ──────────────────────────────────────────────

function SearchSection() {
  const [providers, setProviders] = useState<any[]>([])
  const [editingId, setEditingId] = useState<string | null>(null)
  const [keyInput, setKeyInput] = useState('')
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null)

  const load = useCallback(async () => {
    try { const res = await apiClient.listSearchProviders(); setProviders(res.data?.providers || []) } catch { /* noop */ }
  }, [])
  useEffect(() => { load() }, [load])

  const save = async (id: string) => {
    try {
      await apiClient.setSearchProviderKey(id, keyInput.trim())
      setEditingId(null); setKeyInput('')
      setMsg({ ok: true, text: 'API key saved ✓' }); await load(); setTimeout(() => setMsg(null), 2500)
    } catch (err: any) { setMsg({ ok: false, text: err?.response?.data?.detail || 'Failed to save' }) }
  }
  const remove = async (id: string) => {
    try { await apiClient.deleteSearchProviderKey(id); setMsg({ ok: true, text: 'API key removed' }); await load(); setTimeout(() => setMsg(null), 2500) } catch { /* noop */ }
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12, width: '100%' }}>
      <SectionTitle title="Search Providers" desc="API keys for web search providers used by agents." />
      <ul style={{ listStyle: 'none', margin: 0, padding: 0, display: 'flex', flexDirection: 'column', gap: 8 }}>
        {providers.map(p => (
          <li key={p.id} style={{ border: `1px solid ${tok.borderL2}`, borderRadius: 12, padding: '12px 14px', display: 'flex', alignItems: 'center', gap: 10 }}>
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, minWidth: 0 }}>
              <span style={{ fontSize: 14, lineHeight: '22px', fontWeight: 500, color: tok.labelPrimary }}>{p.name || p.id}</span>
              <Dot state={p.has_api_key ? 'configured' : 'missing'} />
            </span>
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, marginLeft: 'auto' }}>
              {editingId === p.id ? (
                <>
                  <input
                    type="password" value={keyInput} onChange={e => setKeyInput(e.target.value)} placeholder="API key" autoFocus
                    style={{ width: 170, boxSizing: 'border-box', height: 28, padding: '0 10px', borderRadius: 14, fontSize: 12, lineHeight: '18px', border: `1px solid ${tok.borderL2}`, background: `var(--color-input-background, ${tok.layer1})`, color: tok.labelPrimary, outline: 'none' }}
                  />
                  <Btn dense variant="primary" onClick={() => save(p.id)}>Save</Btn>
                  <Btn dense onClick={() => setEditingId(null)}>Cancel</Btn>
                </>
              ) : (
                <>
                  <Btn dense onClick={() => { setEditingId(p.id); setKeyInput('') }}>Edit</Btn>
                  {p.has_api_key && <Btn dense variant="danger" onClick={() => remove(p.id)}>Remove</Btn>}
                </>
              )}
            </span>
          </li>
        ))}
        {providers.length === 0 && <li style={{ fontSize: 14, color: tok.labelTertiary }}>No search providers.</li>}
      </ul>
      {msg && <div style={{ fontSize: 12, lineHeight: '18px', color: msg.ok ? tok.success : tok.error }}>{msg.text}</div>}
    </div>
  )
}

// ── Workspace ─────────────────────────────────────────────────────

function WorkspaceSection() {
  const [ws, setWs] = useState<any>(null)
  const [path, setPath] = useState('')
  const [saved, setSaved] = useState(false)

  const load = useCallback(async () => {
    try { const res = await apiClient.getWorkspaceSettings(); setWs(res.data || {}); setPath(res.data?.workspace_path || '') } catch { /* noop */ }
  }, [])
  useEffect(() => { load() }, [load])

  const save = async (patch: Record<string, any>) => {
    setSaved(false)
    try {
      await apiClient.updateWorkspaceSettings(patch as any)
      setWs((prev: any) => ({ ...(prev || {}), ...patch })); setSaved(true); setTimeout(() => setSaved(false), 2000)
    } catch (err: any) { alert(err?.response?.data?.detail || 'Failed to save workspace settings') }
  }
  const setField = (key: string, value: any) => save({ [key]: value })

  return (
    <div style={{ display: 'flex', flexDirection: 'column', width: '100%' }}>
      <SectionTitle title="Workspace" desc="Where your projects, agents, uploads and generated files live." />
      <Row label="Workspace path" hint="The root folder for all project and agent data">
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <Input value={path} onChange={setPath} mono placeholder="/path/to/workspace" width={300} />
          <Btn variant="primary" onClick={() => save({ workspace_path: path })}>{saved ? 'Saved ✓' : 'Save'}</Btn>
        </div>
      </Row>
      <Row label="Allow read" hint="Agents may read files inside the workspace"><Toggle checked={ws?.allow_read ?? true} onChange={v => setField('allow_read', v)} /></Row>
      <Row label="Allow write" hint="Agents may write files inside the workspace"><Toggle checked={ws?.allow_write ?? true} onChange={v => setField('allow_write', v)} /></Row>
      <Row label="Require approval for edits" hint="Ask before the agent modifies files"><Toggle checked={ws?.require_approval ?? true} onChange={v => setField('require_approval', v)} /></Row>
      <Row label="Backup before edit" hint="Keep a backup copy before the agent edits a file"><Toggle checked={ws?.backup_before_edit ?? true} onChange={v => setField('backup_before_edit', v)} /></Row>
      <Row label="Auto-detect Git" hint="Detect repositories inside the workspace"><Toggle checked={ws?.auto_detect_git ?? true} onChange={v => setField('auto_detect_git', v)} /></Row>
    </div>
  )
}

// ── Storage ───────────────────────────────────────────────────────

function StorageSection() {
  const [mode, setMode] = useState<'local' | 'db'>('local')
  const [source, setSource] = useState<'env' | 'db'>('env')

  useEffect(() => {
    apiClient.getStorageMode().then((res: any) => { setMode(res.data?.mode || 'local'); setSource(res.data?.source || 'env') }).catch(() => {})
  }, [])

  const switchMode = async (next: 'local' | 'db') => { setMode(next); try { await apiClient.updateStorageMode({ mode: next }) } catch { /* noop */ } }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', width: '100%' }}>
      <SectionTitle title="Storage" desc="Where files are persisted." />
      <Row label="Storage mode" hint={`Source: ${source === 'db' ? 'persisted (overrides .env)' : '.env / default'}`}>
        <Select value={mode} onChange={v => switchMode(v as 'local' | 'db')} width={280} options={[
          { value: 'local', label: 'Local disk (backend/outputs)' },
          { value: 'db', label: 'PostgreSQL (BYTEA)' },
        ]} />
      </Row>
      <p style={{ fontSize: 12, lineHeight: '18px', color: tok.labelTertiary, margin: '8px 0 0' }}>
        Switching modes does not migrate data — use the CLI/batch scripts for that.
      </p>
    </div>
  )
}

// ── About ─────────────────────────────────────────────────────────

function AboutSection() {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', width: '100%' }}>
      <SectionTitle title="About LangConfig" desc="Visual platform for building LangChain agents and LangGraph workflows." />
      <Row label="Version"><span style={{ fontSize: 14, color: tok.labelTertiary }}>0.1.0</span></Row>
      <Row label="Configuration" hint="API keys and settings are stored in PostgreSQL (encrypted); the rest lives in .env">
        <span style={{ fontSize: 14, color: tok.labelTertiary }}>See .env</span>
      </Row>
      <Row label="First-time setup" hint="Re-open the setup wizard (API key + workspace)">
        <Btn variant="primary" onClick={() => window.dispatchEvent(new CustomEvent('setup:open'))}>Re-run setup wizard</Btn>
      </Row>
    </div>
  )
}
