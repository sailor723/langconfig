/**
 * PromptAssemblyPage - Visual prompt editor for agents and their subagents
 *
 * Select an agent → edit Manager prompt and Subagent prompts via PromptCanvas
 * Save all changes at once.
 */

import { useState, useEffect, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import PromptCanvas from '../features/agents/ui/PromptCanvas';
import apiClient from '../lib/api-client';
import { Layers, Save, Loader2, GitBranch, User } from 'lucide-react';

interface SubAgentData {
  name: string;
  description: string;
  model?: string;
  system_prompt?: string;
  tools: string[];
  middleware: string[];
  interrupt_on: Record<string, any>;
  skills?: string[];
  response_format?: Record<string, any>;
}

interface AgentData {
  id: number;
  name: string;
  description?: string;
  config: {
    model: string;
    system_prompt: string;
    custom_prompt?: string;
    custom_suffix?: string;
    subagents: SubAgentData[];
    [key: string]: any;
  };
}

export default function PromptAssemblyPage() {
  const { t } = useTranslation('chat');
  const [agents, setAgents] = useState<any[]>([]);
  const [selectedAgentId, setSelectedAgentId] = useState<number | null>(null);
  const [agent, setAgent] = useState<AgentData | null>(null);
  const [loadingAgent, setLoadingAgent] = useState(false);

  // Manager prompt fields
  const [systemPrompt, setSystemPrompt] = useState('');
  const [customPrompt, setCustomPrompt] = useState('');
  const [customSuffix, setCustomSuffix] = useState('');

  // Subagent prompts (indexed by subagent index)
  const [subagentPrompts, setSubagentPrompts] = useState<Record<number, string>>({});

  // Active tab: 'manager' or subagent name
  const [activeTab, setActiveTab] = useState<string>('manager');

  // Save state
  const [saving, setSaving] = useState(false);
  const [saveSuccess, setSaveSuccess] = useState<string | null>(null);

  // Load agent list on mount
  useEffect(() => {
    (async () => {
      try {
        const res = await apiClient.listDeepAgents() as any;
        const list = Array.isArray(res) ? res : res.data || [];
        setAgents(list);
      } catch (err) {
        console.error('Failed to load agents:', err);
      }
    })();
  }, []);

  // Load selected agent config
  const loadAgent = useCallback(async (id: number) => {
    setLoadingAgent(true);
    try {
      const res = await apiClient.getDeepAgent(id) as any;
      const data: AgentData = res?.data || res;
      setAgent(data);
      const cfg = data.config || data;
      setSystemPrompt(cfg.system_prompt || '');
      setCustomPrompt(cfg.custom_prompt || '');
      setCustomSuffix(cfg.custom_suffix || '');
      const subPrompts: Record<number, string> = {};
      (cfg.subagents || []).forEach((sa: SubAgentData, i: number) => {
        subPrompts[i] = sa.system_prompt || '';
      });
      setSubagentPrompts(subPrompts);
      setActiveTab('manager');
    } catch (err) {
      console.error('Failed to load agent:', err);
    } finally {
      setLoadingAgent(false);
    }
  }, []);

  const handleAgentSelect = (id: number) => {
    setSelectedAgentId(id);
    loadAgent(id);
  };

  const updateSubagentPrompt = (idx: number, val: string) => {
    setSubagentPrompts(prev => ({ ...prev, [idx]: val }));
  };

  const handleSave = async () => {
    if (!agent) return;
    setSaving(true);
    setSaveSuccess(null);
    try {
      // Build updated config
      const cfg = { ...(agent.config || agent) };
      cfg.system_prompt = systemPrompt;
      if (customPrompt) cfg.custom_prompt = customPrompt;
      else delete cfg.custom_prompt;
      if (customSuffix) cfg.custom_suffix = customSuffix;
      else delete cfg.custom_suffix;

      // Update subagent prompts
      const subs = [...(cfg.subagents || [])];
      Object.entries(subagentPrompts).forEach(([idx, prompt]) => {
        const i = parseInt(idx);
        if (subs[i]) {
          subs[i] = { ...subs[i], system_prompt: prompt };
        }
      });
      cfg.subagents = subs;

      await apiClient.updateDeepAgent(agent.id, { config: cfg });
      setSaveSuccess(t('prompt_saved', { name: agent.name }));
      setTimeout(() => setSaveSuccess(null), 2000);
    } catch (err) {
      console.error('Failed to save:', err);
      setSaveSuccess(t('prompt_save_failed'));
    } finally {
      setSaving(false);
    }
  };

  const subagents: SubAgentData[] = agent ? (agent.config?.subagents || []) : [];

  return (
    <div className="flex-1 overflow-y-auto p-6" style={{ backgroundColor: '#f0f2f5' }}>
      <div className="max-w-5xl mx-auto">
        {/* Header */}
        <div className="flex items-center justify-between mb-6">
          <div className="flex items-center gap-3">
            <Layers className="w-8 h-8 text-purple-500" />
            <div>
              <h1 className="text-2xl font-bold" style={{ color: '#111827' }}>
                {t('prompt_title')}
              </h1>
              <p className="text-sm" style={{ color: '#4b5563' }}>
                {t('prompt_subtitle')}
              </p>
            </div>
          </div>
        </div>

        {/* Agent Selector */}
        <div className="mb-6 p-4 rounded-lg border bg-white dark:bg-panel-dark" style={{ borderColor: '#e5e7eb' }}>
          <label className="block text-xs font-medium mb-1.5 uppercase" style={{ color: '#6b7280' }}>
            {t('prompt_select_label')}
          </label>
          <div className="flex gap-3 items-center">
            <select
              value={selectedAgentId ?? ''}
              onChange={(e) => {
                const val = e.target.value;
                if (val) handleAgentSelect(parseInt(val));
              }}
              className="flex-1 px-3 py-2 text-sm border rounded-lg focus:outline-none focus:ring-2 focus:ring-primary"
              style={{
                backgroundColor: '#fff',
                color: '#1f2937',
                borderColor: '#d1d5db',
              }}
            >
              <option value="">{t('prompt_select_placeholder')}</option>
              {agents.map(a => (
                <option key={a.id} value={a.id}>{a.name}{a.description && a.description !== a.name ? ` — ${a.description.slice(0, 50)}` : ''}</option>
              ))}
            </select>

            {/* Save Button */}
            <button
              onClick={handleSave}
              disabled={!agent || saving}
              className="flex items-center gap-1.5 text-sm px-4 py-2 rounded-lg border transition-colors bg-primary text-white hover:opacity-90 disabled:opacity-40"
            >
              {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : <Save className="w-4 h-4" />}
              {saveSuccess || t('prompt_save_all')}
            </button>
          </div>
        </div>

        {loadingAgent && (
          <div className="flex items-center justify-center py-12">
            <Loader2 className="w-6 h-6 animate-spin text-gray-400" />
          </div>
        )}

        {!loadingAgent && !agent && !selectedAgentId && (
          <div className="text-center py-12 text-sm" style={{ color: '#9ca3af' }}>
            {t('prompt_editor_placeholder')}
          </div>
        )}

        {!loadingAgent && agent && (
          <>
            {/* Tab Bar */}
            <div className="flex gap-1 mb-4 border-b" style={{ borderColor: '#e5e7eb' }}>
              <button
                onClick={() => setActiveTab('manager')}
                className={`flex items-center gap-1.5 px-4 py-2 text-sm font-medium rounded-t-lg border-b-2 transition-colors ${
                  activeTab === 'manager'
                    ? 'border-purple-500 text-purple-700 bg-white'
                    : 'border-transparent text-gray-500 hover:text-gray-700 hover:bg-gray-50'
                }`}
              >
                <User className="w-4 h-4" />
                {t('prompt_tab_manager')}
              </button>
              {subagents.map((sa: SubAgentData, i: number) => (
                <button
                  key={sa.name}
                  onClick={() => setActiveTab(sa.name)}
                  className={`flex items-center gap-1.5 px-4 py-2 text-sm font-medium rounded-t-lg border-b-2 transition-colors ${
                    activeTab === sa.name
                      ? 'border-purple-500 text-purple-700 bg-white'
                      : 'border-transparent text-gray-500 hover:text-gray-700 hover:bg-gray-50'
                  }`}
                >
                  <GitBranch className="w-4 h-4" />
                  {sa.name}
                </button>
              ))}
            </div>

            {/* Tab Content */}
            <div className="min-h-[400px]">
              {/* Manager Tab */}
              {activeTab === 'manager' && (
                <div>
                  {/* Model selector for assembly preview */}
                  <div className="mb-4 flex items-center gap-3">
                    <label className="text-xs font-medium uppercase" style={{ color: '#6b7280' }}>{t('prompt_preview_model')}</label>
                    <select
                      value={agent.config?.model || 'deepseek:chat'}
                      disabled
                      className="px-2 py-1 text-xs border rounded bg-gray-50 text-gray-500"
                      style={{ borderColor: '#d1d5db' }}
                    >
                      <option value={agent.config?.model}>{agent.config?.model}</option>
                    </select>
                  </div>

                  <PromptCanvas
                    model={agent.config?.model || 'deepseek:chat'}
                    systemPrompt={systemPrompt}
                    customPrompt={customPrompt || undefined}
                    customSuffix={customSuffix || undefined}
                    onSystemPromptChange={setSystemPrompt}
                    onCustomPromptChange={setCustomPrompt}
                    onCustomSuffixChange={setCustomSuffix}
                  />
                </div>
              )}

              {/* Subagent Tabs */}
              {subagents.map((sa: SubAgentData, i: number) => (
                activeTab === sa.name && (
                  <div key={sa.name}>
                    <div className="mb-4 p-3 rounded-lg border bg-white dark:bg-panel-dark" style={{ borderColor: '#e5e7eb' }}>
                      <div className="flex items-center justify-between">
                        <div>
                          <span className="text-sm font-semibold" style={{ color: '#111827' }}>{sa.name}</span>
                          <span className="text-xs ml-2" style={{ color: '#6b7280' }}>{sa.description}</span>
                        </div>
                        <span className="text-xs px-2 py-0.5 rounded bg-gray-100" style={{ color: '#374151' }}>
                          {t('prompt_preview_model')} {sa.model || t('prompt_model_inherited')} · {t('prompt_tools_count', { count: sa.tools.length })}
                        </span>
                      </div>
                    </div>

                    <PromptCanvas
                      model={sa.model || agent.config?.model || 'deepseek:chat'}
                      systemPrompt={subagentPrompts[i] || ''}
                      onSystemPromptChange={(val) => updateSubagentPrompt(i, val)}
                    />
                  </div>
                )
              ))}
            </div>

            {/* Bottom save bar */}
            <div className="mt-6 flex items-center justify-between p-4 rounded-lg border bg-white dark:bg-panel-dark" style={{ borderColor: '#e5e7eb' }}>
              <span className="text-xs" style={{ color: '#6b7280' }}>
                {t('prompt_editing')} <strong>{agent.name}</strong>
                {subagents.length > 0 && ` · ${t('prompt_subagent_count', { count: subagents.length })}`}
              </span>
              <button
                onClick={handleSave}
                disabled={saving}
                className="flex items-center gap-1.5 text-sm px-4 py-2 rounded-lg bg-primary text-white hover:opacity-90 disabled:opacity-40"
              >
                {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : <Save className="w-4 h-4" />}
                {t('prompt_save_all_changes')}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
