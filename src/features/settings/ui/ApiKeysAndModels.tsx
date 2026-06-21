/**
 * API Keys & Models section.
 *
 * API keys are now managed via .env file — this panel shows them read-only.
 * Models are listed from the database.
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

  // API key status (read-only from backend, which reads from .env)
  const [apiKeyStatus, setApiKeyStatus] = useState<Record<string, boolean>>({});
  const [maskedKeys, setMaskedKeys] = useState<Record<string, string | null>>({});
  const [connectionStatus, setConnectionStatus] = useState<Record<string, { connected: boolean | null; message: string | null }>>({});

  // Test connection state
  const [testingProvider, setTestingProvider] = useState<string | null>(null);
  const [testResults, setTestResults] = useState<Record<string, { success: boolean; message: string }>>({});

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      // Fetch models
      const { cloudModels } = await fetchAndCacheModels();
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

      // Fetch API key status from backend (reads from .env)
      const keysRes = await apiClient.getApiKeys();
      const keysData = keysRes.data || [];
      const status: Record<string, boolean> = {};
      const masked: Record<string, string | null> = {};
      const connection: Record<string, { connected: boolean | null; message: string | null }> = {};
      for (const k of keysData) {
        status[k.provider] = k.is_set;
        masked[k.provider] = k.masked_key;
        connection[k.provider] = { connected: k.connected, message: k.connected_message };
      }
      setApiKeyStatus(status);
      setMaskedKeys(masked);
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
      const res = await apiClient.testApiKey(provider);
      const data = res.data;
      setTestResults(prev => ({ ...prev, [provider]: { success: data.success, message: data.message } }));
      setConnectionStatus(prev => ({
        ...prev,
        [provider]: { connected: data.success, message: data.message }
      }));
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

  if (loading) {
    return <div className="p-4 text-sm" style={{ color: 'var(--color-text-muted)' }}>Loading...</div>;
  }

  return (
    <div className="space-y-6">
      {/* Banner */}
      <div
        className="rounded-lg px-4 py-3 flex items-start gap-3 text-sm border"
        style={{
          backgroundColor: 'rgba(99,102,241,0.08)',
          borderColor: 'rgba(99,102,241,0.2)',
        }}
      >
        <span className="material-symbols-outlined text-base shrink-0 mt-0.5" style={{ color: 'var(--color-primary)' }}>info</span>
        <div>
          <p className="font-medium" style={{ color: 'var(--color-text-primary)' }}>API Keys from .env</p>
          <p className="mt-0.5" style={{ color: 'var(--color-text-muted)' }}>
            API keys are now managed via the <code>.env</code> file at the project root.
            Edit the file directly to add or update keys, then restart the server.
          </p>
        </div>
      </div>

      {/* Provider Cards — read only */}
      <SettingsSection title="Provider Keys" description="Current API key status (read from .env)">
        <div className="space-y-3">
          {providers.map(({ provider }) => {
            const isSet = apiKeyStatus[provider];
            const masked = maskedKeys[provider];
            const conn = connectionStatus[provider];
            const testResult = testResults[provider];

            return (
              <div
                key={provider}
                className="rounded-lg p-3 border"
                style={{
                  backgroundColor: 'var(--color-input-background)',
                  borderColor: 'var(--color-border)',
                }}
              >
                <div className="flex items-center justify-between mb-2">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium capitalize" style={{ color: 'var(--color-text-primary)' }}>{provider}</span>
                    {isSet ? (
                      <span className="text-[10px] px-1.5 py-0.5 rounded-full font-medium" style={{ backgroundColor: 'rgba(16,185,129,0.15)', color: '#10b981' }}>Set</span>
                    ) : (
                      <span className="text-[10px] px-1.5 py-0.5 rounded-full font-medium" style={{ backgroundColor: 'rgba(239,68,68,0.1)', color: '#ef4444' }}>Not set</span>
                    )}
                    {conn?.connected === true && <span className="text-[10px] text-emerald-500">✓ Connected</span>}
                    {conn?.connected === false && <span className="text-[10px] text-red-400" title={conn.message || ''}>✗ Failed</span>}
                  </div>
                  <button
                    onClick={() => handleTestConnection(provider)}
                    disabled={testingProvider === provider || !isSet}
                    className="text-xs px-2.5 py-1 rounded-lg border transition-colors disabled:opacity-40"
                    style={{
                      borderColor: 'var(--color-border)',
                      color: 'var(--color-text-muted)',
                    }}
                  >
                    {testingProvider === provider ? (
                      <span className="flex items-center gap-1">
                        <span className="w-3 h-3 border-2 rounded-full animate-spin" style={{ borderColor: 'var(--color-border)', borderTopColor: 'var(--color-primary)' }} />
                        Testing...
                      </span>
                    ) : 'Test'}
                  </button>
                </div>

                {isSet && masked && (
                  <div className="font-mono text-xs px-2.5 py-1.5 rounded" style={{ backgroundColor: 'var(--color-background)', color: 'var(--color-text-muted)' }}>
                    {masked}
                  </div>
                )}

                {/* Test result */}
                {testResult && (
                  <div className={`mt-2 text-xs px-2.5 py-1.5 rounded flex items-start gap-1.5 ${testResult.success ? 'text-emerald-500' : 'text-red-400'}`}
                    style={{
                      backgroundColor: testResult.success ? 'rgba(16,185,129,0.08)' : 'rgba(239,68,68,0.08)',
                    }}
                  >
                    <span className="material-symbols-outlined text-xs">{testResult.success ? 'check_circle' : 'error'}</span>
                    {testResult.message}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </SettingsSection>

      {/* Models (read-only) */}
      {providers.map(({ provider, models }) => (
        <div key={provider} className="mb-4">
          <h4 className="text-xs font-semibold uppercase tracking-wider mb-2 capitalize" style={{ color: 'var(--color-text-muted)' }}>{provider}</h4>
          <div className="flex flex-wrap gap-1.5">
            {models.map(m => (
              <span
                key={m.model_id}
                className="text-xs px-2 py-0.5 rounded-full border"
                style={{
                  backgroundColor: 'var(--color-background)',
                  borderColor: 'var(--color-border)',
                  color: 'var(--color-text-primary)',
                }}
              >
                {m.display_name}
              </span>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}
