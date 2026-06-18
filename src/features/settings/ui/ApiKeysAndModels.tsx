/**
 * Dynamic API Keys & Models section.
 *
 * Reads providers and models from DB (models table).
 * Each provider shows: API key input, model list (read-only tags), add model form.
 */

import { useState, useEffect, useCallback } from 'react';
import { apiClient } from '@/lib/api-client';
import { fetchAndCacheModels } from '@/lib/modelCache';
import SettingsSection from './SettingsSection';

interface ModelEntry {
  model_id: string;
  display_name: string;
  provider: string;
  is_active: boolean;
}

interface ProviderGroup {
  provider: string;
  models: ModelEntry[];
}

export default function ApiKeysAndModels() {
  const [providers, setProviders] = useState<ProviderGroup[]>([]);
  const [loading, setLoading] = useState(true);

  // API key state per provider (read from backend)
  const [apiKeyInputs, setApiKeyInputs] = useState<Record<string, string>>({});
  const [apiKeyStatus, setApiKeyStatus] = useState<Record<string, boolean>>({});
  const [connectionStatus, setConnectionStatus] = useState<Record<string, { connected: boolean | null; message: string | null }>>({});
  const [saving, setSaving] = useState(false);
  const [saveMessage, setSaveMessage] = useState<string | null>(null);

  // Test connection state
  const [testingProvider, setTestingProvider] = useState<string | null>(null);
  const [testResults, setTestResults] = useState<Record<string, { success: boolean; message: string }>>({});

  // Add model form state
  const [addingForProvider, setAddingForProvider] = useState<string | null>(null);
  const [newModelId, setNewModelId] = useState('');
  const [newModelName, setNewModelName] = useState('');

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      // Fetch models
      const { cloudModels } = await fetchAndCacheModels();
      // Group by provider (lowercase keys for backend compatibility)
      const grouped: Record<string, ModelEntry[]> = {};
      for (const m of cloudModels) {
        const key = m.provider.toLowerCase();
        if (!grouped[key]) grouped[key] = [];
        grouped[key].push({
          model_id: m.id,
          display_name: m.name,
          provider: key,
          is_active: true,
        });
      }
      setProviders(
        Object.entries(grouped).map(([provider, models]) => ({ provider, models }))
      );

      // Fetch existing API keys + connection status
      const keysRes = await apiClient.getApiKeys();
      const keysData = keysRes.data || [];
      const status: Record<string, boolean> = {};
      const connection: Record<string, { connected: boolean | null; message: string | null }> = {};
      for (const k of keysData) {
        status[k.provider] = k.is_set;
        connection[k.provider] = { connected: k.connected, message: k.connected_message };
      }
      setApiKeyStatus(status);
      setConnectionStatus(connection);
    } catch (err) {
      console.error('Failed to load providers:', err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { loadData(); }, [loadData]);

  const handleTestConnection = async (provider: string) => {
    setTestingProvider(provider);
    setTestResults(prev => ({ ...prev, [provider]: { success: false, message: 'Testing...' } }));
    try {
      // Use newly entered key if provided, otherwise test with stored key
      const key = apiKeyInputs[provider]?.trim() || undefined;
      const res = await apiClient.testApiKey(provider, key);
      const data = res.data;
      setTestResults(prev => ({ ...prev, [provider]: { success: data.success, message: data.message } }));
      // Persist the connection status so the badge updates
      setConnectionStatus(prev => ({
        ...prev,
        [provider]: { connected: data.success, message: data.message }
      }));
      // Clear result after 8 seconds
      setTimeout(() => setTestResults(prev => {
        const next = { ...prev };
        delete next[provider];
        return next;
      }), 8000);
    } catch (err: any) {
      setTestResults(prev => ({ ...prev, [provider]: { success: false, message: err?.response?.data?.detail || err?.message || 'Connection test failed' } }));
    } finally {
      setTestingProvider(null);
    }
  };

  const handleSaveApiKeys = async () => {
    const keysToSave: Parameters<typeof apiClient.setApiKeys>[0] = {};
    for (const [provider, key] of Object.entries(apiKeyInputs)) {
      if (key.trim()) {
        (keysToSave as Record<string, string>)[`${provider}_api_key`] = key.trim();
      }
    }
    if (Object.keys(keysToSave).length === 0) {
      setSaveMessage('Enter at least one API key to save');
      setTimeout(() => setSaveMessage(null), 3000);
      return;
    }

    setSaving(true);
    setSaveMessage(null);
    try {
      await apiClient.setApiKeys(keysToSave);
      await fetchAndCacheModels();
      setApiKeyInputs({});
      // Reset connection status for updated providers — they need re-testing
      setConnectionStatus(prev => {
        const next = { ...prev };
        for (const [p, v] of Object.entries(apiKeyInputs)) {
          if (v.trim()) {
            next[p] = { connected: null, message: null };
          }
        }
        return next;
      });
      setSaveMessage('API keys saved successfully!');
      setTimeout(() => setSaveMessage(null), 3000);
      await loadData();
    } catch (err) {
      console.error('Failed to save API keys:', err);
      setSaveMessage('Failed to save API keys');
      setTimeout(() => setSaveMessage(null), 5000);
    } finally {
      setSaving(false);
    }
  };

  const handleAddModel = async (provider: string) => {
    if (!newModelId.trim() || !newModelName.trim()) return;
    try {
      await apiClient.createModel({
        model_id: newModelId.trim(),
        display_name: newModelName.trim(),
        provider,
      });
      setNewModelId('');
      setNewModelName('');
      setAddingForProvider(null);
      await loadData();
      await fetchAndCacheModels();
    } catch (err: any) {
      alert(err?.response?.data?.detail || 'Failed to add model');
    }
  };

  const handleDeleteModel = async (modelId: string) => {
    if (!confirm(`Delete model "${modelId}"?`)) return;
    try {
      await apiClient.deleteModel(modelId);
      await loadData();
      await fetchAndCacheModels();
    } catch (err) {
      console.error('Failed to delete model:', err);
    }
  };

  if (loading) {
    return <div className="text-sm py-4 text-gray-500">Loading providers...</div>;
  }

  // Search tools that always appear (no model dependency)
  const searchProviders = ['tavily', 'serper'];

  return (
    <SettingsSection
      title="API Keys & Models"
      description="Manage API keys and models per provider. Models are read from the database."
      icon="key"
    >
      <div className="space-y-6">
        {/* ── LLM / Model providers ── */}
        {providers.map(({ provider, models }) => (
          <div key={provider} className="border border-gray-200 dark:border-border-dark rounded-lg p-4">
            {/* Provider header */}
            <div className="flex items-center justify-between mb-3">
              <h4 className="text-sm font-semibold capitalize" style={{ color: 'var(--color-text-primary)' }}>
                {provider}
              </h4>
              {connectionStatus[provider]?.connected === true ? (
                <span className="text-xs px-2 py-0.5 rounded-full bg-green-100 dark:bg-green-500/20 text-green-700 dark:text-green-400" title={connectionStatus[provider]?.message || ''}>
                  ✓ Connected
                </span>
              ) : apiKeyStatus[provider] ? (
                <span className="text-xs px-2 py-0.5 rounded-full bg-amber-100 dark:bg-amber-500/20 text-amber-700 dark:text-amber-400" title={connectionStatus[provider]?.message || ''}>
                  Key set (not tested)
                </span>
              ) : (
                <span className="text-xs px-2 py-0.5 rounded-full bg-gray-100 dark:bg-gray-500/20 text-gray-600 dark:text-gray-400">
                  No key
                </span>
              )}
            </div>

            {/* API Key input + test button */}
            <div className="flex gap-2 mb-3">
              <input
                type="password"
                value={apiKeyInputs[provider] || ''}
                onChange={(e) => setApiKeyInputs({ ...apiKeyInputs, [provider]: e.target.value })}
                placeholder={apiKeyStatus[provider] ? 'Enter new key to replace' : 'Enter API key...'}
                className="flex-1 px-3 py-2 text-sm border border-gray-300 dark:border-border-dark rounded-lg focus:outline-none focus:ring-2 focus:ring-primary font-mono"
                style={{
                  backgroundColor: 'var(--color-input-background)',
                  color: 'var(--color-text-primary)',
                }}
              />
              <button
                onClick={() => handleTestConnection(provider)}
                disabled={testingProvider === provider}
                className="px-3 py-2 text-xs font-medium border border-gray-300 dark:border-border-dark rounded-lg hover:bg-gray-100 dark:hover:bg-white/5 transition-colors disabled:opacity-50 flex items-center gap-1.5 shrink-0"
                style={{ color: 'var(--color-text-secondary)' }}
                title="Test connection with entered or saved API key"
              >
                {testingProvider === provider ? (
                  <><div className="w-3.5 h-3.5 border-2 border-gray-400 border-t-transparent rounded-full animate-spin" /> Testing</>
                ) : (
                  <><span className="material-symbols-outlined text-sm">network_check</span> Test</>
                )}
              </button>
            </div>
            {/* Test result */}
            {testResults[provider] && (
              <div className={`mb-3 px-3 py-1.5 text-xs rounded-lg ${
                testResults[provider].success
                  ? 'bg-green-100 dark:bg-green-500/10 text-green-700 dark:text-green-400 border border-green-200 dark:border-green-500/20'
                  : 'bg-red-100 dark:bg-red-500/10 text-red-700 dark:text-red-400 border border-red-200 dark:border-red-500/20'
              }`}>
                {testResults[provider].message}
              </div>
            )}

            {/* Models list */}
            <div className="mb-2">
              <div className="flex items-center justify-between mb-1">
                <span className="text-xs font-medium" style={{ color: 'var(--color-text-muted)' }}>
                  Models ({models.length})
                </span>
                <button
                  onClick={() => setAddingForProvider(addingForProvider === provider ? null : provider)}
                  className="text-xs px-2 py-1 rounded hover:bg-gray-100 dark:hover:bg-white/10 transition-colors"
                  style={{ color: 'var(--color-text-muted)' }}
                >
                  + Add model
                </button>
              </div>
              <div className="flex flex-wrap gap-1.5">
                {models.map((m) => (
                  <span
                    key={m.model_id}
                    className="inline-flex items-center gap-1 px-2 py-0.5 text-xs rounded-full bg-gray-100 dark:bg-white/5"
                    style={{ color: 'var(--color-text-secondary)' }}
                  >
                    {m.model_id}
                    <button
                      onClick={() => handleDeleteModel(m.model_id)}
                      className="hover:text-red-500 transition-colors"
                      title="Delete model"
                    >
                      ×
                    </button>
                  </span>
                ))}
              </div>
            </div>

            {/* Add model form */}
            {addingForProvider === provider && (
              <div className="flex gap-2 items-start mt-2 p-2 bg-gray-50 dark:bg-white/5 rounded">
                <div className="flex-1 space-y-1">
                  <input
                    value={newModelId}
                    onChange={(e) => setNewModelId(e.target.value)}
                    placeholder="Model ID (e.g. my-model-v1)"
                    className="w-full px-2 py-1 text-xs border border-gray-300 dark:border-border-dark rounded focus:outline-none focus:ring-1 focus:ring-primary"
                    style={{ backgroundColor: 'var(--color-input-background)', color: 'var(--color-text-primary)' }}
                  />
                  <input
                    value={newModelName}
                    onChange={(e) => setNewModelName(e.target.value)}
                    placeholder="Display name (e.g. My Model V1)"
                    className="w-full px-2 py-1 text-xs border border-gray-300 dark:border-border-dark rounded focus:outline-none focus:ring-1 focus:ring-primary"
                    style={{ backgroundColor: 'var(--color-input-background)', color: 'var(--color-text-primary)' }}
                  />
                </div>
                <button
                  onClick={() => handleAddModel(provider)}
                  disabled={!newModelId.trim() || !newModelName.trim()}
                  className="px-3 py-1.5 text-xs font-medium bg-primary text-white rounded hover:bg-primary/90 disabled:opacity-50"
                >
                  Add
                </button>
              </div>
            )}
          </div>
        ))}

        {/* ── Search Tools (always visible, no model dependency) ── */}
        <div className="pt-4 border-t border-gray-200 dark:border-border-dark">
          <h3 className="text-sm font-semibold mb-3" style={{ color: 'var(--color-text-primary)' }}>
            Search Tools
          </h3>
          <div className="text-xs mb-3" style={{ color: 'var(--color-text-muted)' }}>
            API keys for web search services (Tavily, Serper)
          </div>
          {searchProviders.map((provider) => (
            <div key={provider} className="border border-gray-200 dark:border-border-dark rounded-lg p-4 mb-3">
              {/* Header with connection badge */}
              <div className="flex items-center justify-between mb-3">
                <h4 className="text-sm font-semibold capitalize" style={{ color: 'var(--color-text-primary)' }}>
                  {provider}
                </h4>
                {connectionStatus[provider]?.connected === true ? (
                  <span className="text-xs px-2 py-0.5 rounded-full bg-green-100 dark:bg-green-500/20 text-green-700 dark:text-green-400" title={connectionStatus[provider]?.message || ''}>
                    ✓ Connected
                  </span>
                ) : apiKeyStatus[provider] ? (
                  <span className="text-xs px-2 py-0.5 rounded-full bg-amber-100 dark:bg-amber-500/20 text-amber-700 dark:text-amber-400" title={connectionStatus[provider]?.message || ''}>
                    Key set (not tested)
                  </span>
                ) : (
                  <span className="text-xs px-2 py-0.5 rounded-full bg-gray-100 dark:bg-gray-500/20 text-gray-600 dark:text-gray-400">
                    No key
                  </span>
                )}
              </div>
              {/* API Key input + test button */}
              <div className="flex gap-2">
                <input
                  type="password"
                  value={apiKeyInputs[provider] || ''}
                  onChange={(e) => setApiKeyInputs({ ...apiKeyInputs, [provider]: e.target.value })}
                  placeholder={apiKeyStatus[provider] ? 'Enter new key to replace' : 'Enter API key...'}
                  className="flex-1 px-3 py-2 text-sm border border-gray-300 dark:border-border-dark rounded-lg focus:outline-none focus:ring-2 focus:ring-primary font-mono"
                  style={{
                    backgroundColor: 'var(--color-input-background)',
                    color: 'var(--color-text-primary)',
                  }}
                />
                <button
                  onClick={() => handleTestConnection(provider)}
                  disabled={testingProvider === provider}
                  className="px-3 py-2 text-xs font-medium border border-gray-300 dark:border-border-dark rounded-lg hover:bg-gray-100 dark:hover:bg-white/5 transition-colors disabled:opacity-50 flex items-center gap-1.5 shrink-0"
                  style={{ color: 'var(--color-text-secondary)' }}
                  title="Test connection with entered or saved API key"
                >
                  {testingProvider === provider ? (
                    <><div className="w-3.5 h-3.5 border-2 border-gray-400 border-t-transparent rounded-full animate-spin" /> Testing</>
                  ) : (
                    <><span className="material-symbols-outlined text-sm">network_check</span> Test</>
                  )}
                </button>
              </div>
              {/* Test result */}
              {testResults[provider] && (
                <div className={`mt-2 px-3 py-1.5 text-xs rounded-lg ${
                  testResults[provider].success
                    ? 'bg-green-100 dark:bg-green-500/10 text-green-700 dark:text-green-400 border border-green-200 dark:border-green-500/20'
                    : 'bg-red-100 dark:bg-red-500/10 text-red-700 dark:text-red-400 border border-red-200 dark:border-red-500/20'
                }`}>
                  {testResults[provider].message}
                </div>
              )}
            </div>
          ))}
        </div>

        {/* Save button */}
        <div className="pt-4 border-t border-gray-200 dark:border-border-dark">
          <div className="flex items-center gap-3">
            <button
              onClick={handleSaveApiKeys}
              disabled={saving || Object.values(apiKeyInputs).every(v => !v.trim())}
              className="px-4 py-2 text-sm font-medium bg-primary text-white rounded-lg hover:bg-primary/90 transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
            >
              {saving ? (
                <><div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" /> Saving...</>
              ) : (
                <><span className="material-symbols-outlined text-base">save</span> Save API Keys</>
              )}
            </button>
            {saveMessage && (
              <span className={`text-sm ${saveMessage.includes('successfully') ? 'text-green-600' : 'text-amber-600'}`}>
                {saveMessage}
              </span>
            )}
          </div>
        </div>
      </div>
    </SettingsSection>
  );
}
