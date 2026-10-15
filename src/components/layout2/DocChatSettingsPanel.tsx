/**
 * DocChatSettingsPanel — which model Doc Chat answers with.
 *
 * Doc Chat used to carry an LLM dropdown of its own. That is the wrong place for the choice: it
 * had to be re-made in the panel, per session, and could disagree with every other answer in the
 * app. Removing it left Doc Chat on the app default with no way to say otherwise. This puts the
 * setting where it belongs — with the knowledge base, set once.
 *
 * It is stored in the `knowledge` settings namespace rather than `models`, so a knowledge base can
 * be pointed at a different model without changing what every agent in the app uses. "App default"
 * is a real option and the default: the value is unset, and Doc Chat follows
 * `models.default_model` exactly as it did before this panel existed.
 */
import { useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import apiClient from '../../lib/api-client';
import type { SettingsPanelTokens } from './settingsPanelTokens';
import { CheckCircle, Loader } from 'lucide-react';

interface ModelOption {
  model_id: string;
  display_name?: string;
  provider?: string;
}

interface Props {
  t: SettingsPanelTokens;
}

export default function DocChatSettingsPanel({ t }: Props) {
  const { t: tr } = useTranslation('chat');
  const [model, setModel] = useState('');                 // '' = follow the app default
  const [temperature, setTemperature] = useState('');     // '' = follow the app default
  const [maxFiles, setMaxFiles] = useState('');           // '' = built-in default (300)
  const [maxContext, setMaxContext] = useState('');       // '' = built-in default (1000000)
  const [appDefault, setAppDefault] = useState('');
  const [cloud, setCloud] = useState<ModelOption[]>([]);
  const [local, setLocal] = useState<ModelOption[]>([]);
  const [loading, setLoading] = useState(true);
  const [saved, setSaved] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [desc, models] = await Promise.all([
        apiClient.describeSettings(),
        apiClient.listAvailableModels(),
      ]);
      const namespaces = desc?.data?.namespaces || [];
      const knowledge = namespaces.find((n: any) => n.ns === 'knowledge');
      const modelsNs = namespaces.find((n: any) => n.ns === 'models');
      const kv = knowledge?.value || {};
      setModel(kv.doc_chat_model || '');
      setTemperature(kv.doc_chat_temperature == null ? '' : String(kv.doc_chat_temperature));
      setMaxFiles(kv.doc_chat_max_files == null ? '' : String(kv.doc_chat_max_files));
      setMaxContext(kv.doc_chat_max_context_chars == null ? '' : String(kv.doc_chat_max_context_chars));
      setAppDefault(modelsNs?.value?.default_model || '');
      setCloud(models?.data?.cloud_models || []);
      setLocal(models?.data?.local_models || []);
    } catch (err) {
      console.error(tr('dc_settings_loading'), err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const save = async (ops: Array<{ op: 'set' | 'unset'; path: string[]; value?: any }>) => {
    try {
      await apiClient.mutateSettings({ ns: 'knowledge', ops });
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } catch (err) {
      console.error(tr('dc_settings_saving'), err);
      await load();          // conflict or error — re-read the server truth
    }
  };

  const onModelChange = (value: string) => {
    setModel(value);
    save([value
      ? { op: 'set', path: ['doc_chat_model'], value }
      : { op: 'unset', path: ['doc_chat_model'] }]);
  };

  const onTemperature = (value: string) => {
    setTemperature(value);
    const n = Number(value);
    if (value.trim() === '' || Number.isNaN(n)) {
      save([{ op: 'unset', path: ['doc_chat_temperature'] }]);
    } else {
      save([{ op: 'set', path: ['doc_chat_temperature'], value: Math.min(Math.max(n, 0), 2) }]);
    }
  };

  /**
   * The two limits doc chat used to hard-code. Clamped here to the same bounds the settings schema
   * enforces, so an out-of-range number is corrected rather than thrown back by the API as a
   * failed save.
   */
  const onLimit = (
    value: string,
    field: 'doc_chat_max_files' | 'doc_chat_max_context_chars',
    min: number,
    max: number,
    set: (v: string) => void,
  ) => {
    set(value);
    const n = Number(value);
    if (value.trim() === '' || Number.isNaN(n)) {
      save([{ op: 'unset', path: [field] }]);
    } else {
      save([{ op: 'set', path: [field], value: Math.min(Math.max(Math.floor(n), min), max) }]);
    }
  };

  const byProvider = (list: ModelOption[]) => {
    const out: Record<string, ModelOption[]> = {};
    list.forEach((m) => {
      const p = m.provider || 'other';
      (out[p] = out[p] || []).push(m);
    });
    return out;
  };

  const effective = model || appDefault || 'deepseek-chat';

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <div style={{ flex: 1, fontSize: 15, fontWeight: 500, color: t.textPrimary }}>
            {tr('dc_settings_title')}
          </div>
          {loading && <Loader size={13} className="animate-spin" color={t.textMuted} />}
          {saved && (
            <span style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 11.5, color: '#22c55e' }}>
              <CheckCircle size={12} /> saved
            </span>
          )}
        </div>
        <div style={{ marginTop: 4, fontSize: 12, lineHeight: '18px', color: t.textMuted }}>
          Which model answers questions about your knowledge bases. This is the setting the panel
          used to carry as a dropdown — it lives here now, so it is chosen once instead of every
          time you open the chat.
        </div>
      </div>

      <div>
        <div style={{ fontSize: 11, color: t.textMuted, marginBottom: 4 }}>{tr('dc_settings_model')}</div>
        <select
          value={model}
          onChange={(e) => onModelChange(e.target.value)}
          style={{
            width: 320, height: 30, padding: '0 8px', boxSizing: 'border-box',
            background: t.bg, border: `1px solid ${t.border}`, borderRadius: 8,
            color: t.textPrimary, fontSize: 12.5, outline: 'none',
          }}
        >
          <option value="">{tr('dc_app_default')}{appDefault ? ` — ${appDefault}` : ''}</option>
          {Object.entries(byProvider(cloud)).map(([provider, list]) => (
            <optgroup key={provider} label={provider}>
              {list.map((m) => (
                <option key={m.model_id} value={m.model_id}>
                  {m.display_name || m.model_id}
                </option>
              ))}
            </optgroup>
          ))}
          {local.length > 0 && (
            <optgroup label="local">
              {local.map((m: any) => (
                <option key={m.id ?? m.model_id} value={m.model_id ?? m.name}>
                  {m.display_name || m.name || m.model_id}
                </option>
              ))}
            </optgroup>
          )}
        </select>
        <div style={{ marginTop: 4, fontSize: 11, color: t.textMuted }}>
          {tr('dc_settings_effective')} <span style={{ fontFamily: 'monospace' }}>{effective}</span>
          {!model && ` ${tr('dc_settings_effective_default')}`}
        </div>
      </div>

      <div>
        <div style={{ fontSize: 11, color: t.textMuted, marginBottom: 4 }}>
          {tr('dc_settings_temperature')} <span style={{ opacity: 0.7 }}>{tr('dc_settings_optional')}</span>
        </div>
        <input
          value={temperature}
          placeholder={tr('dc_app_default')}
          onChange={(e) => onTemperature(e.target.value)}
          style={{
            width: 120, height: 30, padding: '0 8px', boxSizing: 'border-box',
            background: t.bg, border: `1px solid ${t.border}`, borderRadius: 8,
            color: t.textPrimary, fontSize: 12.5, outline: 'none',
          }}
        />
        <div style={{ marginTop: 4, fontSize: 11, color: t.textMuted }}>
          {tr('dc_settings_temp_hint')}
        </div>
      </div>

      {/* How much one answer may read. These were hard-coded in `api/knowledge/doc_chat.py`
          (MAX_FILES / MAX_CONTEXT_CHARS) until they moved here; the numbers below mirror that
          file's constants, which are now only the fallback used when a field is unset. */}
      <div>
        <div style={{ fontSize: 11, color: t.textMuted, marginBottom: 4 }}>
          {tr('dc_max_files')}
        </div>
        <input
          type="number"
          min={1}
          max={5000}
          value={maxFiles}
          placeholder={tr('dc_default_files')}
          onChange={(e) =>
            onLimit(e.target.value, 'doc_chat_max_files', 1, 5000, setMaxFiles)}
          style={{
            width: 160, height: 30, padding: '0 8px', boxSizing: 'border-box',
            background: t.bg, border: `1px solid ${t.border}`, borderRadius: 8,
            color: t.textPrimary, fontSize: 12.5, outline: 'none',
          }}
        />
        <div style={{ marginTop: 4, fontSize: 11, color: t.textMuted }}>
          {tr('dc_max_files_hint')}
        </div>
      </div>

      <div>
        <div style={{ fontSize: 11, color: t.textMuted, marginBottom: 4 }}>
          {tr('dc_max_context')}
        </div>
        <input
          type="number"
          min={10000}
          max={20000000}
          step={100000}
          value={maxContext}
          placeholder={tr('dc_default_context')}
          onChange={(e) =>
            onLimit(e.target.value, 'doc_chat_max_context_chars', 10_000, 20_000_000, setMaxContext)}
          style={{
            width: 200, height: 30, padding: '0 8px', boxSizing: 'border-box',
            background: t.bg, border: `1px solid ${t.border}`, borderRadius: 8,
            color: t.textPrimary, fontSize: 12.5, outline: 'none',
          }}
        />
        <div style={{ marginTop: 4, fontSize: 11, color: t.textMuted }}>
          {tr('dc_max_context_hint')}
        </div>
      </div>
    </div>
  );
}
