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
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useLocation } from 'react-router-dom'
import { themes, useTheme, type ThemeName } from '../lib/themes'
import apiClient from '../lib/api-client'
import LegacyMigrationPanel from '../components/layout2/LegacyMigrationPanel'
import KnowledgeIndexPanel from '../components/layout2/KnowledgeIndexPanel'
import ImportFolderPanel from '../components/layout2/ImportFolderPanel'
import DocChatSettingsPanel from '../components/layout2/DocChatSettingsPanel'
import { useProject } from '../contexts/ProjectContext'

type SectionId = 'general' | 'models' | 'ontology' | 'apply' | 'databases' | 'webapi' | 'localmodels' | 'workspace' | 'storage' | 'runtime' | 'agents' | 'knowledge' | 'about'

const SECTIONS: { id: SectionId; labelKey: string; icon: string }[] = [
  { id: 'general', labelKey: 'settings_general', icon: 'tune' },
  { id: 'models', labelKey: 'settings_models', icon: 'smart_toy' },
  // Which databases the SQL tools may point at (admin-only).
  // Which ontology workbench profiles this account can open (the Ontology activity's list).
  { id: 'ontology', labelKey: 'Ontology', icon: 'account_tree' },
  // The publish channel's human half: what an agent staged, and the one click that installs it.
  // It is its own section because applying is a decision about what a NUMBER MEANS for everyone —
  // it deserves a page, not a panel three scrolls down inside another page.
  { id: 'apply', labelKey: 'Apply', icon: 'publish' },
  { id: 'databases', labelKey: 'settings_databases', icon: 'database' },
  { id: 'webapi', labelKey: 'settings_search_providers', icon: 'travel_explore' },
  { id: 'localmodels', labelKey: 'settings_local_models', icon: 'terminal' },
  { id: 'workspace', labelKey: 'settings_workspace', icon: 'folder_open' },
  { id: 'storage', labelKey: 'settings_storage', icon: 'storage' },
  { id: 'runtime', labelKey: 'settings_section_runtime', icon: 'tune' },
  { id: 'agents', labelKey: 'settings_agents', icon: 'rule' },
  { id: 'knowledge', labelKey: 'settings_knowledge', icon: 'sync_alt' },
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
//
// This is only a FALLBACK. The authoritative list is the seeded
// `search_providers` table (`api_key_field` / `requires_api_key`), which travels
// with the seed: hardcoding it here meant exa / brave / serpapi — all seeded as
// web APIs — were classified as LLM providers and their keys rendered in the
// wrong section.
const WEB_API_PROVIDERS_FALLBACK = new Set(['tavily', 'serper'])

// ONE naming rule per provider: <provider>_api_key + <provider>_base_url.
// The backend (backend/config.py `_db_api_base`) reads <provider>_base_url first and
// still accepts the legacy <provider>_api_base, so rows written before this rename
// keep working — but everything written from here on uses the single name.
const PROVIDER_BASE_FIELD: Record<string, string> = {
  openai: 'openai_base_url', anthropic: 'anthropic_base_url', google: 'google_base_url',
  cohere: 'cohere_base_url', replicate: 'replicate_base_url', deepseek: 'deepseek_base_url',
  glm: 'glm_base_url', minimax: 'minimax_base_url', qwen: 'qwen_base_url', kimi: 'kimi_base_url',
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
  /**
   * `source` says who set each secret: `own` (this account), `shared` (inherited
   * from the team layer) or `unset`. Without it a key the whole install spends
   * renders identically to one this account configured.
   */
  secrets: { path: string[]; set: boolean; source?: 'own' | 'shared' | 'unset' }[]
}

type MutateOp = { op: 'set' | 'unset'; path: string[]; value?: any }

/** The Admin-only "team sharing" switches live on the owner's row.
 *
 * Only the owner's flags have an effect (everyone else inherits *from* the owner),
 * so rendering them for a member would offer a control that silently does
 * nothing. The role comes from /api/users/me rather than being inferred.
 */
async function currentUserIsAdmin(): Promise<boolean> {
  try {
    const res = await apiClient.getMe()
    return (res?.data?.role || '') === 'admin'
  } catch {
    return false
  }
}

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

function Dot({ state }: { state: 'configured' | 'missing' | 'invalid' }) {
  // 'configured' only means "a value is stored". It says nothing about whether
  // that value works — a bogus key showed a green dot while every agent failed.
  const [title, colour] = state === 'invalid'
    ? ['Key rejected by the provider — click Test', tok.error]
    : state === 'configured'
      ? ['Key stored (not verified — click Test)', tok.success]
      : ['Missing key', tok.error]
  return (
    <span role="img" title={title}
      style={{ display: 'inline-block', width: 8, height: 8, borderRadius: '50%', flex: 'none', background: colour }}
    />
  )
}

// ── The modal shell ───────────────────────────────────────────────

export default function SettingsModal({ onClose }: { onClose: () => void }) {
  const { i18n, t } = useTranslation('chat')
  const { theme: activeTheme, setTheme } = useTheme()
  // The section is a place, so it can be LINKED: `/settings?section=ontology` opens on the ontology
  // section, whose first control is the surface that applies a staged publish. Without this the gear
  // in the ontology browser landed on General and the pending publishes sat behind a click nobody made.
  //
  // Read in an EFFECT rather than in the initialiser: the modal is mounted by the route, and a mount
  // initialiser only sees the URL of the render that happened to mount it — the very bug being fixed,
  // one layer down. The effect follows every navigation, so the deep link wins whenever it changes.
  const KNOWN_SECTIONS: SectionId[] = ['general', 'models', 'ontology', 'apply', 'databases', 'webapi', 'localmodels', 'workspace', 'storage', 'runtime', 'agents', 'knowledge', 'about']
  const askedSection = (raw: string | null | undefined): SectionId | null =>
    (KNOWN_SECTIONS as string[]).includes(raw || '') ? (raw as SectionId) : null
  // THIS APP IS A HashRouter: the address is `/#/settings?section=apply`, so the query lives in the
  // HASH and `window.location.search` is always empty. Reading it there made every deep link land on
  // General — the fix was invisible for exactly the reason the bug was. `useLocation` knows both.
  const route = useLocation()
  const [section, setSection] = useState<SectionId>(
    () => askedSection(new URLSearchParams(route.search).get('section')) || 'general',
  )
  useEffect(() => {
    // Both ways in: the route (`/#/settings?section=apply`) and the `settings:open` event an opener
    // may fire with a section. The route wins when it names one, because a link is a promise.
    const fromRoute = askedSection(new URLSearchParams(route.search).get('section'))
    if (fromRoute) setSection(fromRoute)
  }, [route.search])
  useEffect(() => {
    const fromEvent = (e: Event) => {
      // An opener may name the section; if it does not, an ontology screen still means Apply —
      // that is the settings surface those screens exist to reach. Reading the HASH here (not
      // `location.search`) is the whole lesson of this file: the app is a HashRouter.
      const hashPath = window.location.hash.replace(/^#/, '').split('?')[0] || '/'
      const want = askedSection((e as CustomEvent<{ section?: string }>).detail?.section)
        || (hashPath.startsWith('/ontology') || hashPath.startsWith('/workbench') ? 'apply' as SectionId : null)
      if (want) setSection(want)
    }
    window.addEventListener('settings:open', fromEvent)
    return () => window.removeEventListener('settings:open', fromEvent)
  }, [])

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
          // The databases section is a 7-column table: at 800px it scrolled
          // sideways and only a couple of rows fit. Give that one section a
          // roomier shell (8 rows on screen, no horizontal scroll).
          width: section === 'databases' || section === 'ontology' ? 1080 : 800,
          height: section === 'databases' ? 'min(880px, calc(100vh - 48px))' : 'min(800px, calc(100vh - 48px))',
          maxWidth: 'calc(100vw - 48px)',
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
            {/* Which section this panel is showing, named. A deep link that silently loses its
                section is indistinguishable from a working one until you can read the answer. */}
            <span data-settings-section={section}
                  style={{ marginRight: 'auto', fontSize: 12, color: tok.labelTertiary, lineHeight: '28px' }}>
              {t('settings_title')} · {section === 'apply' ? 'Apply' : t(SECTIONS.find(x => x.id === section)?.labelKey || '')}
            </span>
            <button
              type="button" onClick={onClose}
              style={{ display: 'inline-flex', alignItems: 'center', justifyContent: 'center', width: 28, height: 28, padding: 0, border: 'none', borderRadius: '50%', background: 'transparent', cursor: 'pointer', color: tok.labelPrimary, fontSize: 14 }}
              onMouseEnter={e => { e.currentTarget.style.background = tok.hover }}
              onMouseLeave={e => { e.currentTarget.style.background = 'transparent' }}
              title={t('close')}
            >✕</button>
          </div>
          <div style={{ flex: 1, minHeight: 0, padding: '0 24px 24px', overflowY: 'auto' }}>
            <div style={{ maxWidth: section === 'databases' || section === 'ontology' ? 1080 : 720 }}>
              {section === 'general' && <GeneralSection i18n={i18n} activeTheme={activeTheme.name} setTheme={setTheme} />}
              {section === 'models' && <ModelsSection />}
              {section === 'ontology' && <OntologySection />}
              {section === 'apply' && <ApplySection />}
              {section === 'databases' && <DatabasesSection />}
              {section === 'webapi' && <SearchSection />}
              {section === 'localmodels' && <LocalModelsSection />}
              {section === 'workspace' && <WorkspaceSection />}
              {section === 'storage' && <StorageSection />}
              {section === 'runtime' && <RuntimeSection />}
              {section === 'agents' && <AgentsSection />}
              {section === 'knowledge' && <KnowledgeSection />}
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
    if (!ok) {
      await load()  // conflict/error — re-read the server truth
      return
    }
    // Notify other in-app listeners (useDisplayMode, etc.) so they
    // refetch and pick up the change without requiring a page reload.
    window.dispatchEvent(new CustomEvent('settings:updated', {
      detail: { ns: 'general', patch },
    }))
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
      <Row label={t('settings_display_mode')} hint={t('settings_display_mode_hint')}>
        <Select
          value={gen?.display_mode ?? 'verbose'}
          onChange={v => update({ display_mode: v })}
          options={[
            { value: 'verbose', label: t('settings_display_mode_verbose') },
            { value: 'direct',  label: t('settings_display_mode_direct') },
          ]}
        />
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
  const [keys, setKeys] = useState<{ provider: string; is_set: boolean; source?: 'own' | 'shared' | 'unset' }[]>([])
  // api_key_field -> source, shared with the Web API section below.
  const [secretSources, setSecretSources] = useState<Record<string, 'own' | 'shared' | 'unset'>>({})
  const [models, setModels] = useState<{ cloud: ModelInfo[]; local: ModelInfo[] }>({ cloud: [], local: [] })
  const [defaults, setDefaults] = useState<any>({ default_model: '', fallback_models: [], temperature: 0, max_tokens: 0 })
  const [editing, setEditing] = useState<string | null>(null)
  const [adding, setAdding] = useState(false)
  const [keyInput, setKeyInput] = useState('')
  const [baseUrl, setBaseUrl] = useState('')
  const [newProviderName, setNewProviderName] = useState('')
  const [testingProvider, setTestingProvider] = useState<string | null>(null)
  // Keyed by provider: one shared message meant a result could appear under a
  // different row than the one you tested.
  const [testMsg, setTestMsg] = useState<Record<string, { ok: boolean; msg: string } | undefined>>({})
  // Team sharing (owner only): whether this account's model/web keys are the
  // install-wide default for accounts that have none of their own.
  const [isAdmin, setIsAdmin] = useState(false)
  const [shareModel, setShareModel] = useState(true)
  const [shareWeb, setShareWeb] = useState(true)

  const setSharing = useCallback(async (field: 'share_model_keys_with_team' | 'share_web_keys_with_team', value: boolean) => {
    if (field === 'share_model_keys_with_team') setShareModel(value); else setShareWeb(value)
    const ok = await mutateNs('models', [{ op: 'set', path: [field], value }])
    if (!ok) { // server refused → re-read the truth instead of lying in the UI
      const ns = await describeNs('models')
      setShareModel(ns?.value?.share_model_keys_with_team !== false)
      setShareWeb(ns?.value?.share_web_keys_with_team !== false)
    }
  }, [])

  const load = useCallback(async () => {
    try {
      const [descRes, modelsRes, spRes] = await Promise.all([
        apiClient.describeSettings(), apiClient.listAvailableModels(),
        // Metadata only (field names / flags), never key values.
        apiClient.listSearchProviders().catch(() => null),
      ])
      const webApi = new Set<string>(WEB_API_PROVIDERS_FALLBACK)
      // Fields that belong to the Web API section. Tracked by FIELD, not by provider
      // id: one credential can serve both sections. `deepseek_api_key` runs the LLM
      // *and* the DeepSeek Search API, so excluding by id removed DeepSeek from this
      // list entirely — the provider disappeared from Models the moment a
      // search_providers row for it was seeded.
      const webApiFields = new Set<string>()
      const spRows = (spRes as any)?.data?.providers
      if (Array.isArray(spRows)) {
        webApi.clear()
        for (const row of spRows) {
          const field: string | undefined = row?.api_key_field
          if (field) {
            webApi.add(String(row.id))                   // tavily -> tavily_api_key
            webApiFields.add(String(field))
          }
        }
      }
      // An LLM provider keeps its row here even when a search provider names the
      // same key: it is shown in both sections, pointing at one stored credential.
      const llmFields = new Set(Object.values(PROVIDER_FIELD))
      const ns: SettingsNs | undefined = (descRes.data?.namespaces || []).find((n: any) => n.ns === 'models')
      const value = ns?.value || {}
      // Provider rows derive from the redacted secret positions (DSH dots):
      // models.api_keys.* fields, no values ever cross the wire. Providers the
      // seeded search_providers table marks as needing a key are excluded here —
      // they live in the dedicated "Web API" settings section.
      const allSecrets = (ns?.secrets || []).filter(s => s.path[0] === 'api_keys')
      setSecretSources(Object.fromEntries(allSecrets.map(s => [s.path[1], s.source || (s.set ? 'own' : 'unset')])))
      const providers = allSecrets
        .map(s => ({ provider: s.path[1].replace(/_api_key$/, ''), is_set: s.set, source: s.source }))
        .filter(p => {
          const field = `${p.provider}_api_key`
          return !webApiFields.has(field) || llmFields.has(field)
        })
      setKeys(providers)
      setShareModel(value.share_model_keys_with_team !== false)
      setShareWeb(value.share_web_keys_with_team !== false)
      setDefaults({
        default_model: value.default_model || '',
        fallback_models: value.fallback_models || [],
        temperature: value.default_temperature ?? 0,
        max_tokens: value.max_tokens ?? 0,
      })
      setModels({ cloud: modelsRes.data?.cloud_models || [], local: modelsRes.data?.local_models || [] })
    } catch (err) { console.error('Failed to load models settings:', err) }
  }, [])
  useEffect(() => { load(); currentUserIsAdmin().then(setIsAdmin) }, [load])

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
      const saved = keyInput.trim()
      await saveKey(provider, keyInput, baseUrl)
      setEditing(null); setKeyInput(''); setBaseUrl('')
      await load()
      // Confirm it round-tripped: the row now reads the stored value, so a later
      // Test cannot silently validate a draft that never persisted.
      if (saved) setTestMsg(prev => ({ ...prev, [provider]: { ok: true, msg: 'Saved — Test now checks the stored key' } }))
    } catch (err: any) {
      setTestMsg(prev => ({ ...prev, [provider]: { ok: false, msg: err?.response?.data?.detail || 'Failed to save — the key was NOT stored' } }))
    }
  }

  const handleTest = async (provider: string) => {
    setTestingProvider(provider)
    try {
      // Test the draft ONLY for the row that is actually open. `keyInput` is a
      // single shared field, so sending it unconditionally meant the Test button
      // on any row validated whichever key happened to be typed into another
      // row's editor.
      const draft = editing === provider ? keyInput.trim() : ''
      const res = await apiClient.testApiKey(provider, draft || undefined)
      const ok = !!res.data?.success
      const base = res.data?.message || (ok ? '✓ Connected' : '✗ Failed')
      // Say WHICH key was tested. A green result for an unsaved draft used to
      // look identical to a green result for the stored key — so the model
      // looked configured, while every agent still failed on a missing key.
      setTestMsg(prev => ({
        ...prev,
        [provider]: { ok, msg: draft ? `${base} · draft key, not saved yet — click Save` : `${base} · saved key` },
      }))
    } catch (err: any) {
      const msg = err?.response?.data?.detail || err?.message || '✗ Connection failed'
      setTestMsg(prev => ({ ...prev, [provider]: { ok: false, msg } }))
    } finally { setTestingProvider(null) }
  }

  const handleAddProvider = async () => {
    const name = newProviderName.trim().toLowerCase()
    if (!name) return
    const field = PROVIDER_FIELD[name]
    if (!field) { setTestMsg(prev => ({ ...prev, __add__: { ok: false, msg: t('settings_unknown_provider', { name, list: Object.keys(PROVIDER_FIELD).join(', ') }) } })); return }
    try {
      await saveKey(name, keyInput, baseUrl)
      setAdding(false); setNewProviderName(''); setKeyInput(''); setBaseUrl(''); setTestMsg({})
      await load()
    } catch (err: any) { setTestMsg(prev => ({ ...prev, __add__: { ok: false, msg: err?.response?.data?.detail || 'Failed' } })) }
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12, width: '100%' }}>
      <SectionTitle title={t('settings_models_title')} desc={t('settings_models_desc')} />

      {/* Default model rows */}
      <Row label={t('settings_default_model')} hint={t('settings_default_model_hint')}>
        <Select
          value={defaults.default_model || ''} width={280}
          onChange={v => updateDefault({ default_model: v })}
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

      {/* Team sharing — the owner's row is the team's default. Admin-only: the flag
          only has an effect on that row, so offering it to a member would be a
          control that silently does nothing. */}
      {isAdmin && (
        <div style={{ border: `1px solid ${tok.borderL2}`, borderRadius: 12, padding: '12px 14px', display: 'flex', alignItems: 'flex-start', gap: 12 }}>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontSize: 14, lineHeight: '22px', fontWeight: 500, color: tok.labelPrimary }}>{t('settings_team_share_models')}</div>
            <div style={{ fontSize: 12, lineHeight: '18px', color: tok.labelTertiary }}>{t('settings_team_share_models_desc')}</div>
          </div>
          <Toggle checked={shareModel} onChange={v => setSharing('share_model_keys_with_team', v)} />
        </div>
      )}

      {/* Provider rows (outlined cards + credential dot) */}
      <ul style={{ listStyle: 'none', margin: 0, padding: 0, display: 'flex', flexDirection: 'column', gap: 8 }}>
        {keys.length === 0 && <li style={{ fontSize: 14, color: tok.labelTertiary, padding: '8px 0' }}>{t('settings_loading_providers')}</li>}
        {keys.map(k => (
          <li key={k.provider} style={{ border: `1px solid ${tok.borderL2}`, borderRadius: 12, padding: '12px 14px', display: 'flex', flexDirection: 'column', gap: 12 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, minWidth: 0 }}>
                <span style={{ fontSize: 14, lineHeight: '22px', fontWeight: 500, color: tok.labelPrimary }}>{label(k.provider)}</span>
                <Dot state={
                  // a rejected key outranks "stored": the dot must not stay green
                  // after a test proved the value does not work
                  testMsg[k.provider]?.ok === false ? 'invalid'
                    : k.is_set ? 'configured' : 'missing'
                } />
                {k.is_set && k.source === 'shared' && (
                  <span
                    title="This key comes from the team (shared) settings. Saving your own key here overrides it for your account only."
                    style={{
                      fontSize: 11, lineHeight: '16px', padding: '1px 7px', borderRadius: 9,
                      border: `1px solid ${tok.borderL2}`, color: tok.labelTertiary,
                      whiteSpace: 'nowrap',
                    }}
                  >
                    {t('settings_key_shared')}
                  </span>
                )}
              </span>
              <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4, marginLeft: 'auto' }}>
                <Btn dense onClick={() => handleTest(k.provider)} disabled={testingProvider === k.provider}>
                  {testingProvider === k.provider ? t('settings_testing') : t('settings_test')}
                </Btn>
                <Btn dense onClick={() => { setEditing(k.provider); setKeyInput(''); setBaseUrl(''); setTestMsg(prev => ({ ...prev, [k.provider]: undefined })) }}>{t('settings_edit')}</Btn>
              </span>
            </div>
            {/* Result of THIS row's Test, visible without opening the editor —
                it used to render only inside the collapsed edit panel, so a
                click on the outer Test button produced no visible feedback and
                the only thing on screen was the "configured" dot. */}
            {testMsg[k.provider] && (
              <div style={{ fontSize: 12, lineHeight: '18px', color: testMsg[k.provider]!.ok ? tok.success : tok.error }}>
                {testMsg[k.provider]!.msg}
              </div>
            )}
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
            <span style={{ fontSize: 12, lineHeight: '18px', fontWeight: 500, color: tok.labelSecondary }}>{t('settings_api_key')}</span>
            <Input value={keyInput} onChange={setKeyInput} placeholder="sk-…" mono width="100%" />
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            <span style={{ fontSize: 12, lineHeight: '18px', fontWeight: 500, color: tok.labelSecondary }}>{t('settings_base_url_optional')}</span>
            <Input value={baseUrl} onChange={setBaseUrl} placeholder="https://api.example.com" mono width="100%" />
          </div>
          {testMsg.__add__ && <div style={{ fontSize: 12, lineHeight: '18px', color: testMsg.__add__.ok ? tok.success : tok.error }}>{testMsg.__add__.msg}</div>}
          <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
            <Btn onClick={() => setAdding(false)}>{t('settings_cancel')}</Btn>
            <Btn variant="primary" onClick={handleAddProvider}>{t('settings_save')}</Btn>
          </div>
        </div>
      ) : (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10 }}>
          <button
            type="button" onClick={() => { setAdding(true); setKeyInput(''); setBaseUrl(''); setNewProviderName(''); setTestMsg(prev => ({ ...prev, __add__: undefined })) }}
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
  // api_key_field -> own/shared/unset, so an inherited search key is labelled
  // instead of looking like one this account configured.
  const [secretSources, setSecretSources] = useState<Record<string, 'own' | 'shared' | 'unset'>>({})
  // Same team-sharing switch as the Models section, but scoped to this group:
  // search keys are billed per query and are often a personal free tier.
  const [isAdmin, setIsAdmin] = useState(false)
  const [shareWeb, setShareWeb] = useState(true)

  const setSharing = async (value: boolean) => {
    setShareWeb(value)
    const ok = await mutateNs('models', [{ op: 'set', path: ['share_web_keys_with_team'], value }])
    if (!ok) {
      const ns = await describeNs('models')
      setShareWeb(ns?.value?.share_web_keys_with_team !== false)
    }
  }

  const load = useCallback(async () => {
    try { const res = await apiClient.listSearchProviders(); setProviders(res.data?.providers || []) } catch { /* noop */ }
    try {
      const ns = await describeNs('models')
      const map: Record<string, 'own' | 'shared' | 'unset'> = {}
      for (const sec of ns?.secrets || []) {
        if (sec.path[0] === 'api_keys') map[sec.path[1]] = sec.source || (sec.set ? 'own' : 'unset')
      }
      setSecretSources(map)
      setShareWeb(ns?.value?.share_web_keys_with_team !== false)
    } catch { /* labelling is best-effort */ }
  }, [])
  useEffect(() => { load(); currentUserIsAdmin().then(setIsAdmin) }, [load])

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

      {isAdmin && (
        <div style={{ border: `1px solid ${tok.borderL2}`, borderRadius: 12, padding: '12px 14px', display: 'flex', alignItems: 'flex-start', gap: 12 }}>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontSize: 14, lineHeight: '22px', fontWeight: 500, color: tok.labelPrimary }}>{t('settings_team_share_web')}</div>
            <div style={{ fontSize: 12, lineHeight: '18px', color: tok.labelTertiary }}>{t('settings_team_share_web_desc')}</div>
          </div>
          <Toggle checked={shareWeb} onChange={v => setSharing(v)} />
        </div>
      )}

      <ul style={{ listStyle: 'none', margin: 0, padding: 0, display: 'flex', flexDirection: 'column', gap: 8 }}>
        {providers.map(p => (
          <li key={p.id} style={{ border: `1px solid ${tok.borderL2}`, borderRadius: 12, padding: '12px 14px', display: 'flex', alignItems: 'center', gap: 10 }}>
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, minWidth: 0 }}>
              <span style={{ fontSize: 14, lineHeight: '22px', fontWeight: 500, color: tok.labelPrimary }}>{p.name || p.id}</span>
              <Dot state={p.has_key ? 'configured' : 'missing'} />
              {p.has_key && p.api_key_field && secretSources[p.api_key_field] === 'shared' && (
                <span
                  title="This key comes from the team (shared) settings. Saving your own key here overrides it for your account only."
                  style={{
                    fontSize: 11, lineHeight: '16px', padding: '1px 7px', borderRadius: 9,
                    border: `1px solid ${tok.borderL2}`, color: tok.labelTertiary,
                    whiteSpace: 'nowrap',
                  }}
                >
                  {t('settings_key_shared')}
                </span>
              )}
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
  // Per-row test state: only the row being tested shows the spinner and its
  // own result — other rows stay interactive.
  const [testingId, setTestingId] = useState<number | null>(null)
  const [rowMsg, setRowMsg] = useState<{ id: number; ok: boolean; text: string } | null>(null)

  const load = useCallback(async () => {
    try { const res = await apiClient.listLocalModels(); setModels(Array.isArray(res.data) ? res.data : []) } catch { /* noop */ }
  }, [])
  useEffect(() => { load() }, [load])

  const set = (k: keyof typeof form) => (v: string) => setForm(f => ({ ...f, [k]: v }))

  // Per-provider default base URL, applied when the provider changes so the
  // model dropdown can be loaded automatically.
  const PROVIDER_DEFAULT_URL: Record<string, string> = {
    ollama: 'http://localhost:11434/v1',
    lmstudio: 'http://localhost:1234/v1',
    vllm: 'http://localhost:8000/v1',
    litellm: 'http://localhost:4000/v1',
    custom: '',
  }

  const changeProvider = async (p: string, explicitBaseUrl?: string) => {
    const url = explicitBaseUrl || PROVIDER_DEFAULT_URL[p] || ''
    setForm(f => ({ ...f, provider: p, base_url: url, model_name: '' }))
    setServerModels([])
    if (url) {
      // Auto-load the model list for the provider's base URL.
      setBusy(true); setMsg(null)
      try {
        const res = await apiClient.validateLocalConfig(url)
        const list: string[] = res.data?.models || []
        setServerModels(list)
        if (list.length) {
          setForm(f => ({ ...f, model_name: f.model_name || list[0] || '' }))
          setMsg({ ok: true, text: `Found ${list.length} model(s) on ${p}.` })
        } else {
          setMsg({ ok: !!res.data?.success, text: res.data?.message || 'Connected, but no models found.' })
        }
      } catch { setMsg({ ok: false, text: '✗ Could not reach the server' }) } finally { setBusy(false) }
    }
  }

  const save = async () => {
    // Auto-generate the name from provider + model when the user left it
    // blank. Dots are KEPT (model ids like qwen3.6 legitimately contain
    // them — the backend allows them); only the model-id separator (':')
    // is mapped to '-'. e.g. 'ollama' + 'qwen3.6:27b' -> 'ollama-qwen3.6-27b'.
    let name = form.name.trim()
    if (!name && form.model_name.trim()) {
      name = `${form.provider}-${form.model_name.trim().replace(/[^a-zA-Z0-9_.-]/g, '-')}`
      setForm(f => ({ ...f, name }))
    }
    if (!name || !form.base_url.trim() || !form.model_name.trim()) {
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
          name, display_name: form.display_name.trim() || name,
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
    setTestingId(id); setRowMsg(null)
    try {
      // Real LLM call to the SPECIFIC model (like the SaaS provider test).
      const res = await apiClient.testLocalModel(id)
      const d = res.data || {}
      setRowMsg({ id, ok: !!d.success, text: d.success ? `✓ ${d.message} → "${d.response}"` : `✗ ${d.message}` })
    } catch { setRowMsg({ id, ok: false, text: '✗ Connection failed' }) } finally { setTestingId(null) }
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
      <SectionTitle title={t('settings_local_models')} desc={t('settings_local_models_desc')} />
      <ul style={{ listStyle: 'none', margin: 0, padding: 0, display: 'flex', flexDirection: 'column', gap: 8 }}>
        {models.map(m => (
          <li key={m.id} style={{ border: `1px solid ${tok.borderL2}`, borderRadius: 12, padding: '12px 14px', display: 'flex', flexDirection: 'column', gap: 8 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, minWidth: 0 }}>
                <span style={{ fontSize: 14, lineHeight: '22px', fontWeight: 500, color: tok.labelPrimary }}>{m.display_name || m.name}</span>
                <Dot state={m.is_validated ? 'configured' : 'missing'} />
                <span style={{ fontSize: 11, lineHeight: '16px', color: tok.labelTertiary, fontFamily: 'monospace' }}>{m.provider} · {m.model_name}</span>
              </span>
              <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, marginLeft: 'auto' }}>
                <Btn dense onClick={() => test(m.id)} disabled={testingId === m.id}>{testingId === m.id ? t('settings_testing') : t('settings_test')}</Btn>
                <Btn dense onClick={() => edit(m)}>{t('settings_edit')}</Btn>
                <Btn dense variant="danger" onClick={() => remove(m.id)}>{t('settings_remove')}</Btn>
              </span>
            </div>
            {rowMsg && rowMsg.id === m.id && (
              <div style={{ fontSize: 12, lineHeight: '18px', color: rowMsg.ok ? tok.success : tok.error }}>{rowMsg.text}</div>
            )}
          </li>
        ))}
        {models.length === 0 && <li style={{ fontSize: 14, color: tok.labelTertiary }}>{t('settings_local_models_empty')}</li>}
      </ul>

      {adding && (
        <div style={{ borderRadius: 12, background: tok.module, padding: '14px 16px', display: 'flex', flexDirection: 'column', gap: 12 }}>
          <div style={{ display: 'flex', gap: 10 }}>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 4, flex: 1 }}>
              <span style={{ fontSize: 12, lineHeight: '18px', fontWeight: 500, color: tok.labelSecondary }}>Name</span>
              <Input value={form.name} onChange={set('name')} placeholder="e.g. ollama-qwen3 (no 'local-' prefix)" mono width="100%" />
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 4, flex: 1 }}>
              <span style={{ fontSize: 12, lineHeight: '18px', fontWeight: 500, color: tok.labelSecondary }}>{t('settings_local_provider')}</span>
              <Select value={form.provider} onChange={v => changeProvider(String(v), form.base_url || undefined)} options={[
                { value: 'ollama', label: 'Ollama' }, { value: 'lmstudio', label: 'LM Studio' },
                { value: 'vllm', label: 'vLLM' }, { value: 'litellm', label: 'LiteLLM' }, { value: 'custom', label: 'Custom' },
              ]} />
            </div>
          </div>
          <div style={{ display: 'flex', gap: 10 }}>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 4, flex: 2 }}>
              <span style={{ fontSize: 12, lineHeight: '18px', fontWeight: 500, color: tok.labelSecondary }}>{t('settings_local_base_url')}</span>
              <Input value={form.base_url} onChange={set('base_url')} placeholder="http://localhost:11434/v1" mono width="100%" />
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 4, flex: 1 }}>
              <span style={{ fontSize: 12, lineHeight: '18px', fontWeight: 500, color: tok.labelSecondary }}>{t('settings_local_model_name')}</span>
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
            <span style={{ fontSize: 12, lineHeight: '18px', fontWeight: 500, color: tok.labelSecondary }}>{t('settings_local_api_key_optional')}</span>
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
          <button type="button" onClick={() => { setAdding(true); setEditingId(null); setForm({ name: '', display_name: '', provider: 'ollama', base_url: 'http://localhost:11434/v1', model_name: '', api_key: '' }); changeProvider('ollama', 'http://localhost:11434/v1') }}
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
  const { activeProjectId, projects, setActiveProjectId, refreshProjects } = useProject()
  const [ws, setWs] = useState<any>(null)
  const [path, setPath] = useState('')
  const [maxIter, setMaxIter] = useState('')
  const [saved, setSaved] = useState(false)

  const load = useCallback(async () => {
    try {
      const ns = await describeNs('workspace')
      const value = ns?.value || {}
      setWs(value); setPath(value.workspace_path || '')
      setMaxIter(value.agent_max_iterations ? String(value.agent_max_iterations) : '')
    } catch { /* noop */ }
  }, [])
  useEffect(() => { load() }, [load])

  // The vault list can go stale when a project was created outside this modal
  // (vault popover, API/CLI), so re-read it when the section mounts. Guarded by
  // a ref: `refreshProjects` is not memoized in ProjectContext, and calling it
  // from a dep-driven effect would loop (setProjects → new identity → effect).
  const refreshedRef = useRef(false)
  useEffect(() => {
    if (refreshedRef.current) return
    refreshedRef.current = true
    void refreshProjects()
  }, [refreshProjects])

  // Dropdown options for the vault switch. A leading "(none)" entry covers a
  // stale/cleared activeProjectId so the <select> never falls back silently to
  // the first project.
  const projectOptions = useMemo(() => {
    const opts = projects.map(p => ({
      value: String(p.id),
      label: `${p.name} (#${p.id})`,
      key: String(p.id),
    }))
    if (!projects.some(p => p.id === activeProjectId)) {
      opts.unshift({ value: '', label: t('settings_current_project_none'), key: '__none' })
    }
    return opts
  }, [projects, activeProjectId, t])

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
      {/* Vault switch — the project picked here scopes new chat sessions and
          every agent workspace (outputs/<vault-slug>/agents/<agent>), so it is
          the same selection as the ActivityBar vault popover. */}
      <Row label={t('settings_current_project')} hint={t('settings_current_project_hint')}>
        <Select
          value={activeProjectId != null ? String(activeProjectId) : ''}
          onChange={v => {
            const id = parseInt(v, 10)
            if (Number.isFinite(id) && id > 0) setActiveProjectId(id)
          }}
          options={projectOptions}
          width={240}
        />
      </Row>
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
      <Row label={t('settings_agent_max_iterations')} hint={t('settings_agent_max_iterations_hint')}>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <Input value={maxIter} onChange={v => setMaxIter(v.replace(/\D/g, ''))} type="number" placeholder="1000" width={120} />
          <Btn variant="primary" onClick={() => { const n = parseInt(maxIter, 10); if (Number.isFinite(n) && n > 0) save({ agent_max_iterations: n }) }}>{saved ? t('settings_saved') : t('settings_save')}</Btn>
        </div>
      </Row>
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

// ── Runtime ────────────────────────────────────────────────────────

function RuntimeSection() {
  const { t } = useTranslation('chat')
  const [rt, setRt] = useState<any>(null)

  const load = useCallback(async () => {
    try { const ns = await describeNs('runtime'); setRt(ns?.value || {}) } catch { /* noop */ }
  }, [])
  useEffect(() => { load() }, [load])

  const update = async (patch: Record<string, any>) => {
    setRt((prev: any) => ({ ...(prev || {}), ...patch }))
    const ok = await mutateNs('runtime', Object.entries(patch).map(([k, v]) => ({ op: 'set', path: [k], value: v })))
    if (!ok) await load()
  }

  // Save helpers that also strip non-numeric chars for number inputs.
  const numField = (key: string, width = 110) => ({
    value: rt?.[key] != null ? String(rt[key]) : '',
    onChange: (v: string) => update({ [key]: parseInt(v.replace(/\D/g, ''), 10) || 0 }),
    type: 'number',
    width,
  })

  return (
    <div style={{ display: 'flex', flexDirection: 'column', width: '100%' }}>
      <SectionTitle title={t('settings_runtime_title')} desc={t('settings_runtime_desc')} />

      {/* Workspace / backups */}
      <Row label={t('settings_runtime_langconfig_workspace_root')}
           hint={t('settings_runtime_value_unchanged')}>
        <Input value={rt?.langconfig_workspace_root ?? ''}
               onChange={v => update({ langconfig_workspace_root: v })}
               width={300} />
      </Row>
      <Row label={t('settings_runtime_backup_dir')}
           hint={t('settings_runtime_value_unchanged')}>
        <Input value={rt?.backup_dir ?? ''}
               onChange={v => update({ backup_dir: v })}
               width={300} />
      </Row>

      {/* Storage (display only; editable under storage_mode endpoint) */}
      <Row label={t('settings_storage_mode')}
           hint={t('settings_runtime_value_unchanged')}>
        <code style={{ fontSize: 12, color: tok.labelTertiary }}>{rt?.storage_mode ?? 'local'}</code>
      </Row>

      {/* Integrations */}
      <SectionTitle title={t('settings_runtime_integration_section')} />
      <Row label={t('settings_runtime_langsmith_tracing')}
           hint={t('settings_runtime_value_unchanged')}>
        <Toggle checked={rt?.langsmith_tracing ?? false}
                onChange={v => update({ langsmith_tracing: v })} />
      </Row>
      <Row label={t('settings_runtime_langsmith_project')}
           hint={t('settings_runtime_value_unchanged')}>
        <Input value={rt?.langsmith_project ?? 'langconfig'}
               onChange={v => update({ langsmith_project: v })}
               width={240} />
      </Row>
      <Row label={t('settings_runtime_ollama_embed_model')}
           hint={t('settings_runtime_ollama_embed_model_hint')}>
        <Input value={rt?.ollama_embed_model ?? 'nomic-embed-text:latest'}
               onChange={v => update({ ollama_embed_model: v })}
               mono width={280} />
      </Row>

      {/* Performance / DB pool */}
      <SectionTitle title={t('settings_runtime_perf_section')} />
      <Row label={t('settings_runtime_db_pool_size')}
           hint={t('settings_runtime_db_pool_size_hint')}>
        <Input {...numField('db_pool_size', 110)} placeholder="10" />
      </Row>
      <Row label={t('settings_runtime_db_max_overflow')}
           hint={t('settings_runtime_db_max_overflow_hint')}>
        <Input {...numField('db_max_overflow', 110)} placeholder="20" />
      </Row>
      <Row label={t('settings_runtime_rate_limit_enabled')}
           hint={t('settings_runtime_value_unchanged')}>
        <Toggle checked={rt?.rate_limit_enabled ?? true}
                onChange={v => update({ rate_limit_enabled: v })} />
      </Row>
      <Row label={t('settings_runtime_rate_limit_requests_per_minute')}
           hint={t('settings_runtime_value_unchanged')}>
        <Input {...numField('rate_limit_requests_per_minute', 110)} placeholder="1000" />
      </Row>
      <Row label={t('settings_runtime_perf_monitoring_enabled')}
           hint={t('settings_runtime_value_unchanged')}>
        <Toggle checked={rt?.performance_monitoring_enabled ?? true}
                onChange={v => update({ performance_monitoring_enabled: v })} />
      </Row>
      <Row label={t('settings_runtime_slow_request_threshold_ms')}
           hint={t('settings_runtime_value_unchanged')}>
        <Input {...numField('slow_request_threshold_ms', 110)} placeholder="1000" />
      </Row>
      <Row label={t('settings_runtime_log_slow_queries')}
           hint={t('settings_runtime_value_unchanged')}>
        <Toggle checked={rt?.log_slow_queries ?? true}
                onChange={v => update({ log_slow_queries: v })} />
      </Row>
      <Row label={t('settings_runtime_slow_query_threshold')}
           hint={t('settings_runtime_value_unchanged')}>
        <Input {...{ value: rt?.slow_query_threshold != null ? String(rt.slow_query_threshold) : '',
                    onChange: (v: string) => update({ slow_query_threshold: parseFloat(v.replace(/[^\d.]/g, '')) || 0 }),
                    type: 'number', width: 110 }}
               placeholder="1.0" />
      </Row>
      <Row label={t('settings_runtime_log_all_requests')}
           hint={t('settings_runtime_value_unchanged')}>
        <Toggle checked={rt?.log_all_requests ?? false}
                onChange={v => update({ log_all_requests: v })} />
      </Row>

      {/* Agent / analysis */}
      <SectionTitle title={t('settings_runtime_analysis_section')} />
      <Row label={t('settings_agent_max_iterations')}
           hint={t('settings_agent_max_iterations_hint')}>
        <Input {...numField('analysis_recursion_limit', 120)} placeholder="1000" />
      </Row>
      <Row label={t('settings_runtime_analysis_dashboard_timeout')}
           hint={t('settings_runtime_analysis_dashboard_timeout_hint')}>
        <Input {...numField('analysis_dashboard_timeout', 110)} placeholder="600" />
      </Row>
      <Row label={t('settings_runtime_analysis_chat_timeout')}
           hint={t('settings_runtime_analysis_chat_timeout_hint')}>
        <Input {...numField('analysis_chat_timeout', 110)} placeholder="120" />
      </Row>

      {/* Execution history */}
      <SectionTitle title={t('settings_runtime_history_section')} />
      <Row label={t('settings_runtime_max_execution_history')}
           hint={t('settings_runtime_value_unchanged')}>
        <Input {...numField('max_execution_history_per_workflow', 110)} placeholder="100" />
      </Row>
      <Row label={t('settings_runtime_execution_history_retention_days')}
           hint={t('settings_runtime_value_unchanged')}>
        <Input {...numField('execution_history_retention_days', 110)} placeholder="90" />
      </Row>
      <Row label={t('settings_runtime_auto_cleanup_execution_history')}
           hint={t('settings_runtime_value_unchanged')}>
        <Toggle checked={rt?.auto_cleanup_execution_history ?? true}
                onChange={v => update({ auto_cleanup_execution_history: v })} />
      </Row>
    </div>
  )
}

// ── Agents (create-time limits) ───────────────────────────────────
//
// The two kinds carry different numbers on purpose: recursion_limit counts
// LangGraph supersteps, and one LLM turn costs ~13 steps for a standard agent
// (six default middleware × before_model + after_model) but ~2 for a DeepAgent.
// Creators read this namespace, so editing a value here changes what the next
// agent is created with.

const AGENT_LIMIT_FIELDS: { key: string; label: string; hintKey: string }[] = [
  {
    key: 'recursion_limit',
    label: 'recursion_limit',
    hintKey: 'settings_agents_limit_recursion_limit_hint',
  },
  {
    key: 'summarization_threshold',
    label: 'summarization_threshold',
    hintKey: 'settings_agents_limit_summarization_threshold_hint',
  },
  {
    key: 'keep_last_messages',
    label: 'keep_last_messages',
    hintKey: 'settings_agents_limit_keep_last_messages_hint',
  },
  {
    key: 'max_total_tokens',
    label: 'max_total_tokens',
    hintKey: 'settings_agents_limit_max_total_tokens_hint',
  },
  {
    key: 'eviction_threshold',
    label: 'eviction_threshold',
    hintKey: 'settings_agents_limit_eviction_threshold_hint',
  },
]

function AgentLimitsBlock({ kind, title, hint }: { kind: 'agent' | 'deepagent'; title: string; hint: string }) {
  const { t } = useTranslation('chat')
  const [limits, setLimits] = useState<Record<string, any> | null>(null)
  const [failed, setFailed] = useState(false)

  const reload = useCallback(async () => {
    const ns = await describeNs('agents')
    setLimits((ns?.value?.[kind] as Record<string, any>) ?? null)
  }, [kind])

  useEffect(() => { reload() }, [reload])

  const write = async (key: string, value: any) => {
    const ok = await mutateNs('agents', [{ op: 'set', path: [kind, key], value }])
    setFailed(!ok)
    await reload()   // server truth (validation may reject an ordering violation)
  }

  if (!limits) return null

  return (
    <div style={{ marginTop: 20 }}>
      <SectionTitle title={title} desc={hint} />
      {failed && (
        <div style={{ fontSize: 12, color: 'var(--color-danger, #d33)', marginBottom: 8 }}>
          {t('settings_agents_rejected')}
        </div>
      )}
      {AGENT_LIMIT_FIELDS.map(f => (
        <Row key={f.key} label={f.label} hint={t(f.hintKey)}>
          <Input
            type="number"
            mono
            width={140}
            value={String(limits[f.key] ?? '')}
            onChange={v => write(f.key, v === '' ? undefined : parseInt(v, 10))}
          />
        </Row>
      ))}
      <Row label="enable_summarization" hint={t('settings_runtime_enable_summarization_hint')}>
        <Toggle checked={Boolean(limits.enable_summarization)} onChange={v => write('enable_summarization', v)} />
      </Row>
      <Row label="enable_auto_eviction" hint={t('settings_runtime_enable_auto_eviction_hint')}>
        <Toggle checked={Boolean(limits.enable_auto_eviction)} onChange={v => write('enable_auto_eviction', v)} />
      </Row>
    </div>
  )
}

function AgentsSection() {
  const { t } = useTranslation('chat')
  return (
    <div>
      <SectionTitle
        title={t('settings_agents')}
        desc={t('settings_agents_desc')}
      />
      <AgentLimitsBlock
        kind="agent"
        title={t('settings_agents_standard')}
        hint={t('settings_agents_standard_hint')}
      />
      <AgentLimitsBlock
        kind="deepagent"
        title={t('settings_agents_deepagent')}
        hint={t('settings_agents_deepagent_hint')}
      />
    </div>
  )
}

// ── Knowledge migration ───────────────────────────────────────────
//
// Not a normal operation: run once per machine after a teammate's data has arrived in the old
// `data/documents/project_<id>/` layout, then never again. It lives in Settings for that reason —
// beside the upload buttons it would be mistaken for one. See
// docs/plans/2026-10-15-kv-ingest-core-spec.md.
function KnowledgeSection() {
  const [bases, setBases] = useState<string[]>([])

  const loadBases = useCallback(() => {
    apiClient.listKnowledgeBases()
      .then((r: any) => {
        const list = r?.data?.bases ?? r?.bases ?? []
        setBases(Array.isArray(list) ? list.map((b: any) => b.key).filter(Boolean) : [])
      })
      .catch(() => { /* the hint and the panel both degrade without it */ })
  }, [])

  // `existingBases` only drives a hint ("merges into the base that already exists"), so a failure
  // to load it must not stop the panels from working.
  useEffect(() => { loadBases() }, [loadBases])

  const panelTokens = {
    bg: tok.layer1,
    bgPanel: tok.layer2,
    border: tok.borderL2,
    textPrimary: tok.labelPrimary,
    textMuted: tok.labelSecondary,
    hover: tok.hover,
    primary: tok.primary,
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 24 }}>
      <DocChatSettingsPanel t={panelTokens} />
      <div style={{ height: 1, background: tok.borderL2 }} />
      <ImportFolderPanel onImported={loadBases} existingBases={bases} t={panelTokens} />
      <div style={{ height: 1, background: tok.borderL2 }} />
      <KnowledgeIndexPanel onIndexed={loadBases} t={panelTokens} />
      <div style={{ height: 1, background: tok.borderL2 }} />
      <LegacyMigrationPanel existingBases={bases} onMigrated={loadBases} t={panelTokens} />
    </div>
  )
}

// ── About ─────────────────────────────────────────────────────────

// ── Databases ────────────────────────────────────────────────────────
/** Which databases the SQL tools (and the Studio picker) may point at.
 *
 * The table lists the CATALOG — every database the server can reach, joined with
 * the stored setting — so the admin sees the ones they switched off instead of
 * having them vanish from the page. Only switched-ON rows are stored: the setting
 * IS the offered list.
 *
 * This exists because the picker used to enumerate EVERY database on the platform
 * Postgres — including `langconfig` and `postgres`, i.e. the platform's own tables
 * were one dropdown click away from `sql_db_query`.
 *
 * Admin-only: the list changes what every account's tools may reach. Members see
 * it read-only rather than a control that would 403.
 */
interface DbEntry {
  name: string
  label?: string | null
  /** platform/target = a SQL database; dashboard = a dashboard grouping with pages. */
  kind: 'platform' | 'target' | 'dashboard'
  host?: string | null
  port?: number | string | null
  dbname?: string | null
  user?: string | null
  enabled?: boolean
  /** True when a password is stored for this target (the value never arrives). */
  has_password?: boolean
  /** True when the row comes from the setting; false = discovered on the server. */
  registered?: boolean
}

// ── Ontology workbench profiles ──────────────────────────────────
// The Ontology activity opens ONE profile at a time: a workbench server that loads an
// ontology folder, its computation overlay, the target DSN and the SQL guardrails. Which
// profiles exist is a decision, so it lives here — before this section it was four URLs
// compiled into the frontend bundle, which meant "add an ontology" required a rebuild.
//
// The ontology's actual content (objects, definitions, metrics) is NOT edited here: it is
// TTL in the ontology repo, versioned with the ontology, and readable in the browser.

interface OntologyProfileRow {
  key: string
  label: string
  url: string
  profile?: string | null
  note?: string | null
  enabled?: boolean
}

function OntologySection() {
  const [items, setItems] = useState<OntologyProfileRow[]>([])
  const [defaultKey, setDefaultKey] = useState<string>('')
  const [showSql, setShowSql] = useState(true)
  const [revision, setRevision] = useState<number>(0)
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null)
  const [busy, setBusy] = useState(false)
  const [dirty, setDirty] = useState(false)

  const load = useCallback(async () => {
    const ns = await describeNs('ontology')
    if (!ns) {
      setMsg({ ok: false, text: 'the `ontology` settings namespace is not registered on this backend' })
      return
    }
    setItems((ns.value?.items || []) as OntologyProfileRow[])
    setDefaultKey(ns.value?.default_key || '')
    setShowSql(ns.value?.show_sql !== false)
    setRevision(ns.revision || 0)
    setDirty(false)
  }, [])
  useEffect(() => { void load() }, [load])

  const patch = (i: number, k: keyof OntologyProfileRow, v: any) => {
    setItems(rows => rows.map((r, j) => (j === i ? { ...r, [k]: v } : r)))
    setDirty(true)
  }
  const addRow = () => {
    const n = items.length + 1
    setItems(rows => [...rows, { key: `ontology${n}`, label: `Ontology ${n}`, url: 'http://127.0.0.1:8099', profile: '', note: '', enabled: true }])
    setDirty(true)
  }
  const removeRow = (i: number) => {
    setItems(rows => rows.filter((_, j) => j !== i))
    setDirty(true)
  }
  const move = (i: number, d: -1 | 1) => {
    setItems(rows => {
      const next = [...rows]
      const j = i + d
      if (j < 0 || j >= next.length) return rows
      ;[next[i], next[j]] = [next[j], next[i]]
      return next
    })
    setDirty(true)
  }

  const save = async () => {
    setBusy(true)
    setMsg(null)
    const clean = items.map(r => ({
      key: (r.key || '').trim(),
      label: (r.label || r.key || '').trim(),
      url: (r.url || '').trim().replace(/\/+$/, ''),
      profile: (r.profile || '').trim() || null,
      note: (r.note || '').trim() || null,
      enabled: r.enabled !== false,
    }))
    const dupes = clean.map(r => r.key).filter((k, i, all) => k && all.indexOf(k) !== i)
    const blank = clean.filter(r => !r.key || !r.url)
    if (blank.length) {
      setMsg({ ok: false, text: 'every profile needs a key and a URL' })
      setBusy(false)
      return
    }
    if (dupes.length) {
      setMsg({ ok: false, text: `duplicate key(s): ${[...new Set(dupes)].join(', ')}` })
      setBusy(false)
      return
    }
    const ok = await mutateNs('ontology', [
      { op: 'set', path: ['items'], value: clean },
      { op: 'set', path: ['default_key'], value: defaultKey || (clean[0]?.key ?? null) },
      { op: 'set', path: ['show_sql'], value: showSql },
    ])
    setBusy(false)
    if (ok) {
      setMsg({ ok: true, text: 'saved — the Ontology activity reads this list on its next load' })
      await load()
    } else {
      setMsg({ ok: false, text: 'save failed (a stale revision or an invalid value) — reloaded from the server' })
      await load()
    }
  }

  const input: React.CSSProperties = {
    width: '100%', boxSizing: 'border-box', height: 30, padding: '0 8px', borderRadius: 7,
    fontSize: 12, border: `1px solid ${tok.borderL2}`,
    background: `var(--color-input-background, ${tok.layer1})`, color: tok.labelPrimary, outline: 'none',
    fontFamily: 'ui-monospace, Menlo, monospace',
  }
  const label: React.CSSProperties = { fontSize: 10.5, color: tok.labelTertiary, marginBottom: 3, display: 'block' }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 14, width: '100%' }}>
      <SectionTitle
        title="Ontology"
        desc="The workbench profiles the Ontology activity can open. Each one is a server that loads one ontology folder and serves its numbers; the ontology's own content lives in TTL files in the ontology repo, not here."
      />

      {/* The decision goes FIRST. It used to sit under a long profile editor, so a human looking for
          "the publish an agent staged" had to scroll past every profile — and reported not finding it. */}
      <PublishPanel />

      <div style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '10px 14px', border: `1px solid ${tok.borderL2}`, borderRadius: 12 }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 14, lineHeight: '22px', fontWeight: 500, color: tok.labelPrimary }}>Show compiled SQL in the browser</div>
          <div style={{ fontSize: 12, lineHeight: '18px', color: tok.labelTertiary }}>
            A metric's number is the contract; the SQL is how it was computed. Off hides the SQL for readers who only need the definition.
          </div>
        </div>
        <Toggle checked={showSql} onChange={v => { setShowSql(v); setDirty(true) }} />
      </div>

      {items.map((row, i) => (
        <div key={i} style={{ border: `1px solid ${tok.borderL2}`, borderRadius: 12, padding: '12px 14px', display: 'flex', flexDirection: 'column', gap: 10 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <input
              value={row.label || ''}
              onChange={e => patch(i, 'label', e.target.value)}
              placeholder="Label"
              style={{ ...input, width: 200, fontFamily: 'inherit', fontSize: 13, fontWeight: 500 }}
            />
            <input
              value={row.key || ''}
              onChange={e => patch(i, 'key', e.target.value)}
              placeholder="key"
              style={{ ...input, width: 130 }}
            />
            {defaultKey === row.key && (
              <span style={{ fontSize: 10.5, padding: '1px 7px', borderRadius: 9, border: `1px solid ${tok.borderL2}`, color: tok.labelTertiary }}>
                default
              </span>
            )}
            <span style={{ marginLeft: 'auto', display: 'inline-flex', gap: 6, alignItems: 'center' }}>
              <Btn dense onClick={() => setDefaultKey(row.key)} disabled={defaultKey === row.key}>make default</Btn>
              <Btn dense onClick={() => move(i, -1)} disabled={i === 0}>↑</Btn>
              <Btn dense onClick={() => move(i, 1)} disabled={i === items.length - 1}>↓</Btn>
              <Toggle checked={row.enabled !== false} onChange={v => patch(i, 'enabled', v)} />
              <Btn dense variant="danger" onClick={() => removeRow(i)}>remove</Btn>
            </span>
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: '260px 1fr', gap: 10 }}>
            <div>
              <span style={label}>workbench URL</span>
              <input value={row.url || ''} onChange={e => patch(i, 'url', e.target.value)} placeholder="http://127.0.0.1:8096" style={input} />
            </div>
            <div>
              <span style={label}>profile path (shown to the reader; the server was started with it)</span>
              <input value={row.profile || ''} onChange={e => patch(i, 'profile', e.target.value)} placeholder="ontologies/clinic/clinic_settings.json" style={input} />
            </div>
          </div>
          <div>
            <span style={label}>one line — what this ontology is for</span>
            <input value={row.note || ''} onChange={e => patch(i, 'note', e.target.value)} placeholder="built by a DeepAgent from clinic_db" style={{ ...input, fontFamily: 'inherit' }} />
          </div>
        </div>
      ))}

      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
        <Btn onClick={addRow}>+ add profile</Btn>
        <Btn variant="primary" onClick={() => void save()} disabled={busy || !dirty}>{busy ? 'saving…' : 'save'}</Btn>
        <Btn onClick={() => void load()} disabled={busy}>reload</Btn>
        <span style={{ fontSize: 12, color: tok.labelTertiary }}>
          {dirty ? 'unsaved changes' : `${items.length} profile(s) · revision ${revision}`}
        </span>
      </div>

      {msg && (
        <div style={{ fontSize: 12, lineHeight: '18px', color: msg.ok ? tok.success : tok.error }}>{msg.text}</div>
      )}
      <div style={{ fontSize: 12, lineHeight: '18px', color: tok.labelTertiary }}>
        A profile that is not running still appears in the Ontology activity — it shows as “not running”
        with the command that starts it, so a stopped server never looks like an empty ontology.
      </div>

    </div>
  )
}

interface PublishRow {
  id: string
  key: string
  actor: string | null
  status: string
  note: string | null
  report: any
  git_commit: string | null
  created_at: string | null
}

/**
 * The Apply page — the deploy step of the ontology pipeline, by itself.
 *
 * An agent builds and STAGES; a person applies. That decision used to live as the first panel of
 * Settings → Ontology, which meant "where do I install the thing the agent made?" had no answer a
 * reader could point at. Staging is visible here, the diff and the numbers each candidate moves are
 * one click deeper, and apply is armed before it fires.
 */
function ApplySection() {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 14, width: '100%' }}>
      <SectionTitle
        title="Apply"
        desc="An agent stages; a person installs. Every candidate below already compiled and passed the gates against a staging copy — applying re-runs the suite on the installed path, commits with the gate summary, and reloads the workbench. A failure reverts byte for byte."
      />
      <PublishPanel />
    </div>
  )
}

/**
 * Pending publishes — what an agent staged, and the one decision a person makes.
 *
 * An agent that builds or edits an ontology hands its files to `/api/ontology/publish/stage`,
 * which copies them over a STAGING copy of the installed ontology and runs the whole suite
 * there: every metric compiled or refused by name, every gate. A publish that introduces a new
 * refusal or a failing gate is refused at that point. Applying installs, re-runs the gates
 * against the real path, commits with the gate summary and reloads the workbench; a failure
 * reverts byte for byte.
 *
 * The two halves exist so that the agent can do the work while a human decides that a number's
 * meaning changes for everyone. Without this panel the staged publish had no surface, so "the
 * agent published it" really meant "someone copied files by hand and no gate ran".
 */
function PublishPanel() {
  const [rows, setRows] = useState<PublishRow[] | null>(null)
  const [open, setOpen] = useState<string | null>(null)
  const [armed, setArmed] = useState<string | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [showHistory, setShowHistory] = useState(false)
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null)
  // Per-publish diff, fetched on demand: a reviewer deciding "does this number change meaning?"
  // needs the declarations that differ, not a file count.
  const [showDiff, setShowDiff] = useState<string | null>(null)
  const [diffs, setDiffs] = useState<Record<string, any>>({})
  const [showValues, setShowValues] = useState<string | null>(null)
  const [values, setValues] = useState<Record<string, any>>({})

  const load = useCallback(async () => {
    try {
      const res = await apiClient.get('/api/ontology/publish/history', { params: { limit: 40 } })
      setRows((res.data?.publishes || []) as PublishRow[])
    } catch {
      setRows([])
    }
  }, [])
  useEffect(() => { void load() }, [load])

  const applyOne = async (id: string) => {
    setBusy(id); setMsg(null)
    try {
      const res = await apiClient.post(`/api/ontology/publish/${id}/apply`, { confirmed: true })
      const d = res.data || {}
      setMsg({
        ok: true,
        text: `installed ${id} · commit ${d.git_commit || '(none)'} · workbench ${d.workbench_reloaded ? 'reloaded' : `NOT reloaded (${d.reload_note || 'unknown'})`}`,
      })
      setArmed(null)
    } catch (e: any) {
      const status = e?.response?.status
      const detail = e?.response?.data?.detail || e?.message || 'apply failed'
      setMsg({
        ok: false,
        text: status === 403
          ? `你的帐号没有 ontology_editor 角色，不能发布：${detail}`
          : `apply failed: ${detail}`,
      })
    } finally {
      setBusy(null)
      await load()
    }
  }

  const toggleDiff = async (id: string) => {
    setShowDiff(prev => (prev === id ? null : id))
    if (diffs[id] !== undefined) return
    try {
      const res = await apiClient.get(`/api/ontology/publish/${id}/diff`)
      setDiffs(prev => ({ ...prev, [id]: res.data }))
    } catch (e: any) {
      setDiffs(prev => ({ ...prev, [id]: { ok: false, error: e?.response?.data?.detail || e?.message } }))
    }
  }

  /** Which numbers move. Both ontologies are compiled and run, so this is the slow one and it is
   *  asked per proposal — right before the apply decision, not by default. */
  const toggleValues = async (id: string) => {
    setShowValues(prev => (prev === id ? null : id))
    if (values[id] !== undefined) return
    try {
      const res = await apiClient.get(`/api/ontology/publish/${id}/values`, { timeout: 300000 })
      setValues(prev => ({ ...prev, [id]: res.data }))
    } catch (e: any) {
      setValues(prev => ({ ...prev, [id]: { ok: false, error: e?.response?.data?.detail || e?.message } }))
    }
  }

  const discardOne = async (id: string) => {
    setBusy(id); setMsg(null)
    try {
      await apiClient.post(`/api/ontology/publish/${id}/discard`, {})
      setMsg({ ok: true, text: `discarded ${id} — the installed ontology was never touched` })
    } catch (e: any) {
      setMsg({ ok: false, text: `discard failed: ${e?.response?.data?.detail || e?.message || ''}` })
    } finally {
      setBusy(null)
      setArmed(null)
      await load()
    }
  }

  const pending = (rows || []).filter(r => r.status === 'staged')
  const past = (rows || []).filter(r => r.status !== 'staged').slice(0, 12)
  const mono = 'ui-monospace, Menlo, monospace'

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10, border: `1px solid ${tok.borderL2}`, borderRadius: 12, padding: '12px 14px' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 14, lineHeight: '22px', fontWeight: 500, color: tok.labelPrimary }}>Pending publishes</div>
          <div style={{ fontSize: 12, lineHeight: '18px', color: tok.labelTertiary }}>
            An agent stages; a person installs. Each candidate was already compiled and gated against a copy —
            applying re-runs the suite on the installed path, commits with the gate summary, and reloads the workbench.
          </div>
        </div>
        <Btn dense onClick={() => void load()} disabled={busy !== null}>reload</Btn>
      </div>

      {rows === null && <div style={{ fontSize: 12, color: tok.labelTertiary }}>reading the publish ledger…</div>}
      {rows !== null && pending.length === 0 && (
        <div style={{ fontSize: 12, color: tok.labelTertiary }}>
          Nothing is waiting. An agent's <code style={{ fontFamily: mono }}>ontology_publish</code> call lands here;
          the installed ontologies are unchanged until something does.
        </div>
      )}

      {pending.map(row => {
        const rep = row.report || {}
        const comp = rep.compile || {}
        const refused: any[] = comp.refused || []
        const newRef: string[] = rep.new_refusals || []
        const carried: string[] = rep.carried_refusals || []
        const fails: string[] = rep.gates_fails || []
        const notRun: string[] = rep.gates_not_run || []
        const isOpen = open === row.id
        return (
          <div key={row.id} style={{ border: `1px solid ${tok.borderL2}`, borderRadius: 10, padding: '10px 12px', display: 'flex', flexDirection: 'column', gap: 8 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, cursor: 'pointer' }} onClick={() => setOpen(isOpen ? null : row.id)}>
              <span style={{ fontSize: 13, fontWeight: 500, color: tok.labelPrimary }}>{row.key}</span>
              <span style={{ fontSize: 11.5, fontFamily: mono, color: tok.labelTertiary }}>{row.id}</span>
              <span style={{ fontSize: 11, padding: '1px 7px', borderRadius: 9, border: `1px solid ${tok.borderL2}`, color: rep.gates_ok ? tok.success : tok.error }}>
                gates {rep.gates_ok ? 'pass' : 'fail'}
              </span>
              <span style={{ fontSize: 11.5, color: tok.labelTertiary }}>
                {comp.compiled ?? 0}/{comp.metrics ?? 0} metrics · {refused.length} refused{newRef.length ? ` · ${newRef.length} new` : ''}
              </span>
              <span style={{ marginLeft: 'auto', fontSize: 11.5, color: tok.labelTertiary }}>{isOpen ? '▾' : '▸'}</span>
            </div>

            {row.note && <div style={{ fontSize: 12, lineHeight: '18px', color: tok.labelSecondary ?? tok.labelPrimary }}>{row.note}</div>}
            <div style={{ fontSize: 11.5, color: tok.labelTertiary }}>
              {row.actor || 'unknown'} · {row.created_at ? new Date(row.created_at).toLocaleString() : ''}
              {(rep.files || []).length ? ` · ${(rep.files || []).length} file(s)` : ''}
            </div>

            {isOpen && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                {newRef.length > 0 && (
                  <div style={{ fontSize: 12, color: tok.error }}>
                    new refusals (this is why it must not be applied): {newRef.join(', ')}
                  </div>
                )}
                {refused.length > 0 && (
                  <div style={{ fontSize: 11.5, fontFamily: mono, color: tok.labelTertiary, whiteSpace: 'pre-wrap' }}>
                    {refused.slice(0, 12).map((r: any) => `REFUSED ${r.name}: ${r.why}`).join('\n')}
                    {carried.length > 0 ? `\n(carried, already refused before this publish: ${carried.join(', ')})` : ''}
                  </div>
                )}
                {fails.length > 0 && (
                  <div style={{ fontSize: 12, color: tok.error, whiteSpace: 'pre-wrap' }}>{fails.join('\n')}</div>
                )}
                {notRun.length > 0 && (
                  <div style={{ fontSize: 11.5, color: tok.labelTertiary }}>not run (named, not passed): {notRun.join(' · ')}</div>
                )}
                {(rep.files || []).length > 0 && (
                  <div style={{ fontSize: 11, fontFamily: mono, color: tok.labelTertiary, wordBreak: 'break-all' }}>
                    {(rep.files || []).join(' · ')}
                  </div>
                )}
                <div>
                  <span
                    onClick={() => void toggleDiff(row.id)}
                    style={{ fontSize: 11.5, color: tok.labelTertiary, cursor: 'pointer' }}
                  >
                    {showDiff === row.id ? '▾' : '▸'} what would change (diff)
                  </span>
                  {showDiff === row.id && (() => {
                    const d = diffs[row.id]
                    if (d === undefined) return <div style={{ fontSize: 11.5, color: tok.labelTertiary }}>reading the diff…</div>
                    if (!d || !d.ok) return <div style={{ fontSize: 11.5, color: tok.labelTertiary }}>{d?.error || 'no diff'}</div>
                    if (!(d.changed || []).length) {
                      return <div style={{ fontSize: 11.5, color: tok.labelTertiary }}>no file differs from the installed ontology</div>
                    }
                    return (
                      <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                        {d.files.filter((f: any) => f.status === 'added' || f.status === 'changed').map((f: any) => (
                          <div key={f.path}>
                            <div style={{ fontSize: 11, fontFamily: mono, color: tok.labelPrimary }}>
                              {f.path} <span style={{ color: tok.success }}>+{f.added || 0}</span>{' '}
                              <span style={{ color: tok.error }}>−{f.removed || 0}</span>
                            </div>
                            <pre style={{ fontSize: 10, fontFamily: mono, background: tok.layer1, padding: 8, borderRadius: 8, maxHeight: 220, overflow: 'auto', margin: '2px 0 0' }}>
                              {f.diff.trim()}
                            </pre>
                          </div>
                        ))}
                      </div>
                    )
                  })()}
                </div>
                <div>
                  <span
                    onClick={() => void toggleValues(row.id)}
                    style={{ fontSize: 11.5, color: tok.labelTertiary, cursor: 'pointer' }}
                  >
                    {showValues === row.id ? '▾' : '▸'} which numbers move
                  </span>
                  {showValues === row.id && (() => {
                    const v = values[row.id]
                    if (v === undefined) return <div style={{ fontSize: 11.5, color: tok.labelTertiary }}>running both ontologies…</div>
                    if (!v || !v.ok) return <div style={{ fontSize: 11.5, color: tok.labelTertiary }}>{v?.error || 'no comparison'}</div>
                    const changed = v.changed || []
                    if (!changed.length) {
                      return <div style={{ fontSize: 11.5, color: tok.labelTertiary }}>no number moves ({v.unchanged || 0} checked)</div>
                    }
                    return (
                      <div style={{ fontSize: 11, fontFamily: mono, display: 'flex', flexDirection: 'column', gap: 2 }}>
                        {changed.map((c: any) => (
                          <div key={c.metric}>
                            <span style={{ color: tok.error }}>{c.metric}</span>{' '}
                            {String(c.before ?? c.before_state ?? '—')}{' → '}
                            <b>{String(c.after ?? c.after_state ?? '—')}</b>
                          </div>
                        ))}
                        <div style={{ fontSize: 10.5, color: tok.labelTertiary }}>
                          {changed.length} of {v.metrics} move
                        </div>
                      </div>
                    )
                  })()}
                </div>
                {rep.gates_text && (
                  <details>
                    <summary style={{ fontSize: 11.5, color: tok.labelTertiary, cursor: 'pointer' }}>gate output</summary>
                    <pre style={{ fontSize: 10.5, fontFamily: mono, color: tok.labelSecondary ?? tok.labelPrimary, background: tok.layer1, padding: 8, borderRadius: 8, maxHeight: 260, overflow: 'auto', margin: '6px 0 0' }}>
                      {rep.gates_text}
                    </pre>
                  </details>
                )}
              </div>
            )}

            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              {armed === row.id ? (
                <>
                  <Btn dense variant="primary" onClick={() => void applyOne(row.id)} disabled={busy === row.id}>
                    {busy === row.id ? 'installing…' : 'confirm apply'}
                  </Btn>
                  <Btn dense onClick={() => setArmed(null)} disabled={busy === row.id}>cancel</Btn>
                  <span style={{ fontSize: 11.5, color: tok.labelTertiary }}>
                    this changes what {row.key}'s numbers mean for everyone
                  </span>
                </>
              ) : (
                <Btn dense onClick={() => setArmed(row.id)} disabled={busy !== null || newRef.length > 0 || fails.length > 0}>
                  apply…
                </Btn>
              )}
              <Btn dense variant="danger" onClick={() => void discardOne(row.id)} disabled={busy !== null}>discard</Btn>
            </div>
          </div>
        )
      })}

      {past.length > 0 && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
          <span
            onClick={() => setShowHistory(v => !v)}
            style={{ fontSize: 11.5, color: tok.labelTertiary, cursor: 'pointer' }}
          >
            {showHistory ? '▾' : '▸'} history ({past.length})
          </span>
          {showHistory && past.map(r => (
            <div key={r.id} style={{ fontSize: 11.5, fontFamily: mono, color: tok.labelTertiary }}>
              {r.status} · {r.key} · {r.id}{r.git_commit ? ` · ${r.git_commit.slice(0, 7)}` : ''} · {r.actor || '?'}
            </div>
          ))}
        </div>
      )}

      {msg && <div style={{ fontSize: 12, lineHeight: '18px', color: msg.ok ? tok.success : tok.error }}>{msg.text}</div>}
    </div>
  )
}

function DatabasesSection() {
  const { t } = useTranslation('chat')
  const [rows, setRows] = useState<DbEntry[]>([])
  const [isAdmin, setIsAdmin] = useState(false)
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null)
  const [saving, setSaving] = useState(false)
  const [loaded, setLoaded] = useState(false)
  const [active, setActive] = useState<string | null>(null)
  // Draft password per row, and the result of the last connection test per row.
  const [pwDraft, setPwDraft] = useState<Record<string, string>>({})
  const [testResult, setTestResult] = useState<Record<string, { ok: boolean; text: string }>>({})
  const [testing, setTesting] = useState<string | null>(null)

  // The table shows the CATALOG (every database the server can reach), not just
  // the stored list. Storing only the switched-on names meant a database that
  // exists but is switched off was invisible on this page — which is why it
  // looked like the setting had one or two databases in it.
  const load = useCallback(async () => {
    try {
      const res = await apiClient.get('/api/graph-studio/databases/catalog')
      const list = (res.data?.databases || []) as DbEntry[]
      setActive(res.data?.active_sql ?? null)
      setRows(list.map(r => ({
        ...r,
        kind: (r.kind || 'platform') as 'platform' | 'target',
        enabled: r.enabled !== false,
      })))
    } catch {
      // Catalog unreachable → fall back to what is stored, so an admin can still
      // fix the setting instead of being shown an empty table.
      const ns = await describeNs('databases')
      const items = (ns?.value?.items || []) as DbEntry[]
      setRows(items.map(i => ({ ...i, kind: (i.kind || 'platform') as 'platform' | 'target' })))
    }
    setLoaded(true)
  }, [])

  useEffect(() => { load(); currentUserIsAdmin().then(setIsAdmin) }, [load])

  const patch = (idx: number, key: keyof DbEntry, value: any) =>
    setRows(prev => prev.map((r, i) => (i === idx ? { ...r, [key]: value } : r)))

  const addRow = () =>
    setRows(prev => [...prev, { name: '', label: '', kind: 'platform', enabled: true, registered: false }])

  const removeRow = (idx: number) => setRows(prev => prev.filter((_, i) => i !== idx))

  /** Save one row's password. Kept separate from 保存 because the table is stored
   *  as one list value and the browser never receives the stored secret — saving
   *  the whole table would blank it. */
  const savePassword = async (name: string) => {
    const value = (pwDraft[name] || '').trim()
    if (!value) return
    try {
      await apiClient.post(`/api/graph-studio/databases/${encodeURIComponent(name)}/password`, { password: value })
      setPwDraft(prev => ({ ...prev, [name]: '' }))
      await load()
      setMsg({ ok: true, text: `${name}：密码已保存` })
    } catch (e: any) {
      setMsg({ ok: false, text: `${name}：密码保存失败 — ${e?.response?.data?.detail || e?.message || ''}` })
    }
  }

  /** Open a real connection and show what the server said. */
  const testConnection = async (name: string) => {
    setTesting(name)
    try {
      const res = await apiClient.post(`/api/graph-studio/databases/${encodeURIComponent(name)}/test`, {})
      const d = res.data || {}
      setTestResult(prev => ({
        ...prev,
        [name]: d.ok
          ? { ok: true, text: `${d.tables} 张表 · ${d.role} · ${d.version}` }
          : { ok: false, text: String(d.detail || '连接失败') },
      }))
    } catch (e: any) {
      setTestResult(prev => ({ ...prev, [name]: { ok: false, text: e?.response?.data?.detail || e?.message || '连接失败' } }))
    } finally {
      setTesting(null)
    }
  }

  const onCount = rows.filter(r => r.enabled && (r.name || '').trim()).length

  // Every row is stored, including the switched-OFF ones: "off on purpose" has to
  // be told apart from "not registered yet". A published database is shared with
  // every account; an off one is hidden from everyone; an unregistered draft stays
  // with whoever generated it (see services/offered_databases.visibility_of).
  const save = async () => {
    const clean = rows
      .map(r => ({
        name: (r.name || '').trim(),
        label: (r.label || '').toString().trim() || null,
        kind: r.kind || 'platform',
        host: (r.host || '').toString().trim() || null,
        port: r.port ? Number(r.port) : null,
        dbname: (r.dbname || '').toString().trim() || null,
        user: (r.user || '').toString().trim() || null,
        enabled: r.enabled !== false,
      }))
      .filter(r => r.name)
    const bad = clean.find((r, i) => clean.findIndex(x => x.name === r.name) !== i)
    if (bad) { setMsg({ ok: false, text: `重复的名字：${bad.name}` }); return }
    setSaving(true); setMsg(null)
    const ok = await mutateNs('databases', [{ op: 'set', path: ['items'], value: clean }])
    setSaving(false)
    if (ok) {
      await load() // re-read the catalog: the switches now come from the setting
      const offCount = clean.filter(r => !r.enabled).length
      setMsg({ ok: true, text: `已保存：${clean.length - offCount} 个开启 · ${offCount} 个关闭` })
    } else {
      await load()
      setMsg({ ok: false, text: '保存失败：需要 admin 账号（见下方说明）' })
    }
  }

  const cell = (style?: React.CSSProperties): React.CSSProperties => ({
    // 38px rows: eight databases fit on one screen without scrolling.
    padding: '9px 10px', fontSize: 13, background: tok.layer1,
    border: `1px solid ${tok.borderL2}`, borderRadius: 6, color: tok.labelPrimary,
    minWidth: 0, boxSizing: 'border-box', ...style,
  })

  return (
    <div>
      <SectionTitle
        title={t('settings_databases')}
        desc={t('settings_databases_desc')}
      />

      <div style={{ display: 'flex', alignItems: 'center', gap: 10, margin: '0 0 10px' }}>
        <span style={{ fontSize: 12, color: tok.labelTertiary }}>
          {rows.length} 个库 · {onCount} 个开启 · {rows.length - onCount} 个关闭
          {active ? ` · 当前指向 ${active}` : ''}
        </span>
        <button onClick={() => void load()} title="重新扫描服务器上的库" style={{
          marginLeft: 'auto', padding: '3px 10px', fontSize: 12, borderRadius: 4, cursor: 'pointer',
          border: `1px solid ${tok.borderL2}`, background: 'transparent', color: tok.labelSecondary,
        }}>重新扫描</button>
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {loaded && rows.length === 0 && (
          <div style={{ fontSize: 13, color: tok.labelTertiary, padding: '10px 0' }}>
            {t('settings_databases_empty')}
          </div>
        )}

        {rows.length > 0 && (
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'separate', borderSpacing: '0 4px', fontSize: 13 }}>
              <thead>
                <tr style={{ color: tok.labelTertiary, textAlign: 'left' }}>
                  {['on', 'name', 'label', 'kind', 'host', 'port', 'user', 'password', '', ''].map((h, i) => (
                    <th key={h || `c${i}`} style={{ padding: '4px 6px', fontWeight: 500, fontSize: 12 }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rows.map((r, i) => {
                  const fixedName = r.registered === false // discovered: the name is the real dbname
                  return (
                    <tr key={`${r.name}-${i}`} style={{ opacity: r.enabled ? 1 : 0.55 }}>
                      <td style={{ padding: '0 4px', textAlign: 'center' }}>
                        <input type="checkbox" checked={r.enabled !== false} disabled={!isAdmin}
                          title={r.enabled !== false ? '开启：出现在下拉里' : '关闭：不提供给 agent'}
                          onChange={e => patch(i, 'enabled', e.target.checked)} />
                      </td>
                      <td style={{ padding: '0 4px' }}>
                        <input value={r.name} disabled={!isAdmin || fixedName}
                          onChange={e => patch(i, 'name', e.target.value)}
                          title={fixedName ? '服务器上已有的库，名字固定' : ''}
                          placeholder="chinook" style={cell({ width: 140, fontFamily: 'monospace' })} />
                      </td>
                      <td style={{ padding: '0 4px' }}>
                        <input value={r.label || ''} disabled={!isAdmin} onChange={e => patch(i, 'label', e.target.value)}
                          placeholder="显示名" style={cell({ width: 160 })} />
                      </td>
                      <td style={{ padding: '0 4px' }}>
                        <select value={r.kind} disabled={!isAdmin || fixedName} onChange={e => patch(i, 'kind', e.target.value)}
                          style={cell({ width: 96 })}>
                          <option value="platform">platform</option>
                          <option value="target">target</option>
                          <option value="dashboard">dashboard</option>
                        </select>
                      </td>
                      <td style={{ padding: '0 4px' }}>
                        <input value={r.host || ''} disabled={!isAdmin || r.kind !== 'target'}
                          onChange={e => patch(i, 'host', e.target.value)}
                          placeholder={r.kind === 'target' ? '127.0.0.1' : '—'} style={cell({ width: 110, fontFamily: 'monospace' })} />
                      </td>
                      <td style={{ padding: '0 4px' }}>
                        <input value={r.port ?? ''} disabled={!isAdmin || r.kind !== 'target'}
                          onChange={e => patch(i, 'port', e.target.value ? Number(e.target.value) : null)}
                          placeholder={r.kind === 'target' ? '5432' : '—'} style={cell({ width: 66, fontFamily: 'monospace' })} />
                      </td>
                      <td style={{ padding: '0 4px' }}>
                        <input value={r.user || ''} disabled={!isAdmin || r.kind !== 'target'}
                          onChange={e => patch(i, 'user', e.target.value)}
                          placeholder={r.kind === 'target' ? 'myrole' : '—'} style={cell({ width: 88, fontFamily: 'monospace' })} />
                      </td>
                      <td style={{ padding: '0 4px' }}>
                        <input
                          type="password"
                          value={pwDraft[r.name] || ''}
                          disabled={!isAdmin || r.kind !== 'target'}
                          onChange={e => setPwDraft(prev => ({ ...prev, [r.name]: e.target.value }))}
                          onKeyDown={e => { if (e.key === 'Enter') void savePassword(r.name) }}
                          onBlur={() => void savePassword(r.name)}
                          placeholder={r.kind === 'target' ? (r.has_password ? '已设置（留空不改）' : '密码') : '—'}
                          title={r.kind === 'target'
                            ? (r.has_password ? '已保存密码；留空保存不会清除它' : '这个 target 还没有密码')
                            : 'platform 用 POSTGRES_* 里的凭据'}
                          style={cell({ width: 112, fontFamily: 'monospace' })}
                        />
                      </td>
                      <td style={{ padding: '0 4px', whiteSpace: 'nowrap' }}>
                        <button
                          onClick={() => void testConnection(r.name)}
                          disabled={testing === r.name}
                          title="真的连一次库，把服务器返回的原话显示出来"
                          style={{
                            height: 26, padding: '0 8px', fontSize: 11, borderRadius: 5,
                            border: `1px solid ${tok.borderL2}`, background: 'transparent',
                            color: tok.labelSecondary, cursor: testing === r.name ? 'wait' : 'pointer',
                          }}
                        >{testing === r.name ? '…' : '测试'}</button>
                        {testResult[r.name] && (
                          <div
                            title={testResult[r.name].text}
                            style={{
                              marginTop: 3, maxWidth: 190, fontSize: 10.5, lineHeight: '14px',
                              color: testResult[r.name].ok ? '#2e7d32' : '#e5484d',
                              overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                            }}
                          >{testResult[r.name].ok ? '✓ ' : '✗ '}{testResult[r.name].text}</div>
                        )}
                      </td>
                      <td style={{ padding: '0 4px' }}>
                        {isAdmin && !fixedName && (
                          <button onClick={() => removeRow(i)} title="移除这一行"
                            style={{ border: 'none', background: 'transparent', color: '#e5484d', cursor: 'pointer', fontSize: 13 }}>
                            ✕
                          </button>
                        )}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}

        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginTop: 6 }}>
          {isAdmin ? (
            <>
              <button onClick={addRow} style={{
                padding: '5px 12px', fontSize: 13, borderRadius: 4, cursor: 'pointer',
                border: `1px solid ${tok.borderL2}`, background: 'transparent', color: tok.labelPrimary,
              }}>{t('settings_databases_add')}</button>
              <button onClick={save} disabled={saving} style={{
                padding: '5px 14px', fontSize: 13, borderRadius: 4, cursor: saving ? 'wait' : 'pointer',
                border: 'none', background: tok.primary, color: '#fff', opacity: saving ? 0.6 : 1,
              }}>{saving ? '…' : t('settings_databases_save')}</button>
            </>
          ) : (
            <span style={{ fontSize: 12, color: tok.labelTertiary }}>{t('settings_databases_admin_only')}</span>
          )}
          {msg && (
            <span style={{ fontSize: 12, color: msg.ok ? '#2e7d32' : '#e5484d' }}>{msg.text}</span>
          )}
        </div>

        <p style={{ fontSize: 12, lineHeight: '18px', color: tok.labelTertiary, margin: '10px 0 0', maxWidth: 760 }}>
          {t('settings_databases_hint')}
        </p>
      </div>
    </div>
  )
}

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
