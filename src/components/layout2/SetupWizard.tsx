/**
 * SetupWizard — first-run onboarding, shown instead of the IDE shell until
 * the user completes it.
 *
 * Step 1 · Connect your AI provider — pick a provider, paste an API key,
 *          test the connection, save (encrypted in PostgreSQL).
 * Step 2 · Choose your workspace — one-click default folder, or a custom
 *          path with server-side validation.
 * Finish  → marks setup complete → the app loads normally.
 */
import { useEffect, useState } from 'react';
import { useLayoutTokens } from './tokens';
import apiClient from '../../lib/api-client';
import {
  KeyRound, FolderOpen, Check, X, Loader, ArrowRight, ArrowLeft,
  Eye, EyeOff, ShieldCheck, FolderPlus, Sparkles, ChevronRight,
} from 'lucide-react';

interface SetupWizardProps {
  onComplete: () => void;
}

interface ProviderInfo {
  provider: string;
  is_set: boolean;
  masked_key?: string | null;
  kind?: string;
}

// Provider name → APIKeySet field (matches backend API_PROVIDER_KEY_FIELDS).
const PROVIDER_FIELD: Record<string, string> = {
  openai: 'openai_api_key',
  anthropic: 'anthropic_api_key',
  google: 'google_api_key',
  cohere: 'cohere_api_key',
  replicate: 'replicate_api_key',
  deepseek: 'deepseek_api_key',
  glm: 'glm_api_key',
  minimax: 'minimax_api_key',
  qwen: 'qwen_api_key',
  kimi: 'kimi_api_key',
  agnes: 'agnes_api_key',
  tavily: 'tavily_api_key',
  serper: 'serper_api_key',
};

const PROVIDER_LABEL: Record<string, string> = {
  openai: 'OpenAI', anthropic: 'Anthropic', google: 'Google', deepseek: 'DeepSeek',
  glm: 'GLM', minimax: 'MiniMax', qwen: 'Qwen', kimi: 'Kimi',
  cohere: 'Cohere', replicate: 'Replicate', agnes: 'Agnes',
  tavily: 'Tavily', serper: 'Serper',
};

export default function SetupWizard({ onComplete }: SetupWizardProps) {
  const t = useLayoutTokens();

  const [step, setStep] = useState<1 | 2>(1);

  // Step 1 — API key
  const [providers, setProviders] = useState<ProviderInfo[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [apiKey, setApiKey] = useState('');
  const [showKey, setShowKey] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<{ ok: boolean; msg: string } | null>(null);
  const [savingKey, setSavingKey] = useState(false);
  const [keySaved, setKeySaved] = useState(false);

  // Step 2 — workspace
  const [defaultWs, setDefaultWs] = useState('');
  const [wsMode, setWsMode] = useState<'default' | 'custom'>('default');
  const [customPath, setCustomPath] = useState('');
  const [wsValidate, setWsValidate] = useState<{ ok: boolean; msg: string } | null>(null);
  const [validating, setValidating] = useState(false);
  const [wsSaving, setWsSaving] = useState(false);
  const [finishing, setFinishing] = useState(false);

  useEffect(() => {
    apiClient.getSetupStatus()
      .then((r: any) => setDefaultWs(r.data?.default_workspace_path || ''))
      .catch(() => {});
    apiClient.getApiKeys()
      .then((r: any) => {
        const list: ProviderInfo[] = Array.isArray(r.data) ? r.data : [];
        setProviders(list);
        const chat = list.filter(p => p.kind !== 'search');
        const already = chat.find(p => p.is_set);
        setSelected(already?.provider ?? chat[0]?.provider ?? null);
      })
      .catch(() => {});
  }, []);

  const selectedInfo = providers.find(p => p.provider === selected) || null;

  const handleSelectProvider = (provider: string) => {
    setSelected(provider);
    setApiKey('');
    setTestResult(null);
    setKeySaved(false);
  };

  const handleTest = async () => {
    if (!selected) return;
    setTesting(true);
    setTestResult(null);
    try {
      const res = await apiClient.testApiKey(selected, apiKey || undefined);
      const d = res.data || {};
      setTestResult({ ok: !!d.success, msg: d.message || (d.success ? '✓ Connected' : '✗ Failed') });
    } catch {
      setTestResult({ ok: false, msg: '✗ Connection failed' });
    } finally {
      setTesting(false);
    }
  };

  const handleSaveKey = async () => {
    if (!selected || !apiKey.trim()) return;
    setSavingKey(true);
    try {
      const field = PROVIDER_FIELD[selected];
      if (!field) return;
      await apiClient.setApiKeys({ [field]: apiKey.trim() } as any);
      setKeySaved(true);
      setTestResult(null);
      // reflect the saved state in the list
      setProviders(prev => prev.map(p =>
        p.provider === selected ? { ...p, is_set: true, masked_key: `••••${apiKey.trim().slice(-4)}` } : p
      ));
    } finally {
      setSavingKey(false);
    }
  };

  const handleValidatePath = async () => {
    if (!customPath.trim()) return;
    setValidating(true);
    setWsValidate(null);
    try {
      const res = await apiClient.validateWorkspacePath(customPath.trim());
      const d = res.data || {};
      if (d.valid) {
        setWsValidate({ ok: true, msg: `✓ Valid — ${d.resolved_path}` });
      } else {
        setWsValidate({ ok: false, msg: `✗ ${d.error || 'Invalid path'}` });
      }
    } catch {
      setWsValidate({ ok: false, msg: '✗ Validation failed' });
    } finally {
      setValidating(false);
    }
  };

  const finish = async (saveWorkspace: boolean) => {
    if (finishing) return;
    setFinishing(true);
    try {
      if (saveWorkspace) {
        const path = wsMode === 'custom' ? customPath.trim() : defaultWs;
        if (path) {
          await apiClient.updateWorkspaceSettings({ workspace_path: path });
        }
      }
      await apiClient.completeSetup();
      onComplete();
    } catch {
      setFinishing(false);
    }
  };

  const chatProviders = providers.filter(p => p.kind !== 'search');
  const searchProviders = providers.filter(p => p.kind === 'search');

  const inputStyle: React.CSSProperties = {
    width: '100%', padding: '10px 12px', borderRadius: 8, fontSize: 13,
    background: t.bgContent, border: `1px solid ${t.border}`, color: t.textPrimary, outline: 'none',
  };

  return (
    <div
      style={{
        height: '100vh', width: '100vw', overflowY: 'auto',
        background: `radial-gradient(1200px 600px at 20% -10%, ${t.accent}14 0%, transparent 55%), ${t.bgSidebar}`,
        display: 'flex', alignItems: 'flex-start', justifyContent: 'center',
        padding: '48px 24px 64px',
      }}
    >
      <div style={{ width: '100%', maxWidth: 640 }}>
        {/* ── Header ── */}
        <div style={{ textAlign: 'center', marginBottom: 28 }}>
          <div
            style={{
              width: 56, height: 56, borderRadius: 14, margin: '0 auto 16px',
              background: `linear-gradient(135deg, ${t.accent}, ${t.accent}bb)`,
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              boxShadow: `0 6px 20px ${t.accent}40`,
            }}
          >
            <Sparkles size={28} color="#fff" />
          </div>
          <h1 style={{ fontSize: 26, fontWeight: 750, color: t.textPrimary, margin: 0, letterSpacing: '-0.4px' }}>
            Welcome to LangConfig
          </h1>
          <p style={{ fontSize: 13, color: t.textMuted, margin: '8px 0 0 0' }}>
            {step === 1
              ? 'Step 1 of 2 — connect your AI provider to get started'
              : 'Step 2 of 2 — choose where your work lives'}
          </p>
        </div>

        {/* ── Progress dots ── */}
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8, marginBottom: 24 }}>
          {[1, 2].map(n => (
            <div key={n} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <div
                style={{
                  width: 10, height: 10, borderRadius: '50%',
                  background: step >= n ? t.accent : t.border,
                  transition: 'background 0.2s',
                }}
              />
              {n === 1 && <div style={{ width: 40, height: 2, background: step >= 2 ? t.accent : t.border }} />}
            </div>
          ))}
        </div>

        {/* ── Card ── */}
        <div
          style={{
            background: t.bgContent, border: `1px solid ${t.border}`, borderRadius: 14,
            boxShadow: '0 12px 40px rgba(0,0,0,0.18)', overflow: 'hidden',
          }}
        >
          {step === 1 ? (
            <div style={{ padding: 24 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 6 }}>
                <div style={{ width: 30, height: 30, borderRadius: 8, background: `${t.accent}15`, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                  <KeyRound size={15} color={t.accent} />
                </div>
                <div>
                  <div style={{ fontSize: 15, fontWeight: 650, color: t.textPrimary }}>API key</div>
                  <div style={{ fontSize: 11, color: t.textMuted }}>Stored encrypted — you can change it later in Settings</div>
                </div>
              </div>

              {/* Chat providers */}
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(120px, 1fr))', gap: 8, margin: '16px 0 6px' }}>
                {chatProviders.map(p => (
                  <button
                    key={p.provider}
                    onClick={() => handleSelectProvider(p.provider)}
                    style={{
                      display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 6,
                      padding: '8px 10px', borderRadius: 8, fontSize: 12, cursor: 'pointer',
                      background: selected === p.provider ? `${t.accent}12` : t.bgSidebar,
                      border: selected === p.provider ? `1px solid ${t.accent}` : `1px solid ${t.border}`,
                      color: t.textPrimary,
                    }}
                  >
                    <span style={{ fontWeight: 600 }}>{PROVIDER_LABEL[p.provider] || p.provider}</span>
                    {p.is_set && <Check size={13} color="#22c55e" />}
                  </button>
                ))}
              </div>
              {searchProviders.length > 0 && (
                <p style={{ fontSize: 10, color: t.textMuted, margin: '6px 0 0 0' }}>
                  Search providers ({searchProviders.map(p => PROVIDER_LABEL[p.provider] || p.provider).join(', ')}) can be added later in Settings.
                </p>
              )}

              {/* Selected provider key input */}
              {selected && (
                <div style={{ marginTop: 18 }}>
                  <div style={{ fontSize: 12, fontWeight: 600, color: t.textPrimary, marginBottom: 6 }}>
                    {PROVIDER_LABEL[selected] || selected} API key
                    {selectedInfo?.is_set && (
                      <span style={{ color: '#22c55e', fontWeight: 500, marginLeft: 8 }}>
                        <Check size={11} style={{ display: 'inline', verticalAlign: -1 }} /> configured {selectedInfo.masked_key ? `(${selectedInfo.masked_key})` : ''}
                      </span>
                    )}
                  </div>
                  <div style={{ display: 'flex', gap: 8 }}>
                    <div style={{ position: 'relative', flex: 1 }}>
                      <input
                        type={showKey ? 'text' : 'password'}
                        value={apiKey}
                        onChange={e => { setApiKey(e.target.value); setKeySaved(false); setTestResult(null); }}
                        placeholder={selectedInfo?.is_set ? 'Paste a new key to replace, or leave empty' : `sk-…  (${PROVIDER_LABEL[selected] || selected})`}
                        style={inputStyle}
                        autoFocus
                      />
                      <button
                        onClick={() => setShowKey(v => !v)}
                        title={showKey ? 'Hide' : 'Show'}
                        style={{ position: 'absolute', right: 8, top: '50%', transform: 'translateY(-50%)', border: 'none', background: 'transparent', color: t.textMuted, cursor: 'pointer', display: 'flex' }}
                      >
                        {showKey ? <EyeOff size={14} /> : <Eye size={14} />}
                      </button>
                    </div>
                    <button
                      onClick={handleTest}
                      disabled={testing || !apiKey.trim()}
                      style={{
                        padding: '0 14px', borderRadius: 8, border: `1px solid ${t.border}`,
                        background: 'transparent', color: t.textPrimary, fontSize: 12, fontWeight: 600, cursor: 'pointer',
                        display: 'inline-flex', alignItems: 'center', gap: 6,
                        opacity: apiKey.trim() ? 1 : 0.5,
                      }}
                    >
                      {testing ? <Loader size={13} style={{ animation: 'spin 1s linear infinite' }} /> : 'Test'}
                    </button>
                    <button
                      onClick={handleSaveKey}
                      disabled={savingKey || !apiKey.trim()}
                      style={{
                        padding: '0 16px', borderRadius: 8, border: 'none',
                        background: t.accent, color: '#fff', fontSize: 12, fontWeight: 650, cursor: 'pointer',
                        display: 'inline-flex', alignItems: 'center', gap: 6,
                        opacity: apiKey.trim() ? 1 : 0.5,
                      }}
                    >
                      {savingKey ? <Loader size={13} style={{ animation: 'spin 1s linear infinite' }} /> : keySaved ? <Check size={13} /> : 'Save'}
                    </button>
                  </div>
                  {testResult && (
                    <div style={{ fontSize: 11, marginTop: 8, color: testResult.ok ? '#22c55e' : '#ef4444' }}>
                      {testResult.msg}
                    </div>
                  )}
                  {keySaved && !testResult && (
                    <div style={{ fontSize: 11, marginTop: 8, color: '#22c55e' }}>✓ API key saved (encrypted).</div>
                  )}
                </div>
              )}

              {/* Footer */}
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: 24 }}>
                <button
                  onClick={() => setStep(2)}
                  style={{ border: 'none', background: 'transparent', color: t.textMuted, fontSize: 12, cursor: 'pointer' }}
                >
                  Skip for now
                </button>
                <button
                  onClick={() => setStep(2)}
                  style={{
                    display: 'inline-flex', alignItems: 'center', gap: 8,
                    padding: '10px 20px', borderRadius: 8, border: 'none',
                    background: t.accent, color: '#fff', fontSize: 13, fontWeight: 650, cursor: 'pointer',
                  }}
                >
                  Continue <ArrowRight size={14} />
                </button>
              </div>
            </div>
          ) : (
            <div style={{ padding: 24 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 6 }}>
                <div style={{ width: 30, height: 30, borderRadius: 8, background: `${t.accent}15`, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                  <FolderOpen size={15} color={t.accent} />
                </div>
                <div>
                  <div style={{ fontSize: 15, fontWeight: 650, color: t.textPrimary }}>Workspace</div>
                  <div style={{ fontSize: 11, color: t.textMuted }}>
                    Where your projects, agents, uploads (knowledge-base) and generated files live
                  </div>
                </div>
              </div>

              {/* Default option */}
              <button
                onClick={() => setWsMode('default')}
                style={{
                  width: '100%', textAlign: 'left', marginTop: 16, padding: 14, borderRadius: 10, cursor: 'pointer',
                  background: wsMode === 'default' ? `${t.accent}10` : t.bgSidebar,
                  border: wsMode === 'default' ? `1px solid ${t.accent}` : `1px solid ${t.border}`,
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <FolderPlus size={15} color={wsMode === 'default' ? t.accent : t.textMuted} />
                  <span style={{ fontSize: 13, fontWeight: 600, color: t.textPrimary }}>Use the default workspace</span>
                </div>
                <div style={{ fontSize: 11, color: t.textMuted, marginTop: 4, fontFamily: 'monospace' }}>
                  {defaultWs || 'backend/outputs'}
                </div>
              </button>

              {/* Custom option */}
              <button
                onClick={() => setWsMode('custom')}
                style={{
                  width: '100%', textAlign: 'left', marginTop: 8, padding: 14, borderRadius: 10, cursor: 'pointer',
                  background: wsMode === 'custom' ? `${t.accent}10` : t.bgSidebar,
                  border: wsMode === 'custom' ? `1px solid ${t.accent}` : `1px solid ${t.border}`,
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <FolderOpen size={15} color={wsMode === 'custom' ? t.accent : t.textMuted} />
                  <span style={{ fontSize: 13, fontWeight: 600, color: t.textPrimary }}>Choose a custom folder</span>
                </div>
              </button>

              {wsMode === 'custom' && (
                <div style={{ marginTop: 12 }}>
                  <div style={{ display: 'flex', gap: 8 }}>
                    <input
                      value={customPath}
                      onChange={e => { setCustomPath(e.target.value); setWsValidate(null); }}
                      placeholder="/Users/you/Documents/my-workspace"
                      style={{ ...inputStyle, fontFamily: 'monospace' }}
                    />
                    <button
                      onClick={handleValidatePath}
                      disabled={validating || !customPath.trim()}
                      style={{
                        padding: '0 14px', borderRadius: 8, border: `1px solid ${t.border}`,
                        background: 'transparent', color: t.textPrimary, fontSize: 12, fontWeight: 600, cursor: 'pointer',
                        opacity: customPath.trim() ? 1 : 0.5,
                      }}
                    >
                      {validating ? <Loader size={13} style={{ animation: 'spin 1s linear infinite' }} /> : 'Validate'}
                    </button>
                  </div>
                  {wsValidate && (
                    <div style={{ fontSize: 11, marginTop: 8, color: wsValidate.ok ? '#22c55e' : '#ef4444' }}>
                      {wsValidate.msg}
                    </div>
                  )}
                </div>
              )}

              <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginTop: 16, fontSize: 11, color: t.textMuted }}>
                <ShieldCheck size={13} color="#22c55e" />
                Your files stay on this machine. Permission controls can be tuned later in Settings → Workspace.
              </div>

              {/* Footer */}
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: 24 }}>
                <div style={{ display: 'flex', gap: 8 }}>
                  <button
                    onClick={() => setStep(1)}
                    style={{
                      display: 'inline-flex', alignItems: 'center', gap: 6, padding: '10px 14px', borderRadius: 8,
                      border: `1px solid ${t.border}`, background: 'transparent', color: t.textPrimary,
                      fontSize: 13, cursor: 'pointer',
                    }}
                  >
                    <ArrowLeft size={14} /> Back
                  </button>
                  <button
                    onClick={() => finish(false)}
                    disabled={finishing}
                    style={{ border: 'none', background: 'transparent', color: t.textMuted, fontSize: 12, cursor: 'pointer' }}
                  >
                    Skip for now
                  </button>
                </div>
                <button
                  onClick={() => finish(true)}
                  disabled={finishing || (wsMode === 'custom' && (!customPath.trim() || (wsValidate ? !wsValidate.ok : false)))}
                  style={{
                    display: 'inline-flex', alignItems: 'center', gap: 8,
                    padding: '10px 20px', borderRadius: 8, border: 'none',
                    background: t.accent, color: '#fff', fontSize: 13, fontWeight: 650, cursor: 'pointer',
                    opacity: finishing ? 0.7 : 1,
                  }}
                >
                  {finishing ? <Loader size={14} style={{ animation: 'spin 1s linear infinite' }} /> : <ChevronRight size={14} />}
                  Launch LangConfig
                </button>
              </div>
            </div>
          )}
        </div>

        <p style={{ textAlign: 'center', fontSize: 11, color: t.textMuted, marginTop: 16 }}>
          You can re-open this setup anytime from the Settings menu.
        </p>
      </div>
    </div>
  );
}
