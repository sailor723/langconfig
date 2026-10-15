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
  const [model, setModel] = useState('');                 // '' = follow the app default
  const [temperature, setTemperature] = useState('');     // '' = follow the app default
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
      setAppDefault(modelsNs?.value?.default_model || '');
      setCloud(models?.data?.cloud_models || []);
      setLocal(models?.data?.local_models || []);
    } catch (err) {
      console.error('Failed to load doc chat settings:', err);
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
      console.error('Failed to save doc chat settings:', err);
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
            Doc chat
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
        <div style={{ fontSize: 11, color: t.textMuted, marginBottom: 4 }}>Model</div>
        <select
          value={model}
          onChange={(e) => onModelChange(e.target.value)}
          style={{
            width: 320, height: 30, padding: '0 8px', boxSizing: 'border-box',
            background: t.bg, border: `1px solid ${t.border}`, borderRadius: 8,
            color: t.textPrimary, fontSize: 12.5, outline: 'none',
          }}
        >
          <option value="">App default{appDefault ? ` — ${appDefault}` : ''}</option>
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
          Doc chat currently answers with <span style={{ fontFamily: 'monospace' }}>{effective}</span>
          {!model && ' (the app default, from Settings → Models)'}.
        </div>
      </div>

      <div>
        <div style={{ fontSize: 11, color: t.textMuted, marginBottom: 4 }}>
          Temperature <span style={{ opacity: 0.7 }}>(optional)</span>
        </div>
        <input
          value={temperature}
          placeholder={appDefault ? 'app default' : 'app default (0)'}
          onChange={(e) => onTemperature(e.target.value)}
          style={{
            width: 120, height: 30, padding: '0 8px', boxSizing: 'border-box',
            background: t.bg, border: `1px solid ${t.border}`, borderRadius: 8,
            color: t.textPrimary, fontSize: 12.5, outline: 'none',
          }}
        />
        <div style={{ marginTop: 4, fontSize: 11, color: t.textMuted }}>
          Empty follows the app default. Answers about documents are usually better at 0.
        </div>
      </div>
    </div>
  );
}
