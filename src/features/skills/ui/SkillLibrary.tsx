/**
 * Copyright (c) 2025 Cade Russell (Ghost Peony)
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */

import { useState, useEffect, useMemo, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import {
  Search,
  RefreshCw,
  X,
  BookOpen,
  Bot,
  Zap,
  Tag,
  Clock,
  TrendingUp,
  ChevronDown,
  ChevronRight,
  Plus,
  Pencil,
  Trash2,
} from 'lucide-react';
import apiClient from '../../../lib/api-client';
import type { Skill, SkillDetail, SkillsSummary, SkillSourceFilter } from '../types';
import SkillBuilderModal from '../../agents/ui/SkillBuilderModal';

interface SkillLibraryProps {
  onSelectSkill?: (skill: Skill) => void;
  selectedSkillIds?: string[];
  multiSelect?: boolean;
}

export default function SkillLibrary({
  onSelectSkill,
  selectedSkillIds = [],
  multiSelect = false,
}: SkillLibraryProps) {
  const { t } = useTranslation('chat');

  const SOURCE_LABELS: Record<string, string> = {
    builtin: t('skills_source_builtin'),
    personal: t('skills_source_personal'),
    project: t('skills_source_project'),
  };

  // State
  const [skills, setSkills] = useState<Skill[]>([]);
  // Maps skill_id → number of agents that reference this skill
  const [agentCounts, setAgentCounts] = useState<Record<string, number>>({});
  const [summary, setSummary] = useState<SkillsSummary | null>(null);
  const [selectedSkill, setSelectedSkill] = useState<SkillDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Filters
  const [searchQuery, setSearchQuery] = useState('');
  const [sourceFilter, setSourceFilter] = useState<SkillSourceFilter>('all');
  const [tagFilter, setTagFilter] = useState<string | null>(null);
  const [expandedSections, setExpandedSections] = useState<Set<string>>(new Set(['builtin', 'personal', 'project']));
  const [showCreateModal, setShowCreateModal] = useState(false);
  // Edit/Delete state
  const [editingSkill, setEditingSkill] = useState<Skill | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);

  // Fetch "Used by N agents" counts for each skill (parallel with skills list)
  const fetchAgentCounts = useCallback(async (skillList: Skill[]) => {
    try {
      const results = await Promise.all(
        skillList.map(async (s) => {
          try {
            const res = await apiClient.get(`/api/skills/${encodeURIComponent(s.skill_id)}/agents`);
            return [s.skill_id, (res as any).agent_count ?? 0] as const;
          } catch {
            return [s.skill_id, 0] as const;
          }
        })
      );
      const map: Record<string, number> = {};
      for (const [id, count] of results) map[id] = count;
      setAgentCounts(map);
    } catch (err) {
      // Non-fatal — leave counts at previous values
    }
  }, []);

  // Fetch skills
  const fetchSkills = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams();
      if (sourceFilter !== 'all') params.append('source_type', sourceFilter);
      if (tagFilter) params.append('tag', tagFilter);
      if (searchQuery) params.append('search', searchQuery);

      const queryString = params.toString();
      const url = queryString ? `/api/skills?${queryString}` : '/api/skills';

      const response = await apiClient.get(url);
      setSkills(response.data);
      // Fetch reverse-link counts in background (non-blocking)
      fetchAgentCounts(response.data);
    } catch (err: any) {
      setError(err.message || t('skills_error_failed'));
      console.error('Error fetching skills:', err);
    } finally {
      setLoading(false);
    }
  }, [sourceFilter, tagFilter, searchQuery]);

  // Fetch summary
  const fetchSummary = useCallback(async () => {
    try {
      const response = await apiClient.get('/api/skills/summary');
      setSummary(response.data);
    } catch (err) {
      console.error('Error fetching skills summary:', err);
    }
  }, []);

  // Fetch skill details
  const fetchSkillDetail = useCallback(async (skillId: string) => {
    try {
      const response = await apiClient.get(`/api/skills/${skillId}`);
      setSelectedSkill(response.data);
    } catch (err) {
      console.error('Error fetching skill details:', err);
    }
  }, []);

  // Initial load
  useEffect(() => {
    fetchSkills();
    fetchSummary();
  }, []);

  // Debounced search
  useEffect(() => {
    const timer = setTimeout(() => {
      fetchSkills();
    }, 300);
    return () => clearTimeout(timer);
  }, [searchQuery, sourceFilter, tagFilter]);

  // Reload skills from filesystem
  const handleReload = async () => {
    setLoading(true);
    try {
      await apiClient.post('/api/skills/reload-all');
      await fetchSkills();
      await fetchSummary();
    } catch (err: any) {
      setError(err.message || 'Failed to reload skills');
    } finally {
      setLoading(false);
    }
  };

  // Handle skill selection
  const handleSkillClick = (skill: Skill) => {
    if (onSelectSkill) {
      onSelectSkill(skill);
    }
    fetchSkillDetail(skill.skill_id);
  };

  // Delete the currently-selected skill
  const handleDeleteSkill = async () => {
    if (!selectedSkill) return;
    setDeleting(true);
    // Close both modals immediately for snappy UX
    setConfirmDelete(false);
    setSelectedSkill(null);
    setEditingSkill(null);
    try {
      await apiClient.delete(`/api/skills/${encodeURIComponent(selectedSkill.skill_id)}`);
      // Refresh the list in the background
      await Promise.all([fetchSkills(), fetchSummary()]);
    } catch (err: any) {
      const msg = err.response?.data?.detail || err.message || 'Failed to delete skill';
      // Re-open the detail panel so the user can retry
      try {
        const resp = await apiClient.get(`/api/skills/${encodeURIComponent(selectedSkill.skill_id)}`);
        setSelectedSkill(resp.data);
      } catch {
        // If the skill no longer exists, leave it closed
      }
      setError(msg);
    } finally {
      setDeleting(false);
    }
  };

  // Open the editor for a skill. If the detail (with instructions) isn't loaded
// yet, fetch it first so the builder is pre-filled.
  const handleEditSkill = async (skill: Skill) => {
    if (selectedSkill?.skill_id !== skill.skill_id || !selectedSkill.instructions) {
      try {
        const resp = await apiClient.get(`/api/skills/${encodeURIComponent(skill.skill_id)}`);
        setSelectedSkill(resp.data);
      } catch (err) {
        // Non-fatal — builder will just lack instructions
        console.warn('Could not pre-fetch instructions for editing', err);
      }
    }
    setEditingSkill(skill);
  };

  // Auto-select a skill if one was requested from DeepAgent Studio
  // (e.g. user clicked 'Open in Builder' in SubAgentDetailModal).
  useEffect(() => {
    const pendingId = sessionStorage.getItem('da:pending-skill-select');
    if (!pendingId || skills.length === 0) return;
    const match = skills.find(s => s.skill_id === pendingId);
    if (match) {
      handleSkillClick(match);
      sessionStorage.removeItem('da:pending-skill-select');
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [skills]);

  // Group skills by source
  const skillsBySource = useMemo(() => {
    const grouped: Record<string, Skill[]> = {
      builtin: [],
      personal: [],
      project: [],
    };
    skills.forEach((skill) => {
      if (grouped[skill.source_type]) {
        grouped[skill.source_type].push(skill);
      }
    });
    return grouped;
  }, [skills]);

  // Get available tags from summary
  const availableTags = useMemo(() => {
    if (!summary?.top_tags) return [];
    return Object.entries(summary.top_tags)
      .sort((a, b) => b[1] - a[1])
      .map(([tag]) => tag);
  }, [summary]);

  const toggleSection = (section: string) => {
    setExpandedSections((prev) => {
      const next = new Set(prev);
      if (next.has(section)) {
        next.delete(section);
      } else {
        next.add(section);
      }
      return next;
    });
  };

  const formatLastUsed = (dateStr: string | null) => {
    if (!dateStr) return t('skills_never');
    const date = new Date(dateStr);
    const now = new Date();
    const diffMs = now.getTime() - date.getTime();
    const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24));

    if (diffDays === 0) return t('skills_today');
    if (diffDays === 1) return t('skills_yesterday');
    if (diffDays < 7) return t('skills_days_ago', { count: diffDays });
    return date.toLocaleDateString();
  };

  return (
    <div className="flex-1 overflow-y-auto" style={{ backgroundColor: 'var(--color-background-dark)' }}>
      <div className="max-w-7xl mx-auto p-4">
        <div className="bg-white dark:bg-panel-dark border border-gray-200 dark:border-border-dark rounded-lg p-4">
        {/* Header */}
        <div className="mb-4">
          <div className="flex items-start gap-3">
            <div
              className="w-10 h-10 rounded-lg flex items-center justify-center flex-shrink-0"
              style={{ backgroundColor: 'var(--color-background-light)' }}
            >
              <Zap className="w-5 h-5" style={{ color: 'var(--color-primary)' }} />
            </div>
            <div className="flex-1">
              <h1 className="text-sm font-semibold mb-0.5" style={{ color: 'var(--color-text-primary)' }}>
                {t('skills_library_title')}
              </h1>
              <p className="text-[11px]" style={{ color: 'var(--color-text-muted)' }}>
                {t('skills_library_subtitle')}
              </p>
              {summary && (
                <div className="flex items-center gap-3 mt-1.5">
                  <span className="text-[10px] px-2 py-0.5 rounded-md font-medium" style={{
                    backgroundColor: 'var(--color-primary)',
                    color: 'white'
                  }}>
                    {t('skills_count', { count: summary.total_skills })}
                  </span>
                  {Object.entries(summary.by_source).map(([source, count]) => (
                    <span key={source} className="text-[10px]" style={{ color: 'var(--color-text-muted)' }}>
                      {SOURCE_LABELS[source]}: {count}
                    </span>
                  ))}
                </div>
              )}
            </div>
            <button
              onClick={() => setShowCreateModal(true)}
              className="px-2.5 py-1.5 rounded-lg text-[11px] font-medium flex items-center gap-1 transition-colors"
              style={{
                backgroundColor: 'var(--color-primary)',
                color: 'white',
              }}
            >
              <Plus className="w-3.5 h-3.5" />
              {t('skills_create')}
            </button>
            <button
              onClick={handleReload}
              disabled={loading}
              className="px-2.5 py-1.5 rounded-lg text-[11px] font-medium flex items-center gap-1 transition-colors border"
              style={{
                borderColor: 'var(--color-border-dark)',
                color: 'var(--color-text-primary)',
              }}
            >
              <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
            </button>
          </div>
        </div>

        {/* Search and Filters */}
        <div className="mb-4 space-y-2">
          <div className="relative">
            <Search className="absolute left-2.5 top-1/2 transform -translate-y-1/2 w-3.5 h-3.5" style={{ color: 'var(--color-text-muted)' }} />
            <input
              type="text"
              placeholder={t('skills_search')}
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full pl-8 pr-8 py-1.5 border border-gray-200 dark:border-border-dark rounded-lg text-xs focus:outline-none focus:ring-1 focus:ring-primary"
              style={{
                backgroundColor: 'var(--color-input-background)',
                color: 'var(--color-text-primary)',
              }}
            />
            {searchQuery && (
              <button
                onClick={() => setSearchQuery('')}
                className="absolute right-2.5 top-1/2 transform -translate-y-1/2"
                style={{ color: 'var(--color-text-muted)' }}
              >
                <X className="w-3.5 h-3.5" />
              </button>
            )}
          </div>

            {/* Tag Filters */}
            {availableTags.length > 0 && (
              <div className="flex items-center gap-2 flex-wrap">
                <span className="text-xs font-medium" style={{ color: 'var(--color-text-muted)' }}>{t('skills_tags')}</span>
                {availableTags.slice(0, 12).map((tag) => (
                  <button
                    key={tag}
                    onClick={() => setTagFilter(tagFilter === tag ? null : tag)}
                    className="px-2.5 py-1 rounded-md text-xs font-medium border transition-colors"
                    style={{
                      backgroundColor: tagFilter === tag ? 'var(--color-primary)' : 'var(--color-panel-dark)',
                      borderColor: tagFilter === tag ? 'var(--color-primary)' : 'var(--color-border-dark)',
                      color: tagFilter === tag ? 'white' : 'var(--color-text-muted)',
                    }}
                  >
                    {tag}
                  </button>
                ))}
              </div>
            )}
          </div>

          {/* Error */}
          {error && (
            <div className="p-4 rounded-lg mb-6 border" style={{
              backgroundColor: 'rgba(239, 68, 68, 0.1)',
              borderColor: 'rgba(239, 68, 68, 0.3)',
              color: '#ef4444'
            }}>
              {error}
            </div>
          )}

          {/* Skills by Source */}
          <div className="space-y-4">
            {(['builtin', 'personal', 'project'] as const).map((sourceType) => {
              const sourceSkills = skillsBySource[sourceType];
              if (sourceSkills.length === 0 && sourceFilter !== 'all' && sourceFilter !== sourceType) return null;

              const isExpanded = expandedSections.has(sourceType);

              return (
                <div key={sourceType}>
                  {/* Section Header */}
                  <button
                    onClick={() => toggleSection(sourceType)}
                    className="w-full p-3 rounded-lg flex items-center justify-between mb-2"
                    style={{ backgroundColor: 'var(--color-primary)' }}
                  >
                    <div className="flex items-center gap-2">
                      {isExpanded ? (
                        <ChevronDown className="w-4 h-4 text-white" />
                      ) : (
                        <ChevronRight className="w-4 h-4 text-white" />
                      )}
                      <span className="text-sm font-semibold text-white">
                        {SOURCE_LABELS[sourceType]} Skills
                      </span>
                      <span className="text-xs text-white/70">({sourceSkills.length})</span>
                    </div>
                  </button>

                  {/* Skills Grid */}
                  {isExpanded && (
                    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
                      {sourceSkills.length === 0 ? (
                        <div className="col-span-full text-center py-8" style={{ color: 'var(--color-text-muted)' }}>
                          <p className="text-sm">{t('skills_no_skills', { source: SOURCE_LABELS[sourceType].toLowerCase() })}</p>
                        </div>
                      ) : (
                        sourceSkills.map((skill) => (
                          <div
                            key={skill.skill_id}
                            onClick={() => handleSkillClick(skill)}
                            className="p-4 rounded-xl border cursor-pointer transition-all hover:shadow-md"
                            style={{
                              backgroundColor: selectedSkill?.skill_id === skill.skill_id
                                ? 'var(--color-node-background-light)'
                                : 'var(--color-panel-dark)',
                              borderColor: selectedSkill?.skill_id === skill.skill_id
                                ? 'var(--color-primary)'
                                : 'var(--color-border-dark)',
                            }}
                          >
                            {/* Card Header */}
                            <div className="flex items-start gap-3 mb-2">
                              <div
                                className="w-10 h-10 rounded-lg flex items-center justify-center flex-shrink-0"
                                style={{ backgroundColor: 'var(--color-background-light)' }}
                              >
                                <Zap className="w-5 h-5" style={{ color: 'var(--color-primary)' }} />
                              </div>
                              <div className="flex-1 min-w-0">
                                <h3 className="text-sm font-semibold truncate" style={{ color: 'var(--color-text-primary)' }}>
                                  {skill.name}
                                </h3>
                                <span className="text-xs" style={{ color: 'var(--color-text-muted)' }}>
                                  {t('skills_version', { version: skill.version })}
                                </span>
                              </div>
                            </div>

                            {/* Description */}
                            <p className="text-xs mb-3 line-clamp-2" style={{ color: 'var(--color-text-muted)' }}>
                              {skill.description}
                            </p>

                            {/* Tags */}
                            {skill.tags.length > 0 && (
                              <div className="flex items-center gap-1 flex-wrap mb-3">
                                {skill.tags.slice(0, 3).map((tag) => (
                                  <span
                                    key={tag}
                                    className="text-xs px-2 py-0.5 rounded-full"
                                    style={{
                                      backgroundColor: 'var(--color-background-dark)',
                                      color: 'var(--color-text-muted)',
                                    }}
                                  >
                                    {tag}
                                  </span>
                                ))}
                                {skill.tags.length > 3 && (
                                  <span className="text-xs" style={{ color: 'var(--color-text-muted)' }}>
                                    +{skill.tags.length - 3}
                                  </span>
                                )}
                              </div>
                            )}

                            {/* Stats */}
                            <div className="flex items-center gap-2 text-xs flex-wrap" style={{ color: 'var(--color-text-muted)' }}>
                              {/* Reverse link: how many agents reference this skill */}
                              <div
                                className="flex items-center gap-1 px-1.5 py-0.5 rounded font-mono"
                                style={{
                                  backgroundColor: (agentCounts[skill.skill_id] ?? 0) > 0
                                    ? 'rgba(217,119,87,0.12)' : 'transparent',
                                  color: (agentCounts[skill.skill_id] ?? 0) > 0
                                    ? '#A85A2E' : 'var(--color-text-muted)',
                                  border: (agentCounts[skill.skill_id] ?? 0) > 0
                                    ? '1px solid #D97757' : '1px solid transparent',
                                }}
                                title={`Used by ${agentCounts[skill.skill_id] ?? 0} deep agent${(agentCounts[skill.skill_id] ?? 0) === 1 ? '' : 's'}`}
                              >
                                <Bot className="w-3 h-3" />
                                <span>Used by {agentCounts[skill.skill_id] ?? 0}</span>
                              </div>
                              <div className="flex items-center gap-1">
                                <TrendingUp className="w-3 h-3" />
                                <span>{skill.usage_count}</span>
                              </div>
                              <div className="flex items-center gap-1">
                                <Clock className="w-3 h-3" />
                                <span>{formatLastUsed(skill.last_used_at)}</span>
                              </div>
                            </div>
                          </div>
                        ))
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          </div>

          {/* Loading */}
          {loading && skills.length === 0 && (
            <div className="flex items-center justify-center py-12">
              <RefreshCw className="w-6 h-6 animate-spin" style={{ color: 'var(--color-text-muted)' }} />
              <span className="ml-2" style={{ color: 'var(--color-text-muted)' }}>{t('skills_loading')}</span>
            </div>
          )}
        </div>

      {/* Skill Detail Modal */}
      {selectedSkill && (
        <div
          className="fixed inset-0 bg-black/50 flex items-center justify-center p-4 z-50"
          onClick={() => setSelectedSkill(null)}
        >
          <div
            className="bg-gray-50 dark:bg-background-dark border border-gray-200 dark:border-border-dark rounded-xl w-full max-w-3xl max-h-[90vh] flex flex-col shadow-2xl overflow-hidden"
            onClick={(e) => e.stopPropagation()}
          >
            {/* Header */}
            <div className="border-b p-6" style={{
              backgroundColor: 'var(--color-primary)',
              borderBottomColor: 'var(--color-border-dark)'
            }}>
              <div className="flex items-start justify-between gap-4">
                <div className="flex-1 min-w-0">
                  <h2 className="text-2xl font-semibold text-white" style={{ textShadow: '0 1px 2px rgba(0,0,0,0.25)' }}>
                    {selectedSkill.name}
                  </h2>
                  <p className="text-sm mt-1 text-white/90">
                    {SOURCE_LABELS[selectedSkill.source_type]} • {t('skills_version', { version: selectedSkill.version })}
                    {selectedSkill.author && ` • ${t('skills_by_author', { author: selectedSkill.author })}`}
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  {/* Edit button — opens the SkillBuilderModal in edit mode.
                      Disabled for builtin skills (filesystem-managed, not editable from UI). */}
                  {selectedSkill.source_type !== 'builtin' && (
                    <button
                      onClick={() => handleEditSkill(selectedSkill)}
                      className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-white/95 hover:text-white bg-white/15 hover:bg-white/25 rounded-lg transition-colors"
                      style={{ textShadow: '0 1px 2px rgba(0,0,0,0.15)' }}
                      title="Edit this skill (opens builder)"
                    >
                      <Pencil className="w-3.5 h-3.5" />
                      Edit
                    </button>
                  )}
                  {/* Delete button — disabled for builtin skills (per backend 403). */}
                  {selectedSkill.source_type !== 'builtin' && (
                    <button
                      onClick={() => setConfirmDelete(true)}
                      className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-white bg-red-500/80 hover:bg-red-500 rounded-lg transition-colors"
                      style={{ textShadow: '0 1px 2px rgba(0,0,0,0.15)' }}
                      title="Delete this skill (cannot be undone)"
                    >
                      <Trash2 className="w-3.5 h-3.5" />
                      Delete
                    </button>
                  )}
                  <button
                    onClick={() => setSelectedSkill(null)}
                    className="p-2 transition-all text-white/90 hover:text-white hover:bg-white/15 rounded-lg"
                    title="Close"
                  >
                    <X className="w-5 h-5" />
                  </button>
                </div>
              </div>
            </div>

            {/* Body */}
            <div className="flex-1 overflow-y-auto p-6 space-y-6">
              {/* Description */}
              <p className="text-sm leading-relaxed" style={{ color: '#374151' }}>
                {selectedSkill.description}
              </p>

              {/* Stats row */}
              <div className="flex items-center gap-4 text-xs" style={{ color: '#6b7280' }}>
                <span className="flex items-center gap-1">
                  <TrendingUp className="w-3.5 h-3.5" />
                  {t('skills_used_times', { count: selectedSkill.usage_count })}
                </span>
                <span className="flex items-center gap-1">
                  <Clock className="w-3.5 h-3.5" />
                  {t('skills_last_used', { date: formatLastUsed(selectedSkill.last_used_at) })}
                </span>
              </div>

              {/* Triggers */}
              {selectedSkill.triggers.length > 0 && (
                <div>
                  <h4 className="text-xs font-semibold uppercase mb-2" style={{ color: '#6b7280' }}>
                    {t('skills_auto_triggers')}
                  </h4>
                  <div className="flex flex-wrap gap-1.5">
                    {selectedSkill.triggers.map((trigger, i) => (
                      <span
                        key={i}
                        className="text-xs px-2 py-1 rounded-md"
                        style={{ backgroundColor: '#f3f4f6', color: '#374151' }}
                      >
                        {trigger}
                      </span>
                    ))}
                  </div>
                </div>
              )}

              {/* Tags */}
              {selectedSkill.tags.length > 0 && (
                <div>
                  <h4 className="text-xs font-semibold uppercase mb-2" style={{ color: '#6b7280' }}>
                    {t('skills_tags_label')}
                  </h4>
                  <div className="flex flex-wrap gap-1.5">
                    {selectedSkill.tags.map((tag) => (
                      <span
                        key={tag}
                        className="text-xs px-2 py-0.5 rounded-full"
                        style={{ backgroundColor: '#f3f4f6', color: '#6b7280' }}
                      >
                        {tag}
                      </span>
                    ))}
                  </div>
                </div>
              )}

              {/* Instructions */}
              <div>
                <h4 className="text-xs font-semibold uppercase mb-2 flex items-center gap-1" style={{ color: '#6b7280' }}>
                  <BookOpen className="w-3.5 h-3.5" />
                  {t('skills_instructions')}
                </h4>
                <div
                  className="p-4 rounded-lg border"
                  style={{ backgroundColor: '#fff', borderColor: '#e5e7eb' }}
                >
                  <pre className="whitespace-pre-wrap font-mono text-xs leading-relaxed" style={{ color: '#1f2937' }}>
                    {selectedSkill.instructions || t('skills_no_instructions')}
                  </pre>
                </div>
              </div>

              {/* Examples */}
              {selectedSkill.examples && (
                <div>
                  <h4 className="text-xs font-semibold uppercase mb-2" style={{ color: '#6b7280' }}>
                    {t('skills_examples')}
                  </h4>
                  <div
                    className="p-4 rounded-lg border"
                    style={{ backgroundColor: '#fff', borderColor: '#e5e7eb' }}
                  >
                    <pre className="whitespace-pre-wrap font-mono text-xs leading-relaxed" style={{ color: '#1f2937' }}>
                      {selectedSkill.examples}
                    </pre>
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Create Skill Modal */}
      {showCreateModal && (
        <SkillBuilderModal
          onClose={() => setShowCreateModal(false)}
          onSave={() => {
            setShowCreateModal(false);
            fetchSkills();
            fetchSummary();
          }}
        />
      )}

      {/* Edit Skill Modal — reuses SkillBuilderModal in edit mode */}
      {editingSkill && (
        <SkillBuilderModal
          existingSkill={{
            skill_id: editingSkill.skill_id,
            name: editingSkill.name,
            description: editingSkill.description,
            tags: editingSkill.tags,
            triggers: editingSkill.triggers,
            instructions: selectedSkill?.skill_id === editingSkill.skill_id
              ? (selectedSkill?.instructions || '')
              : '',
          }}
          onClose={() => {
            setEditingSkill(null);
            // Re-open detail modal for the skill we just edited
            if (editingSkill) {
              fetchSkillDetail(editingSkill.skill_id).then(() => {
                // The detail fetch updates selectedSkill; if the skill
                // was deleted server-side, leave the modal closed.
              });
            }
          }}
          onSave={() => {
            setEditingSkill(null);
            fetchSkills();
            fetchSummary();
            // Re-open the detail modal with the updated skill
            if (editingSkill) {
              fetchSkillDetail(editingSkill.skill_id);
            }
          }}
        />
      )}

      {/* Delete Confirmation Dialog */}
      {confirmDelete && selectedSkill && (
        <div
          className="fixed inset-0 bg-black/60 flex items-center justify-center p-4 z-[60]"
          onClick={() => setConfirmDelete(false)}
        >
          <div
            className="bg-white dark:bg-panel-dark border border-gray-200 dark:border-border-dark rounded-xl w-full max-w-md shadow-2xl overflow-hidden"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="p-6">
              <div className="flex items-start gap-3">
                <div className="w-10 h-10 rounded-full flex items-center justify-center flex-shrink-0" style={{ backgroundColor: 'rgba(239,68,68,0.1)' }}>
                  <Trash2 className="w-5 h-5" style={{ color: '#ef4444' }} />
                </div>
                <div className="flex-1">
                  <h3 className="text-lg font-semibold" style={{ color: '#1f2937' }}>
                    Delete this skill?
                  </h3>
                  <p className="text-sm mt-1" style={{ color: '#6b7280' }}>
                    You're about to permanently delete{' '}
                    <span className="font-mono font-semibold" style={{ color: '#1f2937' }}>
                      {selectedSkill.skill_id}
                    </span>
                    . This action cannot be undone.
                  </p>
                </div>
              </div>
            </div>
            <div className="flex items-center justify-end gap-2 px-6 py-3 border-t" style={{ backgroundColor: '#f9fafb', borderColor: '#e5e7eb' }}>
              <button
                onClick={() => setConfirmDelete(false)}
                disabled={deleting}
                className="px-4 py-2 rounded-lg text-sm font-medium text-gray-700 dark:text-gray-300 bg-white hover:bg-gray-50 border border-gray-200 transition-colors disabled:opacity-50"
              >
                Cancel
              </button>
              <button
                onClick={handleDeleteSkill}
                disabled={deleting}
                className="px-4 py-2 rounded-lg text-sm font-medium text-white flex items-center gap-2 transition-colors disabled:opacity-50"
                style={{ backgroundColor: '#ef4444' }}
                onMouseEnter={(e) => { if (!deleting) (e.currentTarget as HTMLButtonElement).style.backgroundColor = '#dc2626'; }}
                onMouseLeave={(e) => { (e.currentTarget as HTMLButtonElement).style.backgroundColor = '#ef4444'; }}
              >
                <Trash2 className="w-3.5 h-3.5" />
                {deleting ? 'Deleting…' : 'Delete skill'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
    </div>
  );
}
