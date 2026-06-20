/**
 * Copyright (c) 2025 Cade Russell (Ghost Peony)
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */

import { useState, useEffect, useRef, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import apiClient from '../lib/api-client';
import { themes, applyTheme, loadTheme, type ThemeName } from '../lib/themes';
import LanguageSwitcher from '../i18n/LanguageSwitcher';
import SettingsLayout, { SettingsCategory } from "../features/settings/ui/SettingsLayout";
import LocalModelsSettings from "../features/settings/ui/LocalModelsSettings";
import LocalWorkspaceSettings from "../features/settings/ui/LocalWorkspaceSettings";
import ModelDefaultsSettings from '../features/settings/ui/ModelDefaultsSettings';
import ApiKeysAndModels from '../features/settings/ui/ApiKeysAndModels';
import SettingsSection, { SettingsInput, SettingsSelect } from '../features/settings/ui/SettingsSection';
import { fetchAndCacheModels } from '../lib/modelCache';

export default function SettingsView() {
  const { t } = useTranslation('chat');
  const [currentCategory, setCurrentCategory] = useState<SettingsCategory>('general');
  const [isLoading, setIsLoading] = useState(true);
  const saveTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // API Keys state - separate "is set" status from user input
  const [apiKeys, setApiKeys] = useState({
    anthropic: '',
    openai: '',
    google: '',
    deepseek: '',
    glm: '',
    minimax: '',
    tavily: '',
    agnes: '',
    agnesBaseUrl: '',
  });
  const [apiKeyStatus, setApiKeyStatus] = useState({
    anthropic: false,
    openai: false,
    google: false,
    deepseek: false,
    glm: false,
    minimax: false,
    tavily: false,
    agnes: false,
  });
  const [apiKeyConnection, setApiKeyConnection] = useState<Record<string, { connected: boolean | null; message: string | null }>>({});
  const [apiKeySaving, setApiKeySaving] = useState(false);
  const [apiKeySaveMessage, setApiKeySaveMessage] = useState<string | null>(null);
  const [testingProvider, setTestingProvider] = useState<string | null>(null);
  const [testResults, setTestResults] = useState<Record<string, { success: boolean; message: string }>>({});

  // Theme state
  const [currentTheme, setCurrentTheme] = useState<ThemeName>('dark');

  // Type definitions for settings
  interface LocalModelsSettings {
    provider: string;
    baseUrl: string;
    modelName: string;
    apiKey: string;
  }

  interface WorkspaceSettings {
    workspacePath: string;
    allowRead: boolean;
    allowWrite: boolean;
    requireApproval: boolean;
    autoDetectGit: boolean;
    backupBeforeEdit: boolean;
  }

  interface ModelDefaultsSettings {
    primaryModel: string;
    fallbackModels: string[];
    temperature: number;
    maxTokens: number;
    topP: number;
    routingStrategy: string;
    dailyTokenLimit: number;
    monthlyTokenLimit: number;
    alertThreshold: number;
  }

  interface GeneralSettings {
    appName: string;
    storagePath: string;
    language: string;
    autoSave: boolean;
    autoSaveInterval: number;
    confirmBeforeDelete: boolean;
    showNotifications: boolean;
    checkUpdates: boolean;
    telemetry: boolean;
    logLevel: string;
  }

  interface RagSettings {
    embeddingModel: string;
    chunkSize: number;
    chunkOverlap: number;
  }

  // Local Models state - start with null, load from backend
  const [localModelsSettings, setLocalModelsSettings] = useState<LocalModelsSettings | null>(null);

  // Local Workspace state - start with null, load from backend
  const [workspaceSettings, setWorkspaceSettings] = useState<WorkspaceSettings | null>(null);

  // Model Defaults state - start with null, load from backend
  const [modelDefaultsSettings, setModelDefaultsSettings] = useState<ModelDefaultsSettings | null>(null);
  const [savingEmbedding, setSavingEmbedding] = useState(false);

  // General settings state - start with null, load from backend
  const [generalSettings, setGeneralSettings] = useState<GeneralSettings>({
    appName: 'LangConfig',
    language: 'en',
    autoSave: true,
    autoSaveInterval: 300,
    confirmBeforeDelete: true,
    showNotifications: true,
    checkUpdates: true,
    telemetry: false,
    logLevel: 'info',
    storagePath: ''
  });

  // RAG settings state - start with null, load from backend
  const [ragSettings, setRagSettings] = useState<RagSettings | null>(null);
  const [embeddingModels, setEmbeddingModels] = useState<{id: string; name: string; provider: string; type: string}[]>([]);

  useEffect(() => {
    const abortController = new AbortController();

    loadSettings();
    const theme = loadTheme();
    setCurrentTheme(theme.name);

    return () => {
      abortController.abort();
    };
  }, []);

  const loadSettings = async () => {
    try {
      // Load API keys status (don't load masked keys into inputs!)
      const res = await apiClient.getApiKeys();
      const keys = res.data || [];
      setApiKeyStatus({
        anthropic: keys.find((k: any) => k.provider === 'anthropic')?.is_set || false,
        openai: keys.find((k: any) => k.provider === 'openai')?.is_set || false,
        google: keys.find((k: any) => k.provider === 'google')?.is_set || false,
        deepseek: keys.find((k: any) => k.provider === 'deepseek')?.is_set || false,
        glm: keys.find((k: any) => k.provider === 'glm')?.is_set || false,
        minimax: keys.find((k: any) => k.provider === 'minimax')?.is_set || false,
        tavily: keys.find((k: any) => k.provider === 'tavily')?.is_set || false,
        agnes: keys.find((k: any) => k.provider === 'agnes')?.is_set || false,
      });
      setApiKeyConnection({
        anthropic: keys.find((k: any) => k.provider === 'anthropic'),
        openai: keys.find((k: any) => k.provider === 'openai'),
        google: keys.find((k: any) => k.provider === 'google'),
        deepseek: keys.find((k: any) => k.provider === 'deepseek'),
        glm: keys.find((k: any) => k.provider === 'glm'),
        minimax: keys.find((k: any) => k.provider === 'minimax'),
        tavily: keys.find((k: any) => k.provider === 'tavily'),
        agnes: keys.find((k: any) => k.provider === 'agnes'),
      });
      // Keep input fields empty - user types new key to update
      setApiKeys({
        anthropic: '',
        openai: '',
        google: '',
        deepseek: '',
        glm: '',
        minimax: '',
        tavily: '',
        agnes: '',
        agnesBaseUrl: '',
      });

      // Load general settings
      try {
        const generalResponse = await apiClient.getGeneralSettings();
        const generalData = generalResponse.data;
        setGeneralSettings({
          appName: generalData.app_name || 'LangConfig',
          language: generalData.language || 'en',
          autoSave: generalData.auto_save ?? true,
          autoSaveInterval: generalData.auto_save_interval || 300,
          confirmBeforeDelete: generalData.confirm_before_delete ?? true,
          showNotifications: generalData.show_notifications ?? true,
          checkUpdates: generalData.check_updates ?? true,
          telemetry: generalData.telemetry ?? false,
          logLevel: generalData.log_level || 'info',
          storagePath: generalData.storage_path || ''
        });
        // Load theme from backend (overrides localStorage)
        if (generalData.theme && themes[generalData.theme as ThemeName]) {
          const themeName = generalData.theme as ThemeName;
          const theme = themes[themeName];
          applyTheme(theme);
          setCurrentTheme(themeName);
        }
      } catch (error) {
      }

      // Load local models settings
      try {
        const localModelsResponse = await apiClient.getLocalModelsSettings();
        const localModelsData = localModelsResponse.data;
        setLocalModelsSettings({
          provider: localModelsData.provider || 'ollama',
          baseUrl: localModelsData.base_url || 'http://localhost:11434/v1',
          modelName: localModelsData.model_name || 'llama3.2:latest',
          apiKey: localModelsData.api_key || ''
        });
      } catch (error) {
      }

      // Load workspace settings
      try {
        const workspaceResponse = await apiClient.getWorkspaceSettings();
        const workspaceData = workspaceResponse.data;
        setWorkspaceSettings({
          workspacePath: workspaceData.workspace_path || '',
          allowRead: workspaceData.allow_read ?? true,
          allowWrite: workspaceData.allow_write ?? true,
          requireApproval: workspaceData.require_approval ?? true,
          autoDetectGit: workspaceData.auto_detect_git ?? true,
          backupBeforeEdit: workspaceData.backup_before_edit ?? true
        });
      } catch (error) {
      }

      // Load model defaults settings
      try {
        const modelDefaultsResponse = await apiClient.getModelDefaults();
        const modelDefaultsData = modelDefaultsResponse.data;
        setModelDefaultsSettings({
          primaryModel: modelDefaultsData.primary_model || 'gpt-4o',
          fallbackModels: modelDefaultsData.fallback_models || ['claude-sonnet-4-5'],
          temperature: modelDefaultsData.temperature ?? 0.7,
          maxTokens: modelDefaultsData.max_tokens || 4096,
          topP: modelDefaultsData.top_p ?? 1.0,
          routingStrategy: modelDefaultsData.routing_strategy || 'balanced',
          dailyTokenLimit: modelDefaultsData.daily_token_limit || 0,
          monthlyTokenLimit: modelDefaultsData.monthly_token_limit || 0,
          alertThreshold: modelDefaultsData.alert_threshold || 80
        });
      } catch (error) {
      }

      // Load RAG settings from main settings endpoint
      try {
        const settingsResponse = await apiClient.getSettings();
        const settingsData = settingsResponse.data;
        setRagSettings({
          embeddingModel: settingsData.embedding_model || 'text-embedding-3-small',
          chunkSize: settingsData.chunk_size || 1000,
          chunkOverlap: settingsData.chunk_overlap || 200
        });
      } catch (error) {
        console.error('Failed to load RAG settings:', error);
      }

      // Load available embedding models
      try {
        const embResponse = await apiClient.getAvailableEmbeddingModels();
        setEmbeddingModels(embResponse.data.models || []);
      } catch (error) {
        console.error('Failed to load embedding models:', error);
      }

    } catch (error) {
      // Ignore abort errors
      if (error instanceof Error && (error.name === 'AbortError' || error.name === 'CanceledError')) {
        return;
      }
      console.error('Failed to load settings:', error);
    } finally {
      setIsLoading(false);
    }
  };

  // Debounced autosave function
  const autoSave = useCallback((category: SettingsCategory) => {
    // Clear existing timeout
    if (saveTimeoutRef.current) {
      clearTimeout(saveTimeoutRef.current);
    }

    // Set new timeout to save after 1 second of no changes
    saveTimeoutRef.current = setTimeout(async () => {
      try {
        switch (category) {
          case 'api-keys':
            await apiClient.setApiKeys({
              anthropic_api_key: apiKeys.anthropic || undefined,
              openai_api_key: apiKeys.openai || undefined,
              google_api_key: apiKeys.google || undefined,
              deepseek_api_key: apiKeys.deepseek || undefined,
              glm_api_key: apiKeys.glm || undefined,
              minimax_api_key: apiKeys.minimax || undefined,
              tavily_api_key: apiKeys.tavily || undefined,
              agnes_api_key: apiKeys.agnes || undefined,
              agnes_base_url: apiKeys.agnesBaseUrl || undefined,
            });
            break;

          case 'general':
            if (!generalSettings) return;
            await apiClient.updateGeneralSettings({
              app_name: generalSettings.appName,
              language: generalSettings.language,
              auto_save: generalSettings.autoSave,
              auto_save_interval: generalSettings.autoSaveInterval,
              confirm_before_delete: generalSettings.confirmBeforeDelete,
              show_notifications: generalSettings.showNotifications,
              check_updates: generalSettings.checkUpdates,
              telemetry: generalSettings.telemetry,
              log_level: generalSettings.logLevel
            });
            // Also save RAG settings to main settings endpoint
            if (ragSettings) {
              await apiClient.updateSettings({
                embedding_model: ragSettings.embeddingModel,
                chunk_size: ragSettings.chunkSize,
                chunk_overlap: ragSettings.chunkOverlap
              });
            }
            break;

          case 'local-models':
            if (!localModelsSettings) return;
            await apiClient.updateLocalModelsSettings({
              provider: localModelsSettings.provider,
              base_url: localModelsSettings.baseUrl,
              model_name: localModelsSettings.modelName,
              api_key: localModelsSettings.apiKey || null
            });
            break;

          case 'local-workspace':
            if (!workspaceSettings) return;
            await apiClient.updateWorkspaceSettings({
              workspace_path: workspaceSettings.workspacePath,
              allow_read: workspaceSettings.allowRead,
              allow_write: workspaceSettings.allowWrite,
              require_approval: workspaceSettings.requireApproval,
              auto_detect_git: workspaceSettings.autoDetectGit,
              backup_before_edit: workspaceSettings.backupBeforeEdit
            });
            break;

          case 'embedding':
            if (!ragSettings) return;
            await apiClient.updateSettings({
              embedding_model: ragSettings.embeddingModel,
              chunk_size: ragSettings.chunkSize,
              chunk_overlap: ragSettings.chunkOverlap
            });
            break;

          case 'model-defaults':
            if (!modelDefaultsSettings) return;
            await apiClient.updateModelDefaultsSettings({
              primary_model: modelDefaultsSettings.primaryModel,
              fallback_models: modelDefaultsSettings.fallbackModels,
              temperature: modelDefaultsSettings.temperature,
              max_tokens: modelDefaultsSettings.maxTokens,
              top_p: modelDefaultsSettings.topP,
              routing_strategy: modelDefaultsSettings.routingStrategy,
              daily_token_limit: modelDefaultsSettings.dailyTokenLimit,
              monthly_token_limit: modelDefaultsSettings.monthlyTokenLimit,
              alert_threshold: modelDefaultsSettings.alertThreshold
            });
            break;
        }
      } catch (error) {
        console.error('Failed to autosave settings:', error);
      }
    }, 1000); // 1 second debounce
  }, [apiKeys, generalSettings, ragSettings, localModelsSettings, workspaceSettings, modelDefaultsSettings]);

  const handleTestConnection = async (provider: string) => {
    setTestingProvider(provider);
    setTestResults(prev => ({ ...prev, [provider]: { success: false, message: 'Testing...' } }));
    try {
      const res = await apiClient.testApiKey(provider);
      const data = res.data;
      setTestResults(prev => ({ ...prev, [provider]: { success: data.success, message: data.message } }));
      // Clear result after 8 seconds
      setTimeout(() => setTestResults(prev => {
        const next = { ...prev };
        delete next[provider];
        return next;
      }), 8000);
    } catch (err: any) {
      setTestResults(prev => ({ ...prev, [provider]: { success: false, message: err?.message || 'Connection test failed' } }));
    } finally {
      setTestingProvider(null);
    }
  };

  const handleThemeChange = (themeName: ThemeName) => {
    const theme = themes[themeName];
    applyTheme(theme);
    setCurrentTheme(themeName);
    // Save to backend DB
    try {
      apiClient.updateGeneralSettings({ theme: themeName });
    } catch {}
  };

  const renderCategoryContent = () => {
    switch (currentCategory) {
      case 'general':
        return (
          <div>
            <SettingsSection
              title={t('settings_application')}
              description={t('settings_application_desc')}
              icon="tune"
            >
              <div className="space-y-4">
                <div className="border-t border-gray-200 dark:border-border-dark pt-3 mt-3">
                  <h4 className="text-sm font-medium mb-2" style={{ color: 'var(--color-text-primary)' }}>
                    {t('settings_auto_save')}
                  </h4>
                  <div className="space-y-2.5">
                    <label className="flex items-center gap-3 cursor-pointer">
                      <input
                        type="checkbox"
                        checked={generalSettings.autoSave}
                        onChange={(e) => {
                          setGeneralSettings({ ...generalSettings, autoSave: e.target.checked });
                          autoSave('general');
                        }}
                        className="w-4 h-4 text-primary bg-white dark:bg-background-dark border-gray-300 dark:border-border-dark rounded focus:ring-2 focus:ring-primary"
                      />
                      <div className="flex-1">
                        <span className="text-sm font-medium" style={{ color: 'var(--color-text-primary)' }}>
                          {t('settings_auto_save_enable')}
                        </span>
                        <p className="text-xs" style={{ color: 'var(--color-text-muted)' }}>
                          {t('settings_auto_save_desc')}
                        </p>
                      </div>
                    </label>

                    {generalSettings.autoSave && (
                      <SettingsInput
                        label="Auto-save interval (seconds)"
                        type="number"
                        value={generalSettings.autoSaveInterval.toString()}
                        onChange={(value) => {
                          setGeneralSettings({ ...generalSettings, autoSaveInterval: parseInt(value) || 60 });
                          autoSave('general');
                        }}
                        description="How often to automatically save (minimum 30 seconds)"
                      />
                    )}
                  </div>
                </div>

                <div className="border-t border-gray-200 dark:border-border-dark pt-3 mt-3">
                  <h4 className="text-sm font-medium mb-2" style={{ color: 'var(--color-text-primary)' }}>
                    Notifications & Confirmations
                  </h4>
                  <div className="space-y-2.5">
                    <label className="flex items-center gap-3 cursor-pointer">
                      <input
                        type="checkbox"
                        checked={generalSettings.confirmBeforeDelete}
                        onChange={(e) => {
                          setGeneralSettings({ ...generalSettings, confirmBeforeDelete: e.target.checked });
                          autoSave('general');
                        }}
                        className="w-4 h-4 text-primary bg-white dark:bg-background-dark border-gray-300 dark:border-border-dark rounded focus:ring-2 focus:ring-primary"
                      />
                      <div className="flex-1">
                        <span className="text-sm font-medium" style={{ color: 'var(--color-text-primary)' }}>
                          Confirm before deleting
                        </span>
                        <p className="text-xs" style={{ color: 'var(--color-text-muted)' }}>
                          Show confirmation dialog before deleting workflows or agents
                        </p>
                      </div>
                    </label>

                    <label className="flex items-center gap-3 cursor-pointer">
                      <input
                        type="checkbox"
                        checked={generalSettings.showNotifications}
                        onChange={(e) => {
                          setGeneralSettings({ ...generalSettings, showNotifications: e.target.checked });
                          autoSave('general');
                        }}
                        className="w-4 h-4 text-primary bg-white dark:bg-background-dark border-gray-300 dark:border-border-dark rounded focus:ring-2 focus:ring-primary"
                      />
                      <div className="flex-1">
                        <span className="text-sm font-medium" style={{ color: 'var(--color-text-primary)' }}>
                          Show notifications
                        </span>
                        <p className="text-xs" style={{ color: 'var(--color-text-muted)' }}>
                          Display system notifications for workflow completion and errors
                        </p>
                      </div>
                    </label>
                  </div>
                </div>

                <div className="border-t border-gray-200 dark:border-border-dark pt-3 mt-3">
                  <h4 className="text-sm font-medium mb-2" style={{ color: 'var(--color-text-primary)' }}>
                    {t('settings_updates')}
                  </h4>
                  <div className="space-y-2.5">
                    <label className="flex items-center gap-3 cursor-pointer">
                      <input
                        type="checkbox"
                        checked={generalSettings.checkUpdates}
                        onChange={(e) => {
                          setGeneralSettings({ ...generalSettings, checkUpdates: e.target.checked });
                          autoSave('general');
                        }}
                        className="w-4 h-4 text-primary bg-white dark:bg-background-dark border-gray-300 dark:border-border-dark rounded focus:ring-2 focus:ring-primary"
                      />
                      <div className="flex-1">
                        <span className="text-sm font-medium" style={{ color: 'var(--color-text-primary)' }}>
                          {t('settings_check_updates')}
                        </span>
                        <p className="text-xs" style={{ color: 'var(--color-text-muted)' }}>
                          {t('settings_check_updates_desc')}
                        </p>
                      </div>
                    </label>

                    <label className="flex items-center gap-3 cursor-pointer">
                      <input
                        type="checkbox"
                        checked={generalSettings.telemetry}
                        onChange={(e) => {
                          setGeneralSettings({ ...generalSettings, telemetry: e.target.checked });
                          autoSave('general');
                        }}
                        className="w-4 h-4 text-primary bg-white dark:bg-background-dark border-gray-300 dark:border-border-dark rounded focus:ring-2 focus:ring-primary"
                      />
                      <div className="flex-1">
                        <span className="text-sm font-medium" style={{ color: 'var(--color-text-primary)' }}>
                          {t('settings_telemetry')}
                        </span>
                        <p className="text-xs" style={{ color: 'var(--color-text-muted)' }}>
                          {t('settings_telemetry_desc')}
                        </p>
                      </div>
                    </label>
                  </div>
                </div>

                <div className="border-t border-gray-200 dark:border-border-dark pt-3 mt-3">
                  <h4 className="text-sm font-medium mb-2" style={{ color: 'var(--color-text-primary)' }}>
                  {t('settings_language')}
                </h4>
                <div className="flex items-center gap-3">
                  <span className="text-sm" style={{ color: 'var(--color-text-muted)' }}>
                    {t('settings_language_label')}
                  </span>
                    <LanguageSwitcher />
                  </div>
                </div>
              </div>
            </SettingsSection>
          </div>
        );

      case 'api-keys':
        return <ApiKeysAndModels />;

      case 'local-models':
        return <LocalModelsSettings />;

      case 'local-workspace':
        if (!workspaceSettings) return null;
        return (
          <LocalWorkspaceSettings
            settings={workspaceSettings}
            onSettingsChange={(newSettings: WorkspaceSettings) => {
              setWorkspaceSettings(newSettings);
              autoSave('local-workspace');
            }}
          />
        );

      case 'embedding':
        if (!ragSettings) return null;
        return (
          <SettingsSection
            title={t('settings_embedding_title')}
            description={t('settings_embedding_desc')}
            icon="database"
          >
            <SettingsSelect
              label={t('settings_embedding_model')}
              value={ragSettings.embeddingModel}
              onChange={(value: string) => {
                setRagSettings({ ...ragSettings, embeddingModel: value });
              }}
              options={(() => {
                const opts = embeddingModels.map(m => ({
                  value: m.id,
                  label: `${m.name}${m.type === 'local' ? t('settings_embedding_local') : ''}`
                }));
                // Always include current value even if not in list
                if (ragSettings?.embeddingModel && !embeddingModels.some(m => m.id === ragSettings.embeddingModel)) {
                  opts.unshift({ value: ragSettings.embeddingModel, label: `${ragSettings.embeddingModel} (custom)` });
                }
                return opts.length > 0 ? opts : [{ value: 'text-embedding-3-small', label: 'text-embedding-3-small' }];
              })()}
              description={t('settings_embedding_model_desc')}
            />
            <SettingsInput
              label={t('settings_embedding_chunk_size')}
              type="number"
              value={ragSettings.chunkSize.toString()}
              onChange={(value) => {
                setRagSettings({ ...ragSettings, chunkSize: parseInt(value) || 1000 });
              }}
              description={t('settings_embedding_chunk_size_desc')}
            />
            <SettingsInput
              label={t('settings_embedding_chunk_overlap')}
              type="number"
              value={ragSettings.chunkOverlap.toString()}
              onChange={(value) => {
                setRagSettings({ ...ragSettings, chunkOverlap: parseInt(value) || 200 });
              }}
              description={t('settings_embedding_chunk_overlap_desc')}
            />
            <div className="pt-6 border-t border-gray-200 dark:border-border-dark">
              <div className="flex items-center gap-3">
                <button
                  onClick={async () => {
                    setSavingEmbedding(true);
                    await autoSave('embedding');
                    setSavingEmbedding(false);
                  }}
                  disabled={savingEmbedding}
                  className="px-8 py-2.5 text-sm font-semibold text-white rounded-lg hover:brightness-110 active:brightness-90 transition-all cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed shadow-sm"
                  style={{ backgroundColor: 'var(--color-primary)' }}
                >
                  {savingEmbedding ? 'Saving...' : 'Save'}
                </button>
                {!savingEmbedding && ragSettings && (
                  <span className="text-xs" style={{ color: 'var(--color-text-muted)' }}>
                    Changes apply to new document indexing
                  </span>
                )}
              </div>
            </div>
          </SettingsSection>
        );

      case 'model-defaults':
        if (!modelDefaultsSettings) return null;
        return (
          <div>
            <ModelDefaultsSettings
              settings={modelDefaultsSettings}
              onSettingsChange={(newSettings: ModelDefaultsSettings) => {
                setModelDefaultsSettings(newSettings);
                autoSave('model-defaults');
              }}
            />
            <SettingsSection
              title="Override Behavior"
              icon="info"
            >
              <div className="flex gap-3 p-4 bg-blue-50 dark:bg-blue-500/10 border border-blue-200 dark:border-blue-500/30 rounded-lg">
                <span className="material-symbols-outlined text-blue-600 dark:text-blue-400 text-xl">
                  info
                </span>
                <div>
                  <h5 className="text-sm font-semibold text-blue-800 dark:text-blue-400 mb-1">
                    Settings Hierarchy
                  </h5>
                  <p className="text-xs text-blue-700 dark:text-blue-400/80">
                    These are <strong>default settings</strong> used when creating new agents or workflows.
                    Each agent node can override these settings individually. Agent-specific configurations always take precedence over these defaults.
                  </p>
                </div>
              </div>
            </SettingsSection>
          </div>
        );

      case 'appearance':
        return (
          <SettingsSection
              title={t('settings_appearance_title')}
              description={t('settings_appearance_desc')}
            icon="palette"
          >
            <div>
              <label className="text-sm font-medium mb-3 block" style={{ color: 'var(--color-text-primary)' }}>
                {t('settings_color_theme')}
              </label>
              <div className="grid grid-cols-2 gap-3">
                {Object.values(themes).map((theme) => (
                  <button
                    key={theme.name}
                    onClick={() => handleThemeChange(theme.name)}
                    className="p-4 rounded-lg border-2 transition-all text-left hover:border-primary/50"
                    style={{
                      borderColor: currentTheme === theme.name
                        ? 'var(--color-primary)'
                        : 'var(--color-border-dark)',
                      backgroundColor: currentTheme === theme.name
                        ? 'var(--color-primary)' + '10'
                        : 'transparent'
                    }}
                  >
                    <div className="flex items-center gap-3">
                      <div className="flex gap-1">
                        <div
                          className="w-4 h-4 rounded-full"
                          style={{ backgroundColor: theme.colors.primary }}
                        />
                        <div
                          className="w-4 h-4 rounded-full"
                          style={{ backgroundColor: theme.colors.backgroundDark }}
                        />
                        <div
                          className="w-4 h-4 rounded-full"
                          style={{ backgroundColor: theme.colors.panelDark }}
                        />
                      </div>
                      <span className="font-medium text-sm" style={{ color: 'var(--color-text-primary)' }}>
                        {theme.displayName}
                      </span>
                    </div>
                  </button>
                ))}
              </div>
            </div>
          </SettingsSection>
        );

      case 'about':
        return (
          <div>
            <SettingsSection
              title={t('settings_about_title')}
              icon="info"
            >
              <div className="space-y-4">
                {/* App Header */}
                <div className="flex items-center gap-4 p-4 bg-white dark:bg-background-dark border border-gray-200 dark:border-border-dark rounded-lg">
                  <div className="w-16 h-16 bg-primary/10 rounded-lg flex items-center justify-center">
                    <span className="material-symbols-outlined text-3xl text-primary">account_tree</span>
                  </div>
                  <div className="flex-1">
                    <h3 className="text-lg font-bold" style={{ color: 'var(--color-text-primary)' }}>
                      LangConfig
                    </h3>
                    <p className="text-sm font-medium" style={{ color: 'var(--color-primary)' }}>
                      Powered by LangChain & LangGraph
                    </p>
                    <p className="text-sm" style={{ color: 'var(--color-text-muted)' }}>
                      Version 0.1.0 (Alpha)
                    </p>
                  </div>
                </div>

                {/* Built With */}
                <div className="p-4 bg-white dark:bg-background-dark border border-gray-200 dark:border-border-dark rounded-lg">
                  <h4 className="text-sm font-semibold mb-3" style={{ color: 'var(--color-text-primary)' }}>
                    Built with LangChain & LangGraph
                  </h4>
                  <p className="text-sm mb-3" style={{ color: 'var(--color-text-muted)' }}>
                    LangConfig is a visual interface for LangGraph. Every workflow you build is a real LangGraph state graph under the hood. We use these frameworks because they're excellent for building production AI applications.
                  </p>
                  <div className="flex gap-2">
                    <a
                      href="https://www.langchain.com"
                      target="_blank"
                      rel="noopener noreferrer"
                      className="inline-flex items-center gap-2 px-3 py-1.5 text-xs font-medium bg-white dark:bg-panel-dark border border-gray-300 dark:border-border-dark rounded-lg hover:bg-gray-50 dark:hover:bg-white/5 transition-colors"
                      style={{ color: 'var(--color-text-primary)' }}
                    >
                      <span className="material-symbols-outlined text-sm">open_in_new</span>
                      LangChain
                    </a>
                    <a
                      href="https://langchain-ai.github.io/langgraph/"
                      target="_blank"
                      rel="noopener noreferrer"
                      className="inline-flex items-center gap-2 px-3 py-1.5 text-xs font-medium bg-white dark:bg-panel-dark border border-gray-300 dark:border-border-dark rounded-lg hover:bg-gray-50 dark:hover:bg-white/5 transition-colors"
                      style={{ color: 'var(--color-text-primary)' }}
                    >
                      <span className="material-symbols-outlined text-sm">open_in_new</span>
                      LangGraph
                    </a>
                  </div>
                </div>

                {/* What You're Building With */}
                <div className="grid grid-cols-2 gap-3">
                  <div className="p-3 bg-white dark:bg-background-dark border border-gray-200 dark:border-border-dark rounded-lg">
                    <div className="flex items-center gap-2 mb-2">
                      <span className="material-symbols-outlined text-lg text-primary">settings_suggest</span>
                      <h5 className="text-xs font-bold" style={{ color: 'var(--color-text-primary)' }}>LangGraph Workflows</h5>
                    </div>
                    <p className="text-xs" style={{ color: 'var(--color-text-muted)' }}>
                      State graphs with checkpointing
                    </p>
                  </div>

                  <div className="p-3 bg-white dark:bg-background-dark border border-gray-200 dark:border-border-dark rounded-lg">
                    <div className="flex items-center gap-2 mb-2">
                      <span className="material-symbols-outlined text-lg text-primary">smart_toy</span>
                      <h5 className="text-xs font-bold" style={{ color: 'var(--color-text-primary)' }}>LangChain Agents</h5>
                    </div>
                    <p className="text-xs" style={{ color: 'var(--color-text-muted)' }}>
                      Tools, memory, and chains
                    </p>
                  </div>

                  <div className="p-3 bg-white dark:bg-background-dark border border-gray-200 dark:border-border-dark rounded-lg">
                    <div className="flex items-center gap-2 mb-2">
                      <span className="material-symbols-outlined text-lg text-primary">description</span>
                      <h5 className="text-xs font-bold" style={{ color: 'var(--color-text-primary)' }}>LangChain RAG</h5>
                    </div>
                    <p className="text-xs" style={{ color: 'var(--color-text-muted)' }}>
                      Vector stores and retrievers
                    </p>
                  </div>

                  <div className="p-3 bg-white dark:bg-background-dark border border-gray-200 dark:border-border-dark rounded-lg">
                    <div className="flex items-center gap-2 mb-2">
                      <span className="material-symbols-outlined text-lg text-primary">code</span>
                      <h5 className="text-xs font-bold" style={{ color: 'var(--color-text-primary)' }}>Export to Code</h5>
                    </div>
                    <p className="text-xs" style={{ color: 'var(--color-text-muted)' }}>
                      Production LangGraph Python
                    </p>
                  </div>
                </div>

                {/* Mission */}
                <div>
                  <h4 className="text-sm font-semibold mb-2" style={{ color: 'var(--color-text-primary)' }}>
                    Our Mission
                  </h4>
                  <p className="text-sm" style={{ color: 'var(--color-text-muted)' }}>
                    Making LangChain and LangGraph accessible to everyone through visual, no-code workflows. We believe these frameworks are the future of AI development, and everyone should be able to learn and use them - whether you're a developer, product manager, researcher, or just curious about AI agents.
                  </p>
                </div>
              </div>
            </SettingsSection>

            {/* Tech Stack - Compact */}
            <SettingsSection
              title="Built With"
              icon="layers"
            >
              <div className="text-sm space-y-2" style={{ color: 'var(--color-text-muted)' }}>
                <p><strong style={{ color: 'var(--color-text-primary)' }}>Frontend:</strong> React 19, TypeScript, Tailwind CSS, ReactFlow, Tauri 2</p>
                <p><strong style={{ color: 'var(--color-text-primary)' }}>Backend:</strong> Python 3.11, FastAPI, LangChain v1.0, LangGraph, DeepAgents</p>
                <p><strong style={{ color: 'var(--color-text-primary)' }}>Database:</strong> PostgreSQL 16 with pgvector for LangChain vector stores</p>
                <p><strong style={{ color: 'var(--color-text-primary)' }}>AI:</strong> OpenAI, Anthropic, Google models via LangChain integrations</p>
              </div>
            </SettingsSection>

            {/* Links and License */}
            <SettingsSection
              title="Resources"
              icon="link"
            >
              <div className="space-y-4">
                <div className="flex gap-2 flex-wrap">
                  <button className="inline-flex items-center gap-2 px-4 py-2 text-sm font-medium bg-white dark:bg-background-dark border border-gray-300 dark:border-border-dark rounded-lg hover:bg-gray-50 dark:hover:bg-white/5 transition-colors" style={{ color: 'var(--color-text-primary)' }}>
                    <span className="material-symbols-outlined text-base">code</span>
                    GitHub
                  </button>
                </div>

                <hr className="border-gray-200 dark:border-border-dark" />

                <div className="text-xs" style={{ color: 'var(--color-text-muted)' }}>
                  <p className="font-semibold mb-1" style={{ color: 'var(--color-text-primary)' }}>License</p>
                  <p>MIT License © 2025</p>
                  <p className="mt-2">Making agentic AI accessible to everyone.</p>
                </div>
              </div>
            </SettingsSection>
          </div>
        );

      default:
        return (
          <SettingsSection
            title="Coming Soon"
            icon="construction"
          >
            <p className="text-sm" style={{ color: 'var(--color-text-muted)' }}>
              This settings category is under development and will be available soon.
            </p>
          </SettingsSection>
        );
    }
  };

  // Show loading state while fetching settings from backend
  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-screen">
        <div className="text-center">
          <div className="inline-block animate-spin rounded-full h-8 w-8 border-b-2 border-primary mb-4"></div>
          <p className="text-sm" style={{ color: 'var(--color-text-muted)' }}>Loading settings...</p>
        </div>
      </div>
    );
  }

  // Don't render if settings haven't loaded yet
  if (!generalSettings || !localModelsSettings || !workspaceSettings || !modelDefaultsSettings || !ragSettings) {
    return null;
  }

  return (
    <SettingsLayout
      currentCategory={currentCategory}
      onCategoryChange={setCurrentCategory}
    >
      {renderCategoryContent()}
    </SettingsLayout>
  );
}
