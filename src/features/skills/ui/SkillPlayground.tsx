/**
 * SkillPlayground — test a skill against a real user query via LLM.
 *
 * Phase 1 (direct LLM test):
 * - User picks a skill + types a query
 * - Backend builds a system prompt from skill.instructions + tools + triggers
 * - DeepSeek chat runs the query → returns response
 * - UI shows: matched skills, agent output, system prompt (for debugging)
 *
 * No agent framework, no real tool execution — just verifies the skill's
 * instructions produce a sensible answer.
 */
import React, { useEffect, useState } from 'react';
import { Play, RotateCcw, X, Copy, Check } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import apiClient from '../../../lib/api-client';

interface Skill {
  skill_id: string;
  name: string;
  description?: string;
  triggers?: string[];
  tags?: string[];
  allowed_tools?: string[];
  source_type?: string;
}

interface MatchedSkill {
  skill_id: string;
  name: string;
  score: number;
  match_reason: string;
}

interface PlaygroundResult {
  matched: MatchedSkill[];
  agent_output: string;
  system_prompt: string;
  skill: {
    skill_id: string;
    name: string;
    description: string;
    triggers: string[];
    tags: string[];
    allowed_tools: string[];
  };
  model: string;
  elapsed_ms: number;
}

interface SkillPlaygroundProps {
  initialSkillId?: string;
  onClose: () => void;
}

const SkillPlayground: React.FC<SkillPlaygroundProps> = ({ initialSkillId, onClose }) => {
  const { t } = useTranslation('chat');

  const [skills, setSkills] = useState<Skill[]>([]);
  const [selectedSkillId, setSelectedSkillId] = useState<string>(initialSkillId || '');
  const [query, setQuery] = useState<string>('');
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<PlaygroundResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [copiedPrompt, setCopiedPrompt] = useState(false);
  const [showSystemPrompt, setShowSystemPrompt] = useState(false);

  // Load skill list
  useEffect(() => {
    (async () => {
      try {
        const resp = await apiClient.get('/api/skills');
        setSkills(resp.data || []);
        if (!selectedSkillId && resp.data && resp.data.length > 0) {
          // Prefer a personal skill if available, else first one
          const personal = resp.data.find((s: Skill) => s.source_type === 'personal');
          setSelectedSkillId(personal?.skill_id || resp.data[0].skill_id);
        }
      } catch (err: any) {
        setError(`Failed to load skills: ${err.message}`);
      }
    })();
  }, []);

  const handleRun = async () => {
    if (!selectedSkillId || !query.trim()) return;
    setRunning(true);
    setError(null);
    setResult(null);
    try {
      const resp = await apiClient.post('/api/skills/playground/run', {
        skill_id: selectedSkillId,
        query: query.trim(),
      });
      setResult(resp.data);
    } catch (e: any) {
      const msg = e.response?.data?.detail || e.message || 'Run failed';
      setError(typeof msg === 'string' ? msg : JSON.stringify(msg));
    } finally {
      setRunning(false);
    }
  };

  const handleCopyPrompt = () => {
    if (!result?.system_prompt) return;
    navigator.clipboard.writeText(result.system_prompt);
    setCopiedPrompt(true);
    setTimeout(() => setCopiedPrompt(false), 1500);
  };

  const selectedSkill = skills.find((s) => s.skill_id === selectedSkillId);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center"
      style={{ backgroundColor: 'rgba(0,0,0,0.5)' }}
      onClick={onClose}
    >
      <div
        className="bg-white dark:bg-panel-dark rounded-xl shadow-2xl flex flex-col"
        style={{
          width: '90vw',
          maxWidth: 1200,
          height: '90vh',
        }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-3 border-b" style={{ borderColor: '#E8E4DA' }}>
          <div className="flex items-center gap-2">
            <span className="text-xl">🛝</span>
            <h2 className="text-base font-semibold">Skill Playground</h2>
            <span className="text-[10px] text-gray-500 ml-2">
              (Phase 1 — direct LLM test via DeepSeek chat)
            </span>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 rounded hover:bg-gray-100 dark:hover:bg-gray-800"
          >
            <X size={16} />
          </button>
        </div>

        {/* Body: 2-column layout */}
        <div className="flex-1 grid grid-cols-[1fr_1.5fr] gap-0 overflow-hidden">
          {/* === LEFT: Configuration === */}
          <div className="border-r overflow-y-auto" style={{ borderColor: '#E8E4DA' }}>
            <div className="p-4 space-y-3">
              {/* Skill selector */}
              <div>
                <label className="block text-xs font-medium text-gray-700 mb-1 uppercase">
                  Skill to test
                </label>
                <select
                  value={selectedSkillId}
                  onChange={(e) => setSelectedSkillId(e.target.value)}
                  className="w-full px-3 py-2 bg-white border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-primary"
                >
                  {skills.map((s) => (
                    <option key={s.skill_id} value={s.skill_id}>
                      {s.name} ({s.source_type === 'builtin' ? '🔧' : '👤'}) — {s.skill_id}
                    </option>
                  ))}
                </select>
              </div>

              {/* Skill preview */}
              {selectedSkill && (
                <div className="rounded-lg border p-3 space-y-2" style={{ borderColor: '#E8E4DA', backgroundColor: '#FAF9F5' }}>
                  <div className="text-xs font-semibold text-gray-800">{selectedSkill.name}</div>
                  <div className="text-[11px] text-gray-600 line-clamp-3">
                    {selectedSkill.description || '(no description)'}
                  </div>
                  <div className="flex flex-wrap gap-1">
                    {(selectedSkill.tags || []).map((t) => (
                      <span key={t} className="text-[10px] px-1.5 py-0.5 rounded bg-gray-100 text-gray-700">
                        #{t}
                      </span>
                    ))}
                  </div>
                  <div className="text-[10px] text-gray-500 mt-2">
                    <div><strong>Triggers:</strong> {selectedSkill.triggers?.length || 0}</div>
                    <div><strong>Tools:</strong> {(selectedSkill.allowed_tools || []).join(', ') || '(none)'}</div>
                  </div>
                </div>
              )}

              {/* User query */}
              <div>
                <label className="block text-xs font-medium text-gray-700 mb-1 uppercase">
                  User Query
                </label>
                <textarea
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder="e.g. What's the latest news on AI agents?"
                  rows={5}
                  className="w-full px-3 py-2 bg-white border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-primary"
                />
              </div>

              {/* Run button */}
              <div className="flex gap-2">
                <button
                  onClick={handleRun}
                  disabled={running || !selectedSkillId || !query.trim()}
                  className="flex items-center gap-1.5 px-4 py-2 rounded-lg text-sm font-medium text-white disabled:opacity-50"
                  style={{ backgroundColor: 'var(--color-primary)' }}
                >
                  <Play size={14} />
                  {running ? 'Running…' : '▶ Run'}
                </button>
                <button
                  onClick={() => { setQuery(''); setResult(null); setError(null); }}
                  className="flex items-center gap-1.5 px-3 py-2 rounded-lg text-sm font-medium bg-gray-100 hover:bg-gray-200"
                >
                  <RotateCcw size={14} />
                  Reset
                </button>
              </div>

              {/* Quick examples */}
              <div>
                <div className="text-[10px] text-gray-500 mb-1">Quick examples:</div>
                <div className="space-y-1">
                  {[
                    'What is the latest news on AI agents?',
                    'Help me write pytest tests for my code',
                    'Search for documentation about LangGraph',
                  ].map((ex) => (
                    <button
                      key={ex}
                      onClick={() => setQuery(ex)}
                      className="block w-full text-left text-[11px] px-2 py-1 rounded hover:bg-gray-100 text-gray-600"
                    >
                      → {ex}
                    </button>
                  ))}
                </div>
              </div>
            </div>
          </div>

          {/* === RIGHT: Results === */}
          <div className="overflow-y-auto bg-gray-50">
            {!result && !error && (
              <div className="p-6 text-center text-gray-500 text-sm">
                <div className="text-4xl mb-3">🛝</div>
                <div>Pick a skill, type a query, hit Run.</div>
                <div className="text-[11px] mt-2 text-gray-400">
                  The skill's instructions + tools + triggers will be injected into a system prompt,
                  then DeepSeek chat will answer the query.
                </div>
              </div>
            )}

            {error && (
              <div className="m-4 p-4 rounded-lg border" style={{ backgroundColor: '#FEE2E2', borderColor: '#FCA5A5', color: '#991B1B' }}>
                <div className="font-semibold text-sm">Error</div>
                <div className="text-xs mt-1 font-mono">{error}</div>
              </div>
            )}

            {result && (
              <div className="p-4 space-y-4">
                {/* Header summary */}
                <div className="flex items-center justify-between text-xs text-gray-500">
                  <div>
                    <strong>{result.skill.name}</strong> · model: <code>{result.model}</code> · {result.elapsed_ms}ms
                  </div>
                </div>

                {/* Matched skills */}
                {result.matched.length > 0 && (
                  <div className="bg-white rounded-lg border p-3" style={{ borderColor: '#E8E4DA' }}>
                    <div className="text-[10px] text-gray-500 uppercase mb-2">
                      🎯 Matched Skills ({result.matched.length})
                    </div>
                    {result.matched.map((m) => (
                      <div
                        key={m.skill_id}
                        className="flex items-center justify-between py-1.5 border-b last:border-b-0"
                        style={{ borderColor: '#F3F4F6' }}
                      >
                        <div>
                          <div className="text-sm font-medium">
                            {m.name}
                            {m.skill_id === result.skill.skill_id && (
                              <span className="ml-2 text-[10px] px-1.5 py-0.5 rounded bg-green-100 text-green-700">
                                USING
                              </span>
                            )}
                          </div>
                          <div className="text-[10px] text-gray-500 font-mono">
                            {m.match_reason.slice(0, 80)}
                          </div>
                        </div>
                        <div
                          className="text-xs font-mono"
                          style={{
                            color: m.score >= 0.7 ? '#10B981' : m.score >= 0.4 ? '#F59E0B' : '#6B7280',
                          }}
                        >
                          {m.score.toFixed(2)}
                        </div>
                      </div>
                    ))}
                  </div>
                )}

                {/* Agent output */}
                <div className="bg-white rounded-lg border p-3" style={{ borderColor: '#E8E4DA' }}>
                  <div className="text-[10px] text-gray-500 uppercase mb-2">
                    🤖 Agent Output
                  </div>
                  <div className="text-sm whitespace-pre-wrap text-gray-800">
                    {result.agent_output}
                  </div>
                </div>

                {/* System prompt (collapsible) */}
                <div className="bg-white rounded-lg border" style={{ borderColor: '#E8E4DA' }}>
                  <button
                    onClick={() => setShowSystemPrompt((s) => !s)}
                    className="w-full px-3 py-2 flex items-center justify-between text-left"
                  >
                    <span className="text-[10px] text-gray-500 uppercase">
                      📋 System Prompt ({result.system_prompt.length} chars)
                    </span>
                    <span className="text-gray-400 text-xs">{showSystemPrompt ? '▾' : '▸'}</span>
                  </button>
                  {showSystemPrompt && (
                    <div className="px-3 pb-3">
                      <button
                        onClick={handleCopyPrompt}
                        className="flex items-center gap-1 text-[10px] px-2 py-0.5 rounded bg-gray-100 hover:bg-gray-200 mb-2"
                      >
                        {copiedPrompt ? <Check size={10} /> : <Copy size={10} />}
                        {copiedPrompt ? 'Copied' : 'Copy'}
                      </button>
                      <pre className="text-[10px] font-mono text-gray-700 bg-gray-50 p-2 rounded border overflow-x-auto whitespace-pre-wrap">
                        {result.system_prompt}
                      </pre>
                    </div>
                  )}
                </div>
              </div>
            )}
          </div>
        </div>

        {/* Footer */}
        <div className="px-5 py-2.5 border-t text-[11px] text-gray-500 flex items-center justify-between" style={{ borderColor: '#E8E4DA' }}>
          <span>
            💡 Phase 1 simulates agent execution by injecting the skill's instructions into a system prompt.
            Phase 2 will wire up real agent + tool execution.
          </span>
          <button
            onClick={onClose}
            className="px-3 py-1 text-xs rounded bg-gray-100 hover:bg-gray-200"
          >
            Close
          </button>
        </div>
      </div>
    </div>
  );
};

export default SkillPlayground;