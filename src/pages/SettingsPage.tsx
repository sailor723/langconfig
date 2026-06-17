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
import SettingsSection, { SettingsInput, SettingsSelect } from '../features/settings/ui/SettingsSection';

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

  // General settings state - start with null, load from backend
  const [generalSettings, setGeneralSettings] = useState<GeneralSettings>({
    appName: 'LangConfig',
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
        return (
          <div>
            <SettingsSection
              title={t('settings_api_keys_title')}
              description={t('settings_api_keys_desc')}
              icon="key"
            >
              <div className="space-y-4">
                {/* Anthropic */}
                <div>
                  <div className="flex items-center gap-2 mb-1">
                    <label className="text-sm font-medium" style={{ color: 'var(--color-text-primary)' }}>
                      Anthropic API Key
                    </label>
                    {apiKeyStatus.anthropic ? (
                      (() => {
                        const conn = apiKeyConnection.anthropic;
                        if (conn?.connected === true) {
                          return <span className="inline-flex items-center gap-1 px-2 py-0.5 text-xs font-medium bg-green-100 dark:bg-green-500/20 text-green-700 dark:text-green-400 rounded-full"><span className="material-symbols-outlined text-xs">check_circle</span> Connected</span>;
                        } else if (conn?.connected === false) {
                          return <span className="inline-flex items-center gap-1 px-2 py-0.5 text-xs font-medium bg-red-100 dark:bg-red-500/20 text-red-700 dark:text-red-400 rounded-full"><span className="material-symbols-outlined text-xs">error</span> Failed</span>;
                        } else {
                          return <span className="inline-flex items-center gap-1 px-2 py-0.5 text-xs font-medium bg-yellow-100 dark:bg-yellow-500/20 text-yellow-700 dark:text-yellow-400 rounded-full"><span className="material-symbols-outlined text-xs">pending</span> Configured</span>;
                        }
                      })()
                    ) : (
                      <span className="inline-flex items-center gap-1 px-2 py-0.5 text-xs font-medium bg-gray-100 dark:bg-gray-500/20 text-gray-600 dark:text-gray-400 rounded-full">
                        Not set
                      </span>
                    )}
                  </div>
                  <input
                    type="password"
                    value={apiKeys.anthropic}
                    onChange={(e) => setApiKeys({ ...apiKeys, anthropic: e.target.value })}
                    placeholder={apiKeyStatus.anthropic ? "Enter new key to replace existing" : "sk-ant-..."}
                    className="w-full px-3 py-2 text-sm border border-gray-300 dark:border-border-dark rounded-lg focus:outline-none focus:ring-2 focus:ring-primary font-mono"
                    style={{
                      backgroundColor: 'var(--color-input-background)',
                      color: 'var(--color-text-primary)'
                    }}
                  />
                  <p className="text-xs mt-1" style={{ color: 'var(--color-text-muted)' }}>
                    Required for Claude models (claude-sonnet-4-5, claude-haiku-4-5, etc.)
                  </p>
                  <div className="flex items-center gap-2 mt-2">
                    <button
                      onClick={() => handleTestConnection('anthropic')}
                      disabled={testingProvider === 'anthropic' || !apiKeyStatus.anthropic}
                      className="inline-flex items-center gap-1 px-2.5 py-1 text-xs font-medium rounded-lg border transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
                      style={{
                        borderColor: 'var(--color-border-dark)',
                        color: testingProvider === 'anthropic' ? 'var(--color-text-muted)' : 'var(--color-text-primary)',
                      }}
                    >
                      {testingProvider === 'anthropic' ? (
                        <><div className="w-3 h-3 border-2 border-current border-t-transparent rounded-full animate-spin" /> Testing...</>
                      ) : (
                        <><span className="material-symbols-outlined text-xs">link</span> Test Connection</>
                      )}
                    </button>
                    {testResults.anthropic && (
                      <span className={`text-xs ${testResults.anthropic.success ? 'text-green-600' : 'text-red-500'}`}>
                        {testResults.anthropic.message}
                      </span>
                    )}
                  </div>
                </div>

                {/* OpenAI */}
                <div>
                  <div className="flex items-center gap-2 mb-1">
                    <label className="text-sm font-medium" style={{ color: 'var(--color-text-primary)' }}>
                      OpenAI API Key
                    </label>
                    {apiKeyStatus.openai ? (
                      (() => {
                        const conn = apiKeyConnection.openai;
                        if (conn?.connected === true) return <span className="inline-flex items-center gap-1 px-2 py-0.5 text-xs font-medium bg-green-100 dark:bg-green-500/20 text-green-700 dark:text-green-400 rounded-full"><span className="material-symbols-outlined text-xs">check_circle</span> Connected</span>;
                        else if (conn?.connected === false) return <span className="inline-flex items-center gap-1 px-2 py-0.5 text-xs font-medium bg-red-100 dark:bg-red-500/20 text-red-700 dark:text-red-400 rounded-full"><span className="material-symbols-outlined text-xs">error</span> Failed</span>;
                        else return <span className="inline-flex items-center gap-1 px-2 py-0.5 text-xs font-medium bg-green-100 dark:bg-green-500/20 text-green-700 dark:text-green-400 rounded-full"><span className="material-symbols-outlined text-xs">check_circle</span> Configured</span>;
                      })()
                    ) : (
                      <span className="inline-flex items-center gap-1 px-2 py-0.5 text-xs font-medium bg-gray-100 dark:bg-gray-500/20 text-gray-600 dark:text-gray-400 rounded-full">Not set</span>
                    )}
                  </div>
                  <input
                    type="password"
                    value={apiKeys.openai}
                    onChange={(e) => setApiKeys({ ...apiKeys, openai: e.target.value })}
                    placeholder={apiKeyStatus.openai ? "Enter new key to replace existing" : "sk-..."}
                    className="w-full px-3 py-2 text-sm border border-gray-300 dark:border-border-dark rounded-lg focus:outline-none focus:ring-2 focus:ring-primary font-mono"
                    style={{
                      backgroundColor: 'var(--color-input-background)',
                      color: 'var(--color-text-primary)'
                    }}
                  />
                  <p className="text-xs mt-1" style={{ color: 'var(--color-text-muted)' }}>
                    Required for GPT models (gpt-4o, gpt-4o-mini, gpt-4-turbo, etc.)
                  </p>
                  <div className="flex items-center gap-2 mt-2">
                    <button onClick={() => handleTestConnection('openai')} disabled={testingProvider === 'openai' || !apiKeyStatus.openai} className="inline-flex items-center gap-1 px-2.5 py-1 text-xs font-medium rounded-lg border transition-colors disabled:opacity-40 disabled:cursor-not-allowed" style={{ borderColor: 'var(--color-border-dark)', color: testingProvider === 'openai' ? 'var(--color-text-muted)' : 'var(--color-text-primary)' }}>
                      {testingProvider === 'openai' ? <><div className="w-3 h-3 border-2 border-current border-t-transparent rounded-full animate-spin" /> Testing...</> : <><span className="material-symbols-outlined text-xs">link</span> Test Connection</>}
                    </button>
                    {testResults.openai && <span className={`text-xs ${testResults.openai.success ? 'text-green-600' : 'text-red-500'}`}>{testResults.openai.message}</span>}
                  </div>
                </div>

                {/* Google */}
                <div>
                  <div className="flex items-center gap-2 mb-1">
                    <label className="text-sm font-medium" style={{ color: 'var(--color-text-primary)' }}>
                      Google API Key
                    </label>
                    {apiKeyStatus.google ? (
                      (() => {
                        const conn = apiKeyConnection.google;
                        if (conn?.connected === true) return <span className="inline-flex items-center gap-1 px-2 py-0.5 text-xs font-medium bg-green-100 dark:bg-green-500/20 text-green-700 dark:text-green-400 rounded-full"><span className="material-symbols-outlined text-xs">check_circle</span> Connected</span>;
                        else if (conn?.connected === false) return <span className="inline-flex items-center gap-1 px-2 py-0.5 text-xs font-medium bg-red-100 dark:bg-red-500/20 text-red-700 dark:text-red-400 rounded-full"><span className="material-symbols-outlined text-xs">error</span> Failed</span>;
                        else return <span className="inline-flex items-center gap-1 px-2 py-0.5 text-xs font-medium bg-green-100 dark:bg-green-500/20 text-green-700 dark:text-green-400 rounded-full"><span className="material-symbols-outlined text-xs">check_circle</span> Configured</span>;
                      })()
                    ) : (
                      <span className="inline-flex items-center gap-1 px-2 py-0.5 text-xs font-medium bg-gray-100 dark:bg-gray-500/20 text-gray-600 dark:text-gray-400 rounded-full">Not set</span>
                    )}
                  </div>
                  <input
                    type="password"
                    value={apiKeys.google}
                    onChange={(e) => setApiKeys({ ...apiKeys, google: e.target.value })}
                    placeholder={apiKeyStatus.google ? "Enter new key to replace existing" : "AIza..."}
                    className="w-full px-3 py-2 text-sm border border-gray-300 dark:border-border-dark rounded-lg focus:outline-none focus:ring-2 focus:ring-primary font-mono"
                    style={{
                      backgroundColor: 'var(--color-input-background)',
                      color: 'var(--color-text-primary)'
                    }}
                  />
                  <p className="text-xs mt-1" style={{ color: 'var(--color-text-muted)' }}>
                    Required for Gemini models (gemini-2.5-pro, gemini-2.5-flash, etc.)
                  </p>
                  <div className="flex items-center gap-2 mt-2">
                    <button onClick={() => handleTestConnection('google')} disabled={testingProvider === 'google' || !apiKeyStatus.google} className="inline-flex items-center gap-1 px-2.5 py-1 text-xs font-medium rounded-lg border transition-colors disabled:opacity-40 disabled:cursor-not-allowed" style={{ borderColor: 'var(--color-border-dark)', color: testingProvider === 'google' ? 'var(--color-text-muted)' : 'var(--color-text-primary)' }}>
                      {testingProvider === 'google' ? <><div className="w-3 h-3 border-2 border-current border-t-transparent rounded-full animate-spin" /> Testing...</> : <><span className="material-symbols-outlined text-xs">link</span> Test Connection</>}
                    </button>
                    {testResults.google && <span className={`text-xs ${testResults.google.success ? 'text-green-600' : 'text-red-500'}`}>{testResults.google.message}</span>}
                  </div>
                </div>

                {/* DeepSeek */}
                <div>
                  <div className="flex items-center gap-2 mb-1">
                    <label className="text-sm font-medium" style={{ color: 'var(--color-text-primary)' }}>
                      DeepSeek API Key
                    </label>
                    {apiKeyStatus.deepseek ? (
                      (() => {
                        const conn = apiKeyConnection.deepseek;
                        if (conn?.connected === true) return <span className="inline-flex items-center gap-1 px-2 py-0.5 text-xs font-medium bg-green-100 dark:bg-green-500/20 text-green-700 dark:text-green-400 rounded-full"><span className="material-symbols-outlined text-xs">check_circle</span> Connected</span>;
                        else if (conn?.connected === false) return <span className="inline-flex items-center gap-1 px-2 py-0.5 text-xs font-medium bg-red-100 dark:bg-red-500/20 text-red-700 dark:text-red-400 rounded-full"><span className="material-symbols-outlined text-xs">error</span> Failed</span>;
                        else return <span className="inline-flex items-center gap-1 px-2 py-0.5 text-xs font-medium bg-green-100 dark:bg-green-500/20 text-green-700 dark:text-green-400 rounded-full"><span className="material-symbols-outlined text-xs">check_circle</span> Configured</span>;
                      })()
                    ) : (
                      <span className="inline-flex items-center gap-1 px-2 py-0.5 text-xs font-medium bg-gray-100 dark:bg-gray-500/20 text-gray-600 dark:text-gray-400 rounded-full">Not set</span>
                    )}
                  </div>
                  <input
                    type="password"
                    value={apiKeys.deepseek}
                    onChange={(e) => setApiKeys({ ...apiKeys, deepseek: e.target.value })}
                    placeholder={apiKeyStatus.deepseek ? "Enter new key to replace existing" : "sk-..."}
                    className="w-full px-3 py-2 text-sm border border-gray-300 dark:border-border-dark rounded-lg focus:outline-none focus:ring-2 focus:ring-primary font-mono"
                    style={{
                      backgroundColor: 'var(--color-input-background)',
                      color: 'var(--color-text-primary)'
                    }}
                  />
                  <p className="text-xs mt-1" style={{ color: 'var(--color-text-muted)' }}>
                    Required for DeepSeek models (deepseek-chat, deepseek-reasoner)
                  </p>
                  <div className="flex items-center gap-2 mt-2">
                    <button onClick={() => handleTestConnection('deepseek')} disabled={testingProvider === 'deepseek' || !apiKeyStatus.deepseek} className="inline-flex items-center gap-1 px-2.5 py-1 text-xs font-medium rounded-lg border transition-colors disabled:opacity-40 disabled:cursor-not-allowed" style={{ borderColor: 'var(--color-border-dark)', color: testingProvider === 'deepseek' ? 'var(--color-text-muted)' : 'var(--color-text-primary)' }}>
                      {testingProvider === 'deepseek' ? <><div className="w-3 h-3 border-2 border-current border-t-transparent rounded-full animate-spin" /> Testing...</> : <><span className="material-symbols-outlined text-xs">link</span> Test Connection</>}
                    </button>
                    {testResults.deepseek && <span className={`text-xs ${testResults.deepseek.success ? 'text-green-600' : 'text-red-500'}`}>{testResults.deepseek.message}</span>}
                  </div>
                </div>

                {/* GLM */}
                <div>
                  <div className="flex items-center gap-2 mb-1">
                    <label className="text-sm font-medium" style={{ color: 'var(--color-text-primary)' }}>
                      GLM API Key
                    </label>
                    {apiKeyStatus.glm ? (
                      (() => {
                        const conn = apiKeyConnection.glm;
                        if (conn?.connected === true) return <span className="inline-flex items-center gap-1 px-2 py-0.5 text-xs font-medium bg-green-100 dark:bg-green-500/20 text-green-700 dark:text-green-400 rounded-full"><span className="material-symbols-outlined text-xs">check_circle</span> Connected</span>;
                        else if (conn?.connected === false) return <span className="inline-flex items-center gap-1 px-2 py-0.5 text-xs font-medium bg-red-100 dark:bg-red-500/20 text-red-700 dark:text-red-400 rounded-full"><span className="material-symbols-outlined text-xs">error</span> Failed</span>;
                        else return <span className="inline-flex items-center gap-1 px-2 py-0.5 text-xs font-medium bg-green-100 dark:bg-green-500/20 text-green-700 dark:text-green-400 rounded-full"><span className="material-symbols-outlined text-xs">check_circle</span> Configured</span>;
                      })()
                    ) : (
                      <span className="inline-flex items-center gap-1 px-2 py-0.5 text-xs font-medium bg-gray-100 dark:bg-gray-500/20 text-gray-600 dark:text-gray-400 rounded-full">Not set</span>
                    )}
                  </div>
                  <input
                    type="password"
                    value={apiKeys.glm}
                    onChange={(e) => setApiKeys({ ...apiKeys, glm: e.target.value })}
                    placeholder={apiKeyStatus.glm ? "Enter new key to replace existing" : "Enter GLM API key..."}
                    className="w-full px-3 py-2 text-sm border border-gray-300 dark:border-border-dark rounded-lg focus:outline-none focus:ring-2 focus:ring-primary font-mono"
                    style={{
                      backgroundColor: 'var(--color-input-background)',
                      color: 'var(--color-text-primary)'
                    }}
                  />
                  <p className="text-xs mt-1" style={{ color: 'var(--color-text-muted)' }}>
                    Required for GLM models (glm-4, glm-4v, etc.)
                  </p>
                  <div className="flex items-center gap-2 mt-2">
                    <button onClick={() => handleTestConnection('glm')} disabled={testingProvider === 'glm' || !apiKeyStatus.glm} className="inline-flex items-center gap-1 px-2.5 py-1 text-xs font-medium rounded-lg border transition-colors disabled:opacity-40 disabled:cursor-not-allowed" style={{ borderColor: 'var(--color-border-dark)', color: testingProvider === 'glm' ? 'var(--color-text-muted)' : 'var(--color-text-primary)' }}>
                      {testingProvider === 'glm' ? <><div className="w-3 h-3 border-2 border-current border-t-transparent rounded-full animate-spin" /> Testing...</> : <><span className="material-symbols-outlined text-xs">link</span> Test Connection</>}
                    </button>
                    {testResults.glm && <span className={`text-xs ${testResults.glm.success ? 'text-green-600' : 'text-red-500'}`}>{testResults.glm.message}</span>}
                  </div>
                </div>

                {/* MiniMax */}
                <div>
                  <div className="flex items-center gap-2 mb-1">
                    <label className="text-sm font-medium" style={{ color: 'var(--color-text-primary)' }}>
                      MiniMax API Key
                    </label>
                    {apiKeyStatus.minimax ? (
                      (() => {
                        const conn = apiKeyConnection.minimax;
                        if (conn?.connected === true) return <span className="inline-flex items-center gap-1 px-2 py-0.5 text-xs font-medium bg-green-100 dark:bg-green-500/20 text-green-700 dark:text-green-400 rounded-full"><span className="material-symbols-outlined text-xs">check_circle</span> Connected</span>;
                        else if (conn?.connected === false) return <span className="inline-flex items-center gap-1 px-2 py-0.5 text-xs font-medium bg-red-100 dark:bg-red-500/20 text-red-700 dark:text-red-400 rounded-full"><span className="material-symbols-outlined text-xs">error</span> Failed</span>;
                        else return <span className="inline-flex items-center gap-1 px-2 py-0.5 text-xs font-medium bg-green-100 dark:bg-green-500/20 text-green-700 dark:text-green-400 rounded-full"><span className="material-symbols-outlined text-xs">check_circle</span> Configured</span>;
                      })()
                    ) : (
                      <span className="inline-flex items-center gap-1 px-2 py-0.5 text-xs font-medium bg-gray-100 dark:bg-gray-500/20 text-gray-600 dark:text-gray-400 rounded-full">Not set</span>
                    )}
                  </div>
                  <input
                    type="password"
                    value={apiKeys.minimax}
                    onChange={(e) => setApiKeys({ ...apiKeys, minimax: e.target.value })}
                    placeholder={apiKeyStatus.minimax ? "Enter new key to replace existing" : "Enter MiniMax API key..."}
                    className="w-full px-3 py-2 text-sm border border-gray-300 dark:border-border-dark rounded-lg focus:outline-none focus:ring-2 focus:ring-primary font-mono"
                    style={{
                      backgroundColor: 'var(--color-input-background)',
                      color: 'var(--color-text-primary)'
                    }}
                  />
                  <p className="text-xs mt-1" style={{ color: 'var(--color-text-muted)' }}>
                    Required for MiniMax models (minimax-t1, etc.)
                  </p>
                  <div className="flex items-center gap-2 mt-2">
                    <button onClick={() => handleTestConnection('minimax')} disabled={testingProvider === 'minimax' || !apiKeyStatus.minimax} className="inline-flex items-center gap-1 px-2.5 py-1 text-xs font-medium rounded-lg border transition-colors disabled:opacity-40 disabled:cursor-not-allowed" style={{ borderColor: 'var(--color-border-dark)', color: testingProvider === 'minimax' ? 'var(--color-text-muted)' : 'var(--color-text-primary)' }}>
                      {testingProvider === 'minimax' ? <><div className="w-3 h-3 border-2 border-current border-t-transparent rounded-full animate-spin" /> Testing...</> : <><span className="material-symbols-outlined text-xs">link</span> Test Connection</>}
                    </button>
                    {testResults.minimax && <span className={`text-xs ${testResults.minimax.success ? 'text-green-600' : 'text-red-500'}`}>{testResults.minimax.message}</span>}
                  </div>
                </div>

                {/* Tavily API Key */}
                <div className="mb-6">
                  <div className="flex items-center justify-between mb-2">
                    <label className="block text-sm font-medium" style={{ color: 'var(--color-text-primary)' }}>
                      Tavily
                    </label>
                    {apiKeyStatus.tavily && (
                      <span className="flex items-center gap-1 text-xs text-green-600 dark:text-green-400">
                        <svg className="w-3 h-3" fill="currentColor" viewBox="0 0 20 20">
                          <path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" />
                        </svg>
                        Set
                      </span>
                    )}
                    {!apiKeyStatus.tavily && (
                      <span className="text-xs" style={{ color: 'var(--color-text-muted)' }}>
                        Not set
                      </span>
                    )}
                  </div>
                  <input
                    type="password"
                    value={apiKeys.tavily}
                    onChange={(e) => setApiKeys({ ...apiKeys, tavily: e.target.value })}
                    placeholder={apiKeyStatus.tavily ? "Enter new key to replace existing" : "Enter Tavily API key..."}
                    className="w-full px-3 py-2 text-sm border border-gray-300 dark:border-border-dark rounded-lg focus:outline-none focus:ring-2 focus:ring-primary font-mono"
                    style={{
                      backgroundColor: 'var(--color-input-background)',
                      color: 'var(--color-text-primary)'
                    }}
                  />
                  <p className="text-xs mt-1" style={{ color: 'var(--color-text-muted)' }}>
                    Required for Tavily search (tavily_search tool)
                  </p>
                </div>

                {/* Agnes AI API Key */}
                <div>
                  <div className="flex items-center gap-2 mb-1">
                    <label className="text-sm font-medium" style={{ color: 'var(--color-text-primary)' }}>
                      Agnes AI API Key
                    </label>
                    {apiKeyStatus.agnes ? (
                      (() => {
                        const conn = apiKeyConnection.agnes;
                        if (conn?.connected === true) return <span className="inline-flex items-center gap-1 px-2 py-0.5 text-xs font-medium bg-green-100 dark:bg-green-500/20 text-green-700 dark:text-green-400 rounded-full"><span className="material-symbols-outlined text-xs">check_circle</span> Connected</span>;
                        else if (conn?.connected === false) return <span className="inline-flex items-center gap-1 px-2 py-0.5 text-xs font-medium bg-red-100 dark:bg-red-500/20 text-red-700 dark:text-red-400 rounded-full"><span className="material-symbols-outlined text-xs">error</span> Failed</span>;
                        else return <span className="inline-flex items-center gap-1 px-2 py-0.5 text-xs font-medium bg-green-100 dark:bg-green-500/20 text-green-700 dark:text-green-400 rounded-full"><span className="material-symbols-outlined text-xs">check_circle</span> Configured</span>;
                      })()
                    ) : (
                      <span className="inline-flex items-center gap-1 px-2 py-0.5 text-xs font-medium bg-gray-100 dark:bg-gray-500/20 text-gray-600 dark:text-gray-400 rounded-full">Not set</span>
                    )}
                  </div>
                  <input
                    type="password"
                    value={apiKeys.agnes}
                    onChange={(e) => setApiKeys({ ...apiKeys, agnes: e.target.value })}
                    placeholder={apiKeyStatus.agnes ? "Enter new key to replace existing" : "Enter Agnes API key..."}
                    className="w-full px-3 py-2 text-sm border border-gray-300 dark:border-border-dark rounded-lg focus:outline-none focus:ring-2 focus:ring-primary font-mono"
                    style={{
                      backgroundColor: 'var(--color-input-background)',
                      color: 'var(--color-text-primary)'
                    }}
                  />
                  <p className="text-xs mt-1" style={{ color: 'var(--color-text-muted)' }}>
                    Required for Agnes AI models (agnes-chat, agnes-reasoning, etc.)
                  </p>
                  <input
                    type="url"
                    value={apiKeys.agnesBaseUrl}
                    onChange={(e) => setApiKeys({ ...apiKeys, agnesBaseUrl: e.target.value })}
                    placeholder="https://apihub.agnes-ai.com/v1"
                    className="w-full px-3 py-2 mt-2 text-sm border border-gray-300 dark:border-border-dark rounded-lg focus:outline-none focus:ring-2 focus:ring-primary font-mono"
                    style={{
                      backgroundColor: 'var(--color-input-background)',
                      color: 'var(--color-text-primary)'
                    }}
                  />
                  <p className="text-xs mt-1" style={{ color: 'var(--color-text-muted)' }}>
                    Base URL for Agnes AI API (defaults to apihub.agnes-ai.com/v1 if left empty)
                  </p>
                  <div className="flex items-center gap-2 mt-2">
                    <button onClick={() => handleTestConnection('agnes')} disabled={testingProvider === 'agnes' || !apiKeyStatus.agnes} className="inline-flex items-center gap-1 px-2.5 py-1 text-xs font-medium rounded-lg border transition-colors disabled:opacity-40 disabled:cursor-not-allowed" style={{ borderColor: 'var(--color-border-dark)', color: testingProvider === 'agnes' ? 'var(--color-text-muted)' : 'var(--color-text-primary)' }}>
                      {testingProvider === 'agnes' ? <><div className="w-3 h-3 border-2 border-current border-t-transparent rounded-full animate-spin" /> Testing...</> : <><span className="material-symbols-outlined text-xs">link</span> Test Connection</>}
                    </button>
                    {testResults.agnes && <span className={`text-xs ${testResults.agnes.success ? 'text-green-600' : 'text-red-500'}`}>{testResults.agnes.message}</span>}
                  </div>
                </div>

                {/* Save Button and Status */}
                <div className="pt-4 border-t border-gray-200 dark:border-border-dark">
                  <div className="flex items-center gap-3">
                    <button
                      onClick={async () => {
                        // Only save keys that have been entered (non-empty)
                        const keysToSave: Record<string, string> = {};
                        if (apiKeys.anthropic) keysToSave.anthropic_api_key = apiKeys.anthropic;
                        if (apiKeys.openai) keysToSave.openai_api_key = apiKeys.openai;
                        if (apiKeys.google) keysToSave.google_api_key = apiKeys.google;
                        if (apiKeys.deepseek) keysToSave.deepseek_api_key = apiKeys.deepseek;
                        if (apiKeys.glm) keysToSave.glm_api_key = apiKeys.glm;
                        if (apiKeys.minimax) keysToSave.minimax_api_key = apiKeys.minimax;
                        if (apiKeys.tavily) keysToSave.tavily_api_key = apiKeys.tavily;
                        if (apiKeys.agnes) keysToSave.agnes_api_key = apiKeys.agnes;
                        if (apiKeys.agnesBaseUrl) keysToSave.agnes_base_url = apiKeys.agnesBaseUrl;

                        if (Object.keys(keysToSave).length === 0) {
                          setApiKeySaveMessage('Enter at least one API key to save');
                          setTimeout(() => setApiKeySaveMessage(null), 3000);
                          return;
                        }

                        setApiKeySaving(true);
                        setApiKeySaveMessage(null);
                        try {
                          await apiClient.setApiKeys(keysToSave);
                          // Update status for saved keys
                          setApiKeyStatus({
                            anthropic: apiKeyStatus.anthropic || !!apiKeys.anthropic,
                            openai: apiKeyStatus.openai || !!apiKeys.openai,
                            google: apiKeyStatus.google || !!apiKeys.google,
                            deepseek: apiKeyStatus.deepseek || !!apiKeys.deepseek,
                            glm: apiKeyStatus.glm || !!apiKeys.glm,
                            minimax: apiKeyStatus.minimax || !!apiKeys.minimax,
                            tavily: apiKeyStatus.tavily || !!apiKeys.tavily,
                            agnes: apiKeyStatus.agnes || !!apiKeys.agnes,
                          });
                          // Clear input fields after successful save
                          setApiKeys({ anthropic: '', openai: '', google: '', deepseek: '', glm: '', minimax: '', tavily: '', agnes: '', agnesBaseUrl: '' });
                          setApiKeySaveMessage('API keys saved successfully!');
                          setTimeout(() => setApiKeySaveMessage(null), 3000);
                          // Reload connection status (backend auto-tested after save)
                          try {
                            const refreshRes = await apiClient.getApiKeys();
                            const freshKeys = refreshRes.data || [];
                            setApiKeyConnection({
                              anthropic: freshKeys.find((k: any) => k.provider === 'anthropic'),
                              openai: freshKeys.find((k: any) => k.provider === 'openai'),
                              google: freshKeys.find((k: any) => k.provider === 'google'),
                              deepseek: freshKeys.find((k: any) => k.provider === 'deepseek'),
                              glm: freshKeys.find((k: any) => k.provider === 'glm'),
                              minimax: freshKeys.find((k: any) => k.provider === 'minimax'),
                              tavily: freshKeys.find((k: any) => k.provider === 'tavily'),
                              agnes: freshKeys.find((k: any) => k.provider === 'agnes'),
                            });
                          } catch (_) {} // Silently skip refresh error
                        } catch (error) {
                          console.error('Failed to save API keys:', error);
                          setApiKeySaveMessage('Failed to save API keys. Please try again.');
                          setTimeout(() => setApiKeySaveMessage(null), 5000);
                        } finally {
                          setApiKeySaving(false);
                        }
                      }}
                      disabled={apiKeySaving || (!apiKeys.anthropic && !apiKeys.openai && !apiKeys.google && !apiKeys.deepseek && !apiKeys.glm && !apiKeys.minimax && !apiKeys.tavily && !apiKeys.agnes && !apiKeys.agnesBaseUrl)}
                      className="px-4 py-2 text-sm font-medium bg-primary text-white rounded-lg hover:bg-primary/90 transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
                    >
                      {apiKeySaving ? (
                        <>
                          <div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                          Saving...
                        </>
                      ) : (
                        <>
                          <span className="material-symbols-outlined text-base">save</span>
                          Save API Keys
                        </>
                      )}
                    </button>
                    {apiKeySaveMessage && (
                      <span className={`text-sm ${apiKeySaveMessage.includes('successfully') ? 'text-green-600 dark:text-green-400' : 'text-amber-600 dark:text-amber-400'}`}>
                        {apiKeySaveMessage}
                      </span>
                    )}
                  </div>
                  <p className="text-xs mt-2" style={{ color: 'var(--color-text-muted)' }}>
                    Only non-empty fields will be saved. Leave a field empty to keep the existing key.
                  </p>
                </div>
              </div>
            </SettingsSection>

            <SettingsSection
              title="Security Notice"
              icon="warning"
            >
              <div className="flex gap-3 p-4 bg-yellow-50 dark:bg-yellow-500/10 border border-yellow-200 dark:border-yellow-500/30 rounded-lg">
                <span className="material-symbols-outlined text-yellow-600 dark:text-yellow-400 text-xl">
                  lock
                </span>
                <div>
                  <h5 className="text-sm font-semibold text-yellow-800 dark:text-yellow-400 mb-1">
                    Database Storage
                  </h5>
                  <p className="text-xs text-yellow-700 dark:text-yellow-400/80 mb-2">
                    API keys are stored in PostgreSQL database (<code className="px-1 py-0.5 bg-yellow-100 dark:bg-yellow-900/30 rounded">settings</code> table) and persist across backend restarts.
                  </p>
                  <p className="text-xs text-yellow-700 dark:text-yellow-400/80">
                    <strong>Note:</strong> Keys are currently stored unencrypted. Future versions will add encryption and migrate to OS keychain (macOS Keychain, Windows Credential Manager, Linux Secret Service) via Tauri for enhanced security.
                  </p>
                </div>
              </div>
            </SettingsSection>
          </div>
        );

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
            <div className="pt-4">
              <button
                onClick={() => autoSave('embedding')}
                className="px-6 py-2 text-sm font-medium text-white rounded-lg hover:opacity-90 transition-opacity cursor-pointer"
                style={{ backgroundColor: 'var(--color-primary)' }}
              >
                Save
              </button>
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
