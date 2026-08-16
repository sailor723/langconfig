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

type SectionId = 'general' | 'models' | 'webapi' | 'localmodels' | 'workspace' | 'storage' | 'about'

const SECTIONS: { id: SectionId; labelKey: string; icon: string }[] = [
  { id: 'general', labelKey: 'settings_general', icon: 'tune' },
  { id: 'models', labelKey: 'settings_models', icon: 'smart_toy' },
  { id: 'webapi', labelKey: 'settings_search_providers', icon: 'travel_explore' },
  { id: 'localmodels', labelKey: 'settings_local_models', icon: 'terminal' },
  { id: 'workspace', labelKey: 'settings_workspace', icon: 'folder_open' },
  { id: 'storage', labelKey: 'settings_storage', icon: 'storage' },
  { id: 'about', labelKey: 'settings_about', icon: 'info' },
]

const PROVIDER_FIELD: Record<string, string> = {
  openai: 'openai_api_key', anthropic: 'anthropic_api_key', google: 'google_api_key',
  cohere: 'cohere_api_key', replicate: 'replicate_api_key', deepseek: 'deepseek_api_key',
  glm: 'glm_api_key', minimax: 'minimax_api_key', qwen: 'qwen_api_key', kimi: 'kimi_api_key',
  agnes: 'agnes_api_key',
}

// Web API providers (search engines etc.) — shown in their own Settings
// section ("Web API"), NOT mixed into the LLM Models list.
const WEB_API_PROVIDERS = new Set(['tavily', 'serper'])

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

// ── DSH-style settings wire helpers (docs/settings-refactor.md §6) ─────────

interface SettingsNs {
  ns: string
  schema: any
  value: Record<string, any>
  user: Record<string, any>
  revision: number
  writable: boolean
  secrets: { path: string[]; set: boolean }[]
}

type MutateOp = { op: 'set' | 'unset'; path: string[]; value?: any }

async function describeNs(ns: string): Promise<SettingsNs | undefined> {
  try {
    const res = await apiClient.describeSettings()
    return (res.data?.namespaces || []).find((n: any) => n.ns === ns)
  } catch {
    return undefined
  }
}

/** Optimistic write helper: returns true on success, false on conflict/error
 * (callers re-read from describe to recover the server truth). */
async function mutateNs(ns: string, ops: MutateOp[]): Promise<boolean> {
  try {
    await apiClient.mutateSettings({ ns, ops })
    return true
  } catch {
    return false
  }
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
  const { i18n, t } = useTranslation('chat')
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
          <div style={{ padding: '0 12px', fontSize: 16, lineHeight: '24px', fontWeight: 500, color: tok.labelPrimary }}>{t('settings_title')}</div>
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
                  <span style={{ flex: 1, minWidth: 0, overflow: 'hidden', whiteSpace: 'nowrap', textOverflow: 'ellipsis' }}>{t(s.labelKey)}</span>
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
              {section === 'webapi' && <SearchSection />}
              {section === 'localmodels' && <LocalModelsSection />}
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
  const { t } = useTranslation('chat')
  const [gen, setGen] = useState<any>(null)
  const [language, setLanguage] = useState(i18n.language)

  const load = useCallback(async () => {
    try { const ns = await describeNs('general'); setGen(ns?.value || {}) } catch { /* noop */ }
  }, [])
  useEffect(() => { load() }, [load])

  const update = async (patch: Record<string, any>) => {
    setGen((prev: any) => ({ ...(prev || {}), ...patch }))
    const ok = await mutateNs('general', Object.entries(patch).map(([k, v]) => ({ op: 'set', path: [k], value: v })))
    if (!ok) await load()  // conflict/error — re-read the server truth
  }
  const changeLanguage = async (lang: string) => { setLanguage(lang); i18n.changeLanguage(lang); await update({ language: lang }) }
  const changeTheme = async (name: ThemeName) => { setTheme(name); await update({ theme: name }) }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', width: '100%' }}>
      <Row label={t('settings_language')} hint={t('settings_language_label')}>
        <Select value={language} onChange={changeLanguage} options={[{ value: 'en', label: 'English' }, { value: 'zh', label: '中文' }]} />
      </Row>
      <Row label={t('settings_appearance')} hint={t('settings_color_theme')}>
        <Select value={activeTheme} onChange={v => changeTheme(v as ThemeName)} options={Object.values(themes).map(th => ({ value: th.name, label: th.displayName }))} />
      </Row>
      <Row label={t('settings_auto_save')} hint={t('settings_auto_save_desc')}>
        <Toggle checked={gen?.auto_save ?? true} onChange={v => update({ auto_save: v })} />
      </Row>
      <Row label={t('settings_confirm_before_delete')} hint={t('settings_confirm_before_delete_hint')}>
        <Toggle checked={gen?.confirm_before_delete ?? true} onChange={v => update({ confirm_before_delete: v })} />
      </Row>
      <Row label={t('settings_show_notifications')} hint={t('settings_show_notifications_hint')}>
        <Toggle checked={gen?.show_notifications ?? true} onChange={v => update({ show_notifications: v })} />
      </Row>
      <Row label={t('settings_telemetry')} hint={t('settings_telemetry_desc')}>
        <Toggle checked={gen?.telemetry ?? false} onChange={v => update({ telemetry: v })} />
      </Row>
    </div>
  )
}

// ── Models ────────────────────────────────────────────────────────

interface ModelInfo { model_id: string; display_name?: string; provider: string; capabilities?: Record<string, any> }

function ModelsSection() {
  const { t } = useTranslation('chat')
  const [keys, setKeys] = useState<{ provider: string; is_set: boolean }[]>([])
  const [models, setModels] = useState<{ cloud: ModelInfo[]; local: ModelInfo[] }>({ cloud: [], local: [] })
  const [defaults, setDefaults] = useState<any>({ primary_model: '', fallback_models: [], temperature: 0, max_tokens: 0 })
  const [editing, setEditing] = useState<string | null>(null)
  const [adding, setAdding] = useState(false)
  const [keyInput, setKeyInput] = useState('')
  const [baseUrl, setBaseUrl] = useState('')
  const [newProviderName, setNewProviderName] = useState('')
  const [testingProvider, setTestingProvider] = useState<string | null>(null)
  const [testMsg, setTestMsg] = useState<{ ok: boolean; msg: string } | null>(null)

  const load = useCallback(async () => {
    try {
      const [descRes, modelsRes] = await Promise.all([
        apiClient.describeSettings(), apiClient.listAvailableModels(),
      ])
      const ns: SettingsNs | undefined = (descRes.data?.namespaces || []).find((n: any) => n.ns === 'models')
      const value = ns?.value || {}
      // Provider rows derive from the redacted secret positions (DSH dots):
      // models.api_keys.* fields, no values ever cross the wire. Web API
      // providers (tavily/serper) are excluded here — they live in the
      // dedicated "Web API" settings section.
      const providers = (ns?.secrets || [])
        .filter(s => s.path[0] === 'api_keys')
        .map(s => ({ provider: s.path[1].replace(/_api_key$/, ''), is_set: s.set }))
        .filter(p => !WEB_API_PROVIDERS.has(p.provider))
      setKeys(providers)
      setDefaults({
        primary_model: value.primary_model || '',
        fallback_models: value.fallback_models || [],
        temperature: value.default_temperature ?? 0,
        max_tokens: value.max_tokens ?? 0,
      })
      setModels({ cloud: modelsRes.data?.cloud_models || [], local: modelsRes.data?.local_models || [] })
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

  const saveKey = async (provider: string, key: string, base: string) => {
    const field = PROVIDER_FIELD[provider]
    const baseField = PROVIDER_BASE_FIELD[provider]
    if (!field) return
    const ops: MutateOp[] = []
    const k = key.trim()
    if (k) ops.push({ op: 'set', path: ['api_keys', field], value: k })
    else ops.push({ op: 'unset', path: ['api_keys', field] })
    const b = base.trim()
    if (b && baseField) ops.push({ op: 'set', path: ['api_keys', baseField], value: b })
    await mutateNs('models', ops)
  }

  /** Optimistic update of one model-defaults field (temperature → the models
   * namespace's default_temperature). */
  const updateDefault = async (patch: Record<string, any>) => {
    setDefaults((p: any) => ({ ...p, ...patch }))
    const ops: MutateOp[] = Object.entries(patch).map(([k, v]) => ({
      op: 'set', path: [k === 'temperature' ? 'default_temperature' : k], value: v,
    }))
    const ok = await mutateNs('models', ops)
    if (!ok) await load()
  }

  const handleEditSave = async (provider: string) => {
    try {
      await saveKey(provider, keyInput, baseUrl)
      setEditing(null); setKeyInput(''); setBaseUrl(''); setTestMsg(null)
      await load()
    } catch (err: any) { setTestMsg({ ok: false, msg: err?.response?.data?.detail || 'Failed to save' }) }
  }

  const handleTest = async (provider: string) => {
    setTestingProvider(provider); setTestMsg(null)
    try {
      // Test the DRAFT key when one is entered, else the SAVED key (none →
      // backend resolves the stored models.api_keys value).
      const res = await apiClient.testApiKey(provider, keyInput.trim() || undefined)
      setTestMsg({ ok: !!res.data?.success, msg: res.data?.message || (res.data?.success ? '✓ Connected' : '✗ Failed') })
    } catch { setTestMsg({ ok: false, msg: '✗ Connection failed' }) } finally { setTestingProvider(null) }
  }

  const handleAddProvider = async () => {
    const name = newProviderName.trim().toLowerCase()
    if (!name) return
    const field = PROVIDER_FIELD[name]
    if (!field) { setTestMsg({ ok: false, msg: t('settings_unknown_provider', { name, list: Object.keys(PROVIDER_FIELD).join(', ') }) }); return }
    try {
      await saveKey(name, keyInput, baseUrl)
      setAdding(false); setNewProviderName(''); setKeyInput(''); setBaseUrl(''); setTestMsg(null)
      await load()
    } catch (err: any) { setTestMsg({ ok: false, msg: err?.response?.data?.detail || 'Failed' }) }
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12, width: '100%' }}>
      <SectionTitle title={t('settings_models_title')} desc={t('settings_models_desc')} />

      {/* Default model rows */}
      <Row label={t('settings_default_model')} hint={t('settings_default_model_hint')}>
        <Select
          value={defaults.primary_model || ''} width={280}
          onChange={v => updateDefault({ primary_model: v })}
          options={[{ value: '', label: t('settings_not_set') }, ...allModels]}
        />
      </Row>
      <Row label={t('settings_fallback_model')} hint={t('settings_fallback_model_hint')}>
        <Select
          value={defaults.fallback_models?.[0] || ''} width={280}
          onChange={v => updateDefault({ fallback_models: [v] })}
          options={[{ value: '', label: t('settings_none') }, ...allModels]}
        />
      </Row>
      <div style={{ display: 'flex', gap: 24 }}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          <span style={{ fontSize: 12, lineHeight: '18px', fontWeight: 500, color: tok.labelSecondary }}>{t('settings_temperature')}</span>
          <Input
            value={String(defaults.temperature ?? 0)} type="number" width={110}
            onChange={v => { const n = parseFloat(v) || 0; updateDefault({ temperature: n }) }}
          />
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          <span style={{ fontSize: 12, lineHeight: '18px', fontWeight: 500, color: tok.labelSecondary }}>{t('settings_max_tokens')}</span>
          <Input
            value={String(defaults.max_tokens ?? 0)} type="number" width={140}
            onChange={v => { const n = parseInt(v, 10) || 0; updateDefault({ max_tokens: n }) }}
          />
        </div>
      </div>

      <SectionTitle title={t('settings_api_keys_heading')} desc={t('settings_models_keys_desc')} />

      {/* Provider rows (outlined cards + credential dot) */}
      <ul style={{ listStyle: 'none', margin: 0, padding: 0, display: 'flex', flexDirection: 'column', gap: 8 }}>
        {keys.length === 0 && <li style={{ fontSize: 14, color: tok.labelTertiary, padding: '8px 0' }}>{t('settings_loading_providers')}</li>}
        {keys.map(k => (
          <li key={k.provider} style={{ border: `1px solid ${tok.borderL2}`, borderRadius: 12, padding: '12px 14px', display: 'flex', flexDirection: 'column', gap: 12 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, minWidth: 0 }}>
                <span style={{ fontSize: 14, lineHeight: '22px', fontWeight: 500, color: tok.labelPrimary }}>{label(k.provider)}</span>
                <Dot state={k.is_set ? 'configured' : 'missing'} />
              </span>
              <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4, marginLeft: 'auto' }}>
                <Btn dense onClick={() => handleTest(k.provider)} disabled={testingProvider === k.provider}>
                  {testingProvider === k.provider ? t('settings_testing') : t('settings_test')}
                </Btn>
                <Btn dense onClick={() => { setEditing(k.provider); setKeyInput(''); setBaseUrl(''); setTestMsg(null) }}>{t('settings_edit')}</Btn>
              </span>
            </div>
            {editing === k.provider && (
              <div style={{ borderRadius: 12, background: tok.module, padding: '14px 16px', display: 'flex', flexDirection: 'column', gap: 14 }}>
                <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
                  <span style={{ fontSize: 14, lineHeight: '22px', fontWeight: 500, color: tok.labelPrimary }}>{label(k.provider)}</span>
                  <span style={{ fontSize: 12, lineHeight: '18px', color: tok.labelTertiary }}>{k.provider}</span>
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                  <span style={{ fontSize: 12, lineHeight: '18px', fontWeight: 500, color: tok.labelSecondary }}>{t('settings_api_key')}</span>
                  <Input value={keyInput} onChange={setKeyInput} placeholder="sk-… (leave empty to keep current)" mono width="100%" />
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                  <span style={{ fontSize: 12, lineHeight: '18px', fontWeight: 500, color: tok.labelSecondary }}>{t('settings_customized_settings')}</span>
                  <Input value={baseUrl} onChange={setBaseUrl} placeholder="https://api.example.com (optional)" mono width="100%" />
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                  <span style={{ fontSize: 12, lineHeight: '18px', fontWeight: 500, color: tok.labelSecondary }}>{t('settings_models_list')}</span>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                    {models.cloud.filter(m => m.provider.toLowerCase() === k.provider).map(m => (
                      <div key={m.model_id} style={{ border: `1px solid ${tok.borderL2}`, borderRadius: 8, padding: '6px', display: 'grid', gridTemplateColumns: 'minmax(0,1.4fr) minmax(0,1fr)', gap: 6, alignItems: 'center' }}>
                        <span style={{ fontSize: 13, color: tok.labelPrimary, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{m.display_name || m.model_id}</span>
                        <span style={{ fontSize: 12, color: tok.labelTertiary, fontFamily: 'monospace' }}>{m.model_id}</span>
                      </div>
                    ))}
                    {models.cloud.filter(m => m.provider.toLowerCase() === k.provider).length === 0 && (
                      <div style={{ padding: 12, border: `1px dashed ${tok.borderL3}`, borderRadius: 8, textAlign: 'center', fontSize: 12, color: tok.labelTertiary }}>{t('settings_no_models')}</div>
                    )}
                  </div>
                </div>
                {testMsg && <div style={{ fontSize: 12, lineHeight: '18px', color: testMsg.ok ? tok.success : tok.error }}>{testMsg.msg}</div>}
                <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
                  <Btn onClick={() => handleTest(k.provider)} disabled={testingProvider === k.provider}>{testingProvider === k.provider ? t('settings_testing') : t('settings_test')}</Btn>
                  <Btn onClick={() => setEditing(null)}>{t('settings_cancel')}</Btn>
                  <Btn variant="primary" onClick={() => handleEditSave(k.provider)}>{t('settings_apply')}</Btn>
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
            <span style={{ fontSize: 12, lineHeight: '18px', fontWeight: 500, color: tok.labelSecondary }}>{t('settings_provider_name')}</span>
            <Input value={newProviderName} onChange={setNewProviderName} placeholder="e.g. openai, deepseek, anthropic" width="100%" />
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            <span style={{ fontSize: 12, lineHeight: '18px', fontWeight: 500, color: tok.labelSecondary }}>API key</span>
            <Input value={keyInput} onChange={setKeyInput} placeholder="sk-…" mono width="100%" />
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            <span style={{ fontSize: 12, lineHeight: '18px', fontWeight: 500, color: tok.labelSecondary }}>{t('settings_base_url_optional')}</span>
            <Input value={baseUrl} onChange={setBaseUrl} placeholder="https://api.example.com" mono width="100%" />
          </div>
          {testMsg && <div style={{ fontSize: 12, lineHeight: '18px', color: testMsg.ok ? tok.success : tok.error }}>{testMsg.msg}</div>}
          <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
            <Btn onClick={() => setAdding(false)}>{t('settings_cancel')}</Btn>
            <Btn variant="primary" onClick={handleAddProvider}>{t('settings_save')}</Btn>
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
            {t('settings_add_provider')}
          </button>
        </div>
      )}
    </div>
  )
}

// ── Search Providers ──────────────────────────────────────────────

function SearchSection() {
  const { t } = useTranslation('chat')
  const [providers, setProviders] = useState<any[]>([])
  const [editingId, setEditingId] = useState<string | null>(null)
  const [keyInput, setKeyInput] = useState('')
  const [testingId, setTestingId] = useState<string | null>(null)
  const [testMsg, setTestMsg] = useState<{ id: string | null; ok: boolean; text: string } | null>(null)

  const load = useCallback(async () => {
    try { const res = await apiClient.listSearchProviders(); setProviders(res.data?.providers || []) } catch { /* noop */ }
  }, [])
  useEffect(() => { load() }, [load])

  const save = async (id: string) => {
    try {
      await apiClient.setSearchProviderKey(id, keyInput.trim())
      setEditingId(null); setKeyInput('')
      setTestMsg({ id: null, ok: true, text: 'API key saved ✓' }); await load(); setTimeout(() => setTestMsg(null), 2500)
    } catch (err: any) { setTestMsg({ id: null, ok: false, text: err?.response?.data?.detail || 'Failed to save' }) }
  }
  const remove = async (id: string) => {
    try { await apiClient.deleteSearchProviderKey(id); setTestMsg({ id: null, ok: true, text: 'API key removed' }); await load(); setTimeout(() => setTestMsg(null), 2500) } catch { /* noop */ }
  }
  const test = async (id: string) => {
    setTestingId(id); setTestMsg(null)
    try {
      const res = await apiClient.testSearchProvider(id)
      setTestMsg({ id, ok: !!res.data?.success, text: res.data?.message || (res.data?.success ? '✓ Connected' : '✗ Failed') })
    } catch { setTestMsg({ id, ok: false, text: '✗ Connection failed' }) } finally { setTestingId(null) }
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12, width: '100%' }}>
      <SectionTitle title={t('settings_search_providers')} desc={t('settings_search_providers_desc')} />
      <ul style={{ listStyle: 'none', margin: 0, padding: 0, display: 'flex', flexDirection: 'column', gap: 8 }}>
        {providers.map(p => (
          <li key={p.id} style={{ border: `1px solid ${tok.borderL2}`, borderRadius: 12, padding: '12px 14px', display: 'flex', alignItems: 'center', gap: 10 }}>
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, minWidth: 0 }}>
              <span style={{ fontSize: 14, lineHeight: '22px', fontWeight: 500, color: tok.labelPrimary }}>{p.name || p.id}</span>
              <Dot state={p.has_key ? 'configured' : 'missing'} />
            </span>
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, marginLeft: 'auto' }}>
              {editingId === p.id ? (
                <>
                  <input
                    type="password" value={keyInput} onChange={e => setKeyInput(e.target.value)} placeholder={t('settings_api_key')} autoFocus
                    style={{ width: 170, boxSizing: 'border-box', height: 28, padding: '0 10px', borderRadius: 14, fontSize: 12, lineHeight: '18px', border: `1px solid ${tok.borderL2}`, background: `var(--color-input-background, ${tok.layer1})`, color: tok.labelPrimary, outline: 'none' }}
                  />
                  <Btn dense variant="primary" onClick={() => save(p.id)}>{t('settings_save')}</Btn>
                  <Btn dense onClick={() => setEditingId(null)}>{t('settings_cancel')}</Btn>
                </>
              ) : (
                <>
                  <Btn dense onClick={() => test(p.id)} disabled={testingId === p.id}>{testingId === p.id ? t('settings_testing') : t('settings_test')}</Btn>
                  <Btn dense onClick={() => { setEditingId(p.id); setKeyInput('') }}>{t('settings_edit')}</Btn>
                  {p.has_key && <Btn dense variant="danger" onClick={() => remove(p.id)}>{t('settings_remove')}</Btn>}
                </>
              )}
            </span>
          </li>
        ))}
        {providers.length === 0 && <li style={{ fontSize: 14, color: tok.labelTertiary }}>{t('settings_no_search_providers')}</li>}
      </ul>
      {testMsg && <div style={{ fontSize: 12, lineHeight: '18px', color: testMsg.ok ? tok.success : tok.error }}>{testMsg.text}</div>}
    </div>
  )
}

// ── Local Models (Ollama / LM Studio / vLLM) ──────────────────────

interface LocalModelRow {
  id: number; name: string; display_name: string; provider: string;
  base_url: string; model_name: string; is_validated: boolean; validation_error?: string | null;
}

function LocalModelsSection() {
  const { t } = useTranslation('chat')
  const [models, setModels] = useState<LocalModelRow[]>([])
  const [adding, setAdding] = useState(false)
  const [editingId, setEditingId] = useState<number | null>(null)
  const [form, setForm] = useState({ name: '', display_name: '', provider: 'ollama', base_url: '', model_name: '', api_key: '' })
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null)
  const [serverModels, setServerModels] = useState<string[]>([])

  const load = useCallback(async () => {
    try { const res = await apiClient.listLocalModels(); setModels(Array.isArray(res.data) ? res.data : []) } catch { /* noop */ }
  }, [])
  useEffect(() => { load() }, [load])

  const set = (k: keyof typeof form) => (v: string) => setForm(f => ({ ...f, [k]: v }))

  const save = async () => {
    if (!form.name.trim() || !form.base_url.trim() || !form.model_name.trim()) {
      setMsg({ ok: false, text: 'name, base URL and model name are required' }); return
    }
    setBusy(true); setMsg(null)
    try {
      if (editingId !== null) {
        await apiClient.updateLocalModel(editingId, {
          display_name: form.display_name, base_url: form.base_url, model_name: form.model_name,
          ...(form.api_key.trim() ? { api_key: form.api_key.trim() } : {}),
        })
      } else {
        await apiClient.createLocalModel({
          name: form.name.trim(), display_name: form.display_name.trim() || form.name.trim(),
          provider: form.provider, base_url: form.base_url.trim(), model_name: form.model_name.trim(),
          ...(form.api_key.trim() ? { api_key: form.api_key.trim() } : {}),
        })
      }
      setAdding(false); setEditingId(null); setForm({ name: '', display_name: '', provider: 'ollama', base_url: '', model_name: '', api_key: '' })
      setMsg({ ok: true, text: 'Saved ✓' }); await load(); setTimeout(() => setMsg(null), 2500)
    } catch (err: any) { setMsg({ ok: false, text: err?.response?.data?.detail || 'Failed to save' }) }
    finally { setBusy(false) }
  }

  const test = async (id: number) => {
    setBusy(true); setMsg(null)
    try {
      const res = await apiClient.validateLocalModel(id)
      setMsg({ ok: !!res.data?.success, text: res.data?.message || (res.data?.success ? '✓ Connected' : '✗ Failed') })
    } catch { setMsg({ ok: false, text: '✗ Connection failed' }) } finally { setBusy(false) }
  }

  /** Fetch the model list from the server (Ollama /models) to fill the dropdown. */
  const loadServerModels = async () => {
    if (!form.base_url.trim()) { setMsg({ ok: false, text: 'Enter a base URL first (e.g. http://localhost:11434/v1)' }); return }
    setBusy(true); setMsg(null)
    try {
      const res = await apiClient.validateLocalConfig(form.base_url.trim(), form.api_key.trim() || undefined)
      const list: string[] = res.data?.models || []
      setServerModels(list)
      if (list.length) {
        setMsg({ ok: true, text: `Found ${list.length} model(s) — pick one below.` })
        // Auto-fill the first model when none chosen yet.
        setForm(f => ({ ...f, model_name: f.model_name || list[0] || '' }))
      } else {
        setMsg({ ok: !!res.data?.success, text: res.data?.message || 'Connected, but no models found.' })
      }
    } catch { setMsg({ ok: false, text: '✗ Could not reach the server' }) } finally { setBusy(false) }
  }

  const remove = async (id: number) => {
    try { await apiClient.deleteLocalModel(id); await load() } catch { /* noop */ }
  }

  const edit = (m: LocalModelRow) => {
    setEditingId(m.id); setAdding(true)
    setForm({ name: m.name, display_name: m.display_name, provider: m.provider, base_url: m.base_url, model_name: m.model_name, api_key: '' })
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12, width: '100%' }}>
      <SectionTitle title={t('settings_local_models')} desc="Local model servers (Ollama, LM Studio, vLLM, LiteLLM)." />
      <ul style={{ listStyle: 'none', margin: 0, padding: 0, display: 'flex', flexDirection: 'column', gap: 8 }}>
        {models.map(m => (
          <li key={m.id} style={{ border: `1px solid ${tok.borderL2}`, borderRadius: 12, padding: '12px 14px', display: 'flex', alignItems: 'center', gap: 10 }}>
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, minWidth: 0 }}>
              <span style={{ fontSize: 14, lineHeight: '22px', fontWeight: 500, color: tok.labelPrimary }}>{m.display_name || m.name}</span>
              <Dot state={m.is_validated ? 'configured' : 'missing'} />
              <span style={{ fontSize: 11, lineHeight: '16px', color: tok.labelTertiary, fontFamily: 'monospace' }}>{m.provider} · {m.model_name}</span>
            </span>
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, marginLeft: 'auto' }}>
              <Btn dense onClick={() => test(m.id)} disabled={busy}>{busy ? t('settings_testing') : t('settings_test')}</Btn>
              <Btn dense onClick={() => edit(m)}>{t('settings_edit')}</Btn>
              <Btn dense variant="danger" onClick={() => remove(m.id)}>{t('settings_remove')}</Btn>
            </span>
          </li>
        ))}
        {models.length === 0 && <li style={{ fontSize: 14, color: tok.labelTertiary }}>No local models yet — add Ollama below.</li>}
      </ul>

      {/* Test result — always visible, even outside the add form */}
      {msg && !adding && (
        <div style={{ fontSize: 12, lineHeight: '18px', color: msg.ok ? tok.success : tok.error, padding: '0 2px' }}>{msg.text}</div>
      )}

      {adding && (
        <div style={{ borderRadius: 12, background: tok.module, padding: '14px 16px', display: 'flex', flexDirection: 'column', gap: 12 }}>
          <div style={{ display: 'flex', gap: 10 }}>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 4, flex: 1 }}>
              <span style={{ fontSize: 12, lineHeight: '18px', fontWeight: 500, color: tok.labelSecondary }}>Name</span>
              <Input value={form.name} onChange={set('name')} placeholder="e.g. ollama-qwen3 (no 'local-' prefix)" mono width="100%" />
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 4, flex: 1 }}>
              <span style={{ fontSize: 12, lineHeight: '18px', fontWeight: 500, color: tok.labelSecondary }}>Provider</span>
              <Select value={form.provider} onChange={v => set('provider')(String(v))} options={[
                { value: 'ollama', label: 'Ollama' }, { value: 'lmstudio', label: 'LM Studio' },
                { value: 'vllm', label: 'vLLM' }, { value: 'litellm', label: 'LiteLLM' }, { value: 'custom', label: 'Custom' },
              ]} />
            </div>
          </div>
          <div style={{ display: 'flex', gap: 10 }}>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 4, flex: 2 }}>
              <span style={{ fontSize: 12, lineHeight: '18px', fontWeight: 500, color: tok.labelSecondary }}>Base URL (ends with /v1)</span>
              <Input value={form.base_url} onChange={set('base_url')} placeholder="http://localhost:11434/v1" mono width="100%" />
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 4, flex: 1 }}>
              <span style={{ fontSize: 12, lineHeight: '18px', fontWeight: 500, color: tok.labelSecondary }}>Model name</span>
              <Select
                value={form.model_name} onChange={v => set('model_name')(String(v))}
                options={serverModels.length
                  ? serverModels.map(m => ({ value: m, label: m }))
                  : (form.model_name ? [{ value: form.model_name, label: form.model_name }] : [{ value: '', label: '(load models →)' }])}
              />
            </div>
          </div>
          <div style={{ display: 'flex', gap: 8 }}>
            <Btn dense onClick={loadServerModels} disabled={busy}>{busy ? t('settings_testing') : 'Load models from server'}</Btn>
            {serverModels.length > 0 && (
              <span style={{ fontSize: 12, lineHeight: '22px', color: tok.labelTertiary }}>{serverModels.length} available</span>
            )}
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            <span style={{ fontSize: 12, lineHeight: '18px', fontWeight: 500, color: tok.labelSecondary }}>API key (optional)</span>
            <Input value={form.api_key} onChange={set('api_key')} placeholder="(leave empty for Ollama)" mono width="100%" />
          </div>
          {msg && <div style={{ fontSize: 12, lineHeight: '18px', color: msg.ok ? tok.success : tok.error }}>{msg.text}</div>}
          <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
            <Btn onClick={() => { setAdding(false); setEditingId(null) }}>{t('settings_cancel')}</Btn>
            <Btn variant="primary" onClick={save} disabled={busy}>{busy ? t('settings_testing') : (editingId !== null ? t('settings_apply') : t('settings_save'))}</Btn>
          </div>
        </div>
      )}

      {!adding && (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10 }}>
          <button type="button" onClick={() => { setAdding(true); setEditingId(null); setForm({ name: '', display_name: '', provider: 'ollama', base_url: 'http://localhost:11434/v1', model_name: '', api_key: '' }) }}
            style={{ flex: '1 1 0', minWidth: 180, gap: 6, height: 44, boxSizing: 'border-box', display: 'inline-flex', alignItems: 'center', justifyContent: 'center', borderRadius: 22, border: `1px dashed ${tok.borderL3}`, background: 'transparent', cursor: 'pointer', color: tok.labelPrimary, fontSize: 14, lineHeight: '22px', fontFamily: 'inherit' }}>
            <span style={{ fontSize: 16 }}>+</span> {t('settings_add_local_model')}
          </button>
        </div>
      )}
    </div>
  )
}

// ── Workspace ─────────────────────────────────────────────────────

function WorkspaceSection() {
  const { t } = useTranslation('chat')
  const [ws, setWs] = useState<any>(null)
  const [path, setPath] = useState('')
  const [saved, setSaved] = useState(false)

  const load = useCallback(async () => {
    try {
      const ns = await describeNs('workspace')
      const value = ns?.value || {}
      setWs(value); setPath(value.workspace_path || '')
    } catch { /* noop */ }
  }, [])
  useEffect(() => { load() }, [load])

  const save = async (patch: Record<string, any>) => {
    setSaved(false)
    try {
      const ok = await mutateNs('workspace', Object.entries(patch).map(([k, v]) => ({ op: 'set', path: [k], value: v })))
      setWs((prev: any) => ({ ...(prev || {}), ...patch }))
      if (!ok) await load()
      setSaved(true); setTimeout(() => setSaved(false), 2000)
    } catch (err: any) { alert(err?.response?.data?.detail || 'Failed to save workspace settings') }
  }
  const setField = (key: string, value: any) => save({ [key]: value })

  return (
    <div style={{ display: 'flex', flexDirection: 'column', width: '100%' }}>
      <SectionTitle title={t('settings_workspace_title')} desc={t('settings_workspace_desc')} />
      <Row label={t('settings_workspace_path')} hint={t('settings_workspace_path_hint')}>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <Input value={path} onChange={setPath} mono placeholder="/path/to/workspace" width={300} />
          <Btn variant="primary" onClick={() => save({ workspace_path: path })}>{saved ? t('settings_saved') : t('settings_save')}</Btn>
        </div>
      </Row>
      <Row label={t('settings_local_workspace_allow_read')} hint={t('settings_local_workspace_allow_read_desc')}><Toggle checked={ws?.allow_read ?? true} onChange={v => setField('allow_read', v)} /></Row>
      <Row label={t('settings_local_workspace_allow_write')} hint={t('settings_local_workspace_allow_write_desc')}><Toggle checked={ws?.allow_write ?? true} onChange={v => setField('allow_write', v)} /></Row>
      <Row label={t('settings_local_workspace_require_approval')} hint={t('settings_local_workspace_require_approval_desc')}><Toggle checked={ws?.require_approval ?? true} onChange={v => setField('require_approval', v)} /></Row>
      <Row label={t('settings_local_workspace_backup')} hint={t('settings_local_workspace_backup_desc')}><Toggle checked={ws?.backup_before_edit ?? true} onChange={v => setField('backup_before_edit', v)} /></Row>
      <Row label={t('settings_local_workspace_auto_detect')} hint={t('settings_local_workspace_auto_detect_desc')}><Toggle checked={ws?.auto_detect_git ?? true} onChange={v => setField('auto_detect_git', v)} /></Row>
    </div>
  )
}

// ── Storage ───────────────────────────────────────────────────────

function StorageSection() {
  const { t } = useTranslation('chat')
  const [mode, setMode] = useState<'local' | 'db'>('local')
  const [source, setSource] = useState<'env' | 'db'>('env')

  useEffect(() => {
    apiClient.getStorageMode().then((res: any) => { setMode(res.data?.mode || 'local'); setSource(res.data?.source || 'env') }).catch(() => {})
  }, [])

  const switchMode = async (next: 'local' | 'db') => { setMode(next); try { await apiClient.updateStorageMode({ mode: next }) } catch { /* noop */ } }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', width: '100%' }}>
      <SectionTitle title={t('settings_storage_title')} desc={t('settings_storage_desc')} />
      <Row label={t('settings_storage_mode')} hint={`Source: ${source === 'db' ? 'persisted (overrides .env)' : '.env / default'}`}>
        <Select value={mode} onChange={v => switchMode(v as 'local' | 'db')} width={280} options={[
          { value: 'local', label: t('settings_local_disk') },
          { value: 'db', label: t('settings_postgres') },
        ]} />
      </Row>
      <p style={{ fontSize: 12, lineHeight: '18px', color: tok.labelTertiary, margin: '8px 0 0' }}>
        {t('settings_storage_note')}
      </p>
    </div>
  )
}

// ── About ─────────────────────────────────────────────────────────

function AboutSection() {
  const { t } = useTranslation('chat')
  return (
    <div style={{ display: 'flex', flexDirection: 'column', width: '100%' }}>
      <SectionTitle title={t('settings_about_title')} desc={t('settings_about_desc')} />
      <Row label={t('settings_version')}><span style={{ fontSize: 14, color: tok.labelTertiary }}>0.1.0</span></Row>
      <Row label={t('settings_configuration')} hint={t('settings_configuration_hint')}>
        <span style={{ fontSize: 14, color: tok.labelTertiary }}>{t('settings_see_env')}</span>
      </Row>
      <Row label={t('settings_first_time_setup')} hint={t('settings_first_time_setup_hint')}>
        <Btn variant="primary" onClick={() => window.dispatchEvent(new CustomEvent('setup:open'))}>{t('settings_rerun_setup')}</Btn>
      </Row>
    </div>
  )
}
