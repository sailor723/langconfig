/**
 * PromptAssemblyPage - Standalone page for prompt assembly preview
 *
 * Shows the 4 prompt components (USER → BASE/CUSTOM → SUFFIX)
 * as stacked blocks in a canvas layout with a live preview area.
 */

import { useState } from 'react';
import PromptCanvas from '../features/agents/ui/PromptCanvas';
import apiClient from '../lib/api-client';
import { Layers, Sparkles, Save, Check, X, Loader2 } from 'lucide-react';

const MODELS = [
  'deepseek:chat',
  'openai:gpt-4o',
  'anthropic:claude-sonnet-4-6',
  'google_genai:gemini-3.1-pro-preview',
];

const EXAMPLE_PROMPTS: Record<string, string> = {
  'Customer Support': 'You are a customer-support agent for ACME Corp. Be polite, concise, and helpful. Always escalate technical issues to a human agent.',
  'Code Researcher': 'You are an expert code researcher. Analyze codebases thoroughly, provide detailed explanations, and cite relevant files.',
  'Data Analyst': 'You are a data analyst. Interpret data, create visualizations, and provide actionable insights. Always explain your methodology.',
  'Custom': '',
};

export default function PromptAssemblyPage() {
  const [model, setModel] = useState('deepseek:chat');
  const [systemPrompt, setSystemPrompt] = useState(EXAMPLE_PROMPTS['Customer Support']);
  const [customPrompt, setCustomPrompt] = useState('');
  const [customSuffix, setCustomSuffix] = useState('');
  const [selectedExample, setSelectedExample] = useState('Customer Support');

  // Save dialog state
  const [showSaveDialog, setShowSaveDialog] = useState(false);
  const [agents, setAgents] = useState<any[]>([]);
  const [saveLoading, setSaveLoading] = useState(false);
  const [saveSuccess, setSaveSuccess] = useState<string | null>(null);

  const loadAgents = async () => {
    setSaveLoading(true);
    try {
      const res = await apiClient.listDeepAgents() as any;
      const list = Array.isArray(res) ? res : res.data || [];
      setAgents(list);
    } catch (err) {
      console.error('Failed to load agents:', err);
    } finally {
      setSaveLoading(false);
    }
  };

  const handleSaveToAgent = async (agent: any) => {
    setSaveLoading(true);
    try {
      await apiClient.saveAgentPrompt(agent.id, customPrompt || undefined, customSuffix || undefined);
      setSaveSuccess(`Saved to "${agent.name}"`);
      setTimeout(() => { setShowSaveDialog(false); setSaveSuccess(null); }, 1500);
    } catch (err) {
      console.error('Failed to save:', err);
      setSaveSuccess(null);
    } finally {
      setSaveLoading(false);
    }
  };

  const handleExampleSelect = (key: string) => {
    setSelectedExample(key);
    setSystemPrompt(EXAMPLE_PROMPTS[key]);
  };

  return (
    <div className="flex-1 overflow-y-auto p-6" style={{ backgroundColor: '#f0f2f5' }}>
      <div className="max-w-5xl mx-auto">
        {/* Header */}
        <div className="mb-6">
          <div className="flex items-center gap-3 mb-2">
            <Layers className="w-8 h-8 text-purple-500" />
            <h1 className="text-2xl font-bold" style={{ color: '#111827' }}>
              Prompt Assembly
            </h1>
            <span className="text-[11px] px-2 py-0.5 rounded-full bg-purple-100 dark:bg-purple-900/30 text-purple-700 dark:text-purple-300 font-medium">
              Experiment
            </span>
          </div>
          <p className="text-sm ml-11" style={{ color: '#4b5563' }}>
            Visualize how the system prompt is assembled from 4 components: <strong>USER</strong> → <strong>BASE</strong> / <strong>CUSTOM</strong> → <strong>SUFFIX</strong>
          </p>
        </div>

        {/* Save to Agent button */}
        <div className="flex items-center justify-end mb-4">
          {saveSuccess ? (
            <span className="flex items-center gap-1.5 text-sm text-green-700 bg-green-100 px-3 py-1.5 rounded-lg">
              <Check className="w-4 h-4" /> {saveSuccess}
            </span>
          ) : (
            <button
              onClick={() => { setShowSaveDialog(true); loadAgents(); }}
              className="flex items-center gap-1.5 text-sm px-4 py-2 rounded-lg border transition-colors bg-white hover:bg-gray-50 border-gray-300 hover:border-gray-400"
              style={{ color: '#374151' }}
            >
              <Save className="w-4 h-4" /> Save to Agent
            </button>
          )}
        </div>

        {/* Controls */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-6">
          {/* Model Selector */}
          <div>
            <label className="block text-xs font-medium mb-1.5 uppercase" style={{ color: '#4b5563' }}>
              Model
            </label>
            <select
              value={model}
              onChange={(e) => setModel(e.target.value)}
              className="w-full px-3 py-2 text-sm border rounded-lg focus:outline-none focus:ring-2 focus:ring-primary"
              style={{
                backgroundColor: '#fff',
                color: '#1f2937',
                borderColor: '#d1d5db',
              }}
            >
              {MODELS.map(m => (
                <option key={m} value={m}>{m}</option>
              ))}
            </select>
          </div>

          {/* Example Prompts */}
          <div>
            <label className="block text-xs font-medium mb-1.5 uppercase" style={{ color: '#4b5563' }}>
              Example Prompt
            </label>
            <div className="flex gap-2 flex-wrap">
              {Object.keys(EXAMPLE_PROMPTS).map(key => (
                <button
                  key={key}
                  onClick={() => handleExampleSelect(key)}
                  className={`text-xs px-3 py-1.5 rounded-lg border transition-colors ${
                    selectedExample === key
                      ? 'bg-purple-100 dark:bg-purple-900/30 border-purple-300 dark:border-purple-700 text-purple-700 dark:text-purple-300'
                      : 'bg-white border-gray-300 hover:bg-gray-100'
                  }`}
                  style={{ color: selectedExample === key ? undefined : '#374151' }}
                >
                  {key}
                </button>
              ))}
            </div>
          </div>
        </div>

        {/* Custom Prompt & Suffix Controls */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-6">
          <div>
            <label className="block text-xs font-medium mb-1.5 uppercase" style={{ color: '#4b5563' }}>
              Custom Prompt <span className="text-purple-500">(replaces BASE)</span>
            </label>
            <textarea
              value={customPrompt}
              onChange={(e) => setCustomPrompt(e.target.value)}
              rows={3}
              placeholder="Leave empty to use SDK default BASE prompt..."
              className="w-full px-3 py-2 text-xs font-mono border rounded-lg focus:outline-none focus:ring-2 focus:ring-primary resize-none"
              style={{
                backgroundColor: '#fff',
                color: '#1f2937',
                borderColor: '#d1d5db',
              }}
            />
          </div>
          <div>
            <label className="block text-xs font-medium mb-1.5 uppercase" style={{ color: '#4b5563' }}>
              Custom Suffix <span className="text-amber-500">(appended last)</span>
            </label>
            <textarea
              value={customSuffix}
              onChange={(e) => setCustomSuffix(e.target.value)}
              rows={3}
              placeholder="Leave empty for no suffix..."
              className="w-full px-3 py-2 text-xs font-mono border rounded-lg focus:outline-none focus:ring-2 focus:ring-primary resize-none"
              style={{
                backgroundColor: '#fff',
                color: '#1f2937',
                borderColor: '#d1d5db',
              }}
            />
          </div>
        </div>

        {/* Prompt Canvas */}
        <PromptCanvas
          model={model}
          systemPrompt={systemPrompt}
          customPrompt={customPrompt || undefined}
          customSuffix={customSuffix || undefined}
          onSystemPromptChange={(val) => {
            setSystemPrompt(val);
            setSelectedExample('Custom');
          }}
          onCustomPromptChange={(val) => setCustomPrompt(val)}
          onCustomSuffixChange={(val) => setCustomSuffix(val)}
        />

        {/* Info Footer */}
        <div className="mt-6 p-4 rounded-lg border" style={{
          backgroundColor: '#fff',
          borderColor: '#d1d5db',
        }}>
          <div className="flex items-start gap-3">
            <Sparkles className="w-5 h-5 text-purple-500 mt-0.5" />
            <div>
              <h3 className="text-sm font-medium mb-1" style={{ color: '#111827' }}>
                How Prompt Assembly Works
              </h3>
              <ul className="text-xs space-y-1" style={{ color: '#4b5563' }}>
                <li><strong className="text-blue-600">USER</strong> — Your custom instructions, passed as <code>system_prompt=</code></li>
                <li><strong className="text-gray-600">BASE</strong> — SDK default prompt (<code>BASE_AGENT_PROMPT</code>), always present</li>
                <li><strong className="text-purple-600">CUSTOM</strong> — HarnessProfile override, replaces BASE when set</li>
                <li><strong className="text-amber-600">SUFFIX</strong> — Model-specific profile suffix, appended last</li>
              </ul>
              <p className="text-xs mt-2" style={{ color: '#4b5563' }}>
                Assembly order: <code>USER + &quot;\n\n&quot; + (BASE or CUSTOM) + (&quot;\n\n&quot; + SUFFIX if present)</code>
              </p>
            </div>
          </div>
        </div>
      </div>

      {/* Save to Agent Dialog */}
      {showSaveDialog && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40" onClick={() => setShowSaveDialog(false)}>
          <div className="bg-white rounded-xl shadow-xl max-w-lg w-full mx-4 max-h-[70vh] flex flex-col" onClick={e => e.stopPropagation()}>
            <div className="flex items-center justify-between px-5 py-4 border-b border-gray-200">
              <h3 className="text-base font-semibold" style={{ color: '#111827' }}>Save Prompt to Agent</h3>
              <button onClick={() => setShowSaveDialog(false)} className="p-1 hover:bg-gray-100 rounded">
                <X className="w-5 h-5 text-gray-500" />
              </button>
            </div>
            <div className="flex-1 overflow-y-auto p-4 space-y-2">
              {agents.length === 0 && saveLoading ? (
                <div className="flex items-center justify-center py-8">
                  <Loader2 className="w-5 h-5 animate-spin text-gray-400" />
                </div>
              ) : agents.length === 0 ? (
                <p className="text-sm text-center py-8" style={{ color: '#6b7280' }}>No agents found. Create one first in Agents page.</p>
              ) : (
                agents.map(agent => (
                  <button
                    key={agent.id}
                    onClick={() => handleSaveToAgent(agent)}
                    disabled={saveLoading}
                    className="w-full text-left px-4 py-3 rounded-lg border border-gray-200 hover:border-purple-300 hover:bg-purple-50 transition-colors disabled:opacity-50"
                  >
                    <div className="font-medium text-sm" style={{ color: '#111827' }}>{agent.name}</div>
                    {agent.description && (
                      <div className="text-xs mt-0.5" style={{ color: '#6b7280' }}>{agent.description.slice(0, 100)}</div>
                    )}
                  </button>
                ))
              )}
            </div>
            <div className="px-5 py-3 border-t border-gray-100 text-xs text-gray-400">
              Saves <strong>Custom Prompt</strong> (replaces BASE) and <strong>Custom Suffix</strong> (appended last) to agent config
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
