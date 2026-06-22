/**
 * Copyright (c) 2025 Cade Russell (Ghost Peony)
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 *
 * SkillBuilderModal — section-based skill editor
 *
 * Inspired by the Agent Skills spec (https://agentskills.io/specification):
 * each SKILL.md is a directory with `SKILL.md` (frontmatter + instructions)
 * + optional `scripts/`, `references/`, `assets/`. This modal exposes each
 * logical section as an independently-editable unit with its own Save
 * button, so users can tweak one part without affecting the others.
 *
 * UX:
 * - Header is draggable (move by dragging the title bar)
 * - Bottom-right corner is resizable (min 600×500)
 * - Five collapsible sections:
 *     1. 📇 Identity       — name, skill_id (id is read-only)
 *     2. 📝 Discovery      — description (router-matching), tags, triggers
 *     3. ⚙️ Configuration  — allowed_tools, version
 *     4. 📜 Body           — SKILL.md instructions (the workflow)
 *     5. 📚 Examples       — optional USER/ASST dialogs
 *     6. 🗂️ Files          — read-only list of scripts/, references/, assets/
 * - Each section header has [Edit] / [Save] / [Cancel] buttons
 * - Top-right has a global Save (saves all pending changes) + X
 */

import { useState, useRef, useEffect, useCallback, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import {
  X,
  Plus,
  Zap,
  BookOpen,
  Save,
  Check,
  RotateCcw,
  ChevronDown,
  ChevronRight,
  GripHorizontal,
  Maximize2,
  FileCode,
  FolderOpen,
  FileText,
  Hash,
} from 'lucide-react';
import apiClient from '@/lib/api-client';

interface SkillBuilderModalProps {
  onClose: () => void;
  onSave?: (skill: any) => void;
  existingSkill?: {
    skill_id: string;
    name: string;
    description: string;
    tags: string[];
    triggers: string[];
    instructions: string;
    examples?: string | null;
    version?: string;
    allowed_tools?: string[] | null;
    source_path?: string;
    source_type?: string;
  };
}

type SectionId = 'identity' | 'discovery' | 'configuration' | 'body' | 'examples' | 'files';

const SkillBuilderModal = ({ onClose, onSave, existingSkill }: SkillBuilderModalProps) => {
  const { t } = useTranslation('chat');
  const isEditing = !!existingSkill;

  // -------- Form state (mirrors the API fields) --------
  const [name, setName] = useState(existingSkill?.name || '');
  const [description, setDescription] = useState(existingSkill?.description || '');
  const [tags, setTags] = useState<string[]>(existingSkill?.tags || ['custom']);
  const [triggers, setTriggers] = useState<string[]>(existingSkill?.triggers || []);
  const [instructions, setInstructions] = useState(existingSkill?.instructions || '');
  const [examples, setExamples] = useState<string>(existingSkill?.examples || '');
  const [allowedTools, setAllowedTools] = useState<string[]>(
    Array.isArray(existingSkill?.allowed_tools) ? existingSkill!.allowed_tools! : []
  );
  const [newTag, setNewTag] = useState('');
  const [newTrigger, setNewTrigger] = useState('');
  const [newTool, setNewTool] = useState('');

  // -------- Section UI state --------
  const [openSections, setOpenSections] = useState<Set<SectionId>>(
    new Set<SectionId>(['discovery', 'body'])
  );
  const [sectionErrors, setSectionErrors] = useState<Record<SectionId, string | null>>({
    identity: null, discovery: null, configuration: null, body: null, examples: null, files: null,
  });
  const [sectionSaving, setSectionSaving] = useState<Record<SectionId, boolean>>({
    identity: false, discovery: false, configuration: false, body: false, examples: false, files: false,
  });

  // -------- Draggable + Resizable state --------
  const [position, setPosition] = useState({ x: 0, y: 0 });
  const [size, setSize] = useState({ width: 880, height: 720 });
  const dragStateRef = useRef<{ active: boolean; startX: number; startY: number; baseX: number; baseY: number }>({
    active: false, startX: 0, startY: 0, baseX: 0, baseY: 0,
  });
  const resizeStateRef = useRef<{ active: boolean; startX: number; startY: number; baseW: number; baseH: number }>({
    active: false, startX: 0, startY: 0, baseW: 0, baseH: 0,
  });
  const containerRef = useRef<HTMLDivElement>(null);

  // Drag handlers
  const handleDragMouseDown = (e: React.MouseEvent) => {
    if ((e.target as HTMLElement).closest('button, input, textarea, select, a, [role="button"]')) return;
    dragStateRef.current = {
      active: true,
      startX: e.clientX,
      startY: e.clientY,
      baseX: position.x,
      baseY: position.y,
    };
    e.preventDefault();
  };
  const handleResizeMouseDown = (e: React.MouseEvent) => {
    resizeStateRef.current = {
      active: true,
      startX: e.clientX,
      startY: e.clientY,
      baseW: size.width,
      baseH: size.height,
    };
    e.preventDefault();
    e.stopPropagation();
  };
  useEffect(() => {
    const onMove = (e: MouseEvent) => {
      if (dragStateRef.current.active) {
        const dx = e.clientX - dragStateRef.current.startX;
        const dy = e.clientY - dragStateRef.current.startY;
        setPosition({
          x: dragStateRef.current.baseX + dx,
          y: dragStateRef.current.baseY + dy,
        });
      }
      if (resizeStateRef.current.active) {
        const dx = e.clientX - resizeStateRef.current.startX;
        const dy = e.clientY - resizeStateRef.current.startY;
        const newW = Math.max(600, resizeStateRef.current.baseW + dx);
        const newH = Math.max(500, resizeStateRef.current.baseH + dy);
        setSize({ width: newW, height: newH });
      }
    };
    const onUp = () => {
      dragStateRef.current.active = false;
      resizeStateRef.current.active = false;
    };
    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', onUp);
    return () => {
      window.removeEventListener('mousemove', onMove);
      window.removeEventListener('mouseup', onUp);
    };
  }, []);

  // -------- Section helpers --------
  const toggleSection = (id: SectionId) => {
    setOpenSections((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };
  const setSectionError = (id: SectionId, msg: string | null) => {
    setSectionErrors((p) => ({ ...p, [id]: msg }));
  };
  const setSectionIsSaving = (id: SectionId, v: boolean) => {
    setSectionSaving((p) => ({ ...p, [id]: v }));
  };

  // -------- Save handlers (per-section) --------
  const buildUpdatePayload = useCallback(() => {
    return {
      name: name.trim(),
      description: description.trim(),
      tags,
      triggers,
      instructions,
      examples: examples || null,
      'allowed-tools': allowedTools,  // kebab for spec compliance
    };
  }, [name, description, tags, triggers, instructions, examples, allowedTools]);

  const handleSaveSection = async (id: SectionId) => {
    setSectionError(id, null);
    setSectionIsSaving(id, true);
    try {
      if (!existingSkill) {
        // For new skills, POST once with everything
        if (!name.trim() || !description.trim() || !instructions.trim()) {
          setSectionError(id, t('skill_builder_error_required'));
          setSectionIsSaving(id, false);
          return;
        }
        const result = await apiClient.post('/api/skills', {
          name: name.trim(),
          description: description.trim(),
          tags,
          triggers,
          instructions,
          examples: examples || null,
          allowed_tools: allowedTools,
        });
        if (onSave) onSave(result.data);
        onClose();
      } else {
        const result = await apiClient.put(
          `/api/skills/${encodeURIComponent(existingSkill.skill_id)}`,
          buildUpdatePayload()
        );
        if (onSave) onSave(result.data);
        setSectionError(id, t('skill_builder_saved'));
        setTimeout(() => setSectionError(id, null), 1800);
      }
    } catch (e: any) {
      setSectionError(id, e.response?.data?.detail || e.message || t('skill_builder_error_save'));
    } finally {
      setSectionIsSaving(id, false);
    }
  };

  // -------- Tag / Trigger / Tool handlers --------
  const addTag = () => {
    const t = newTag.trim();
    if (t && !tags.includes(t)) {
      setTags([...tags, t]);
      setNewTag('');
    }
  };
  const removeTag = (tag: string) => setTags(tags.filter((x) => x !== tag));

  const addTrigger = () => {
    const tr = newTrigger.trim();
    if (tr && !triggers.includes(tr)) {
      setTriggers([...triggers, tr]);
      setNewTrigger('');
    }
  };
  const removeTrigger = (tr: string) => setTriggers(triggers.filter((x) => x !== tr));

  const addTool = () => {
    const tl = newTool.trim();
    if (tl && !allowedTools.includes(tl)) {
      setAllowedTools([...allowedTools, tl]);
      setNewTool('');
    }
  };
  const removeTool = (tl: string) => setAllowedTools(allowedTools.filter((x) => x !== tl));

  const resetAll = () => {
    if (!existingSkill) {
      setName(''); setDescription(''); setTags(['custom']); setTriggers([]);
      setInstructions(''); setExamples(''); setAllowedTools([]);
    } else {
      setName(existingSkill.name);
      setDescription(existingSkill.description);
      setTags(existingSkill.tags);
      setTriggers(existingSkill.triggers);
      setInstructions(existingSkill.instructions);
      setExamples(existingSkill.examples || '');
      setAllowedTools(Array.isArray(existingSkill.allowed_tools) ? existingSkill.allowed_tools : []);
    }
  };

  // ===================================================================================
  // Section renderers
  // ===================================================================================

  const renderIdentity = () => (
    <div className="space-y-4 pt-3">
      <Field label="Skill ID (immutable)">
        <input
          type="text"
          value={existingSkill?.skill_id || '(will be generated from name)'}
          disabled
          className="w-full px-3 py-2 bg-gray-100 dark:bg-gray-800 border border-gray-200 rounded-lg text-sm font-mono text-gray-500 cursor-not-allowed"
        />
      </Field>
      <Field label="Name" required>
        <input
          type="text"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="e.g. web-search"
          className="w-full px-3 py-2 bg-white dark:bg-background-dark border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent"
        />
      </Field>
      <Field label="Version">
        <input
          type="text"
          value={existingSkill?.version || ''}
          disabled
          placeholder="1.0.0"
          className="w-full px-3 py-2 bg-gray-100 dark:bg-gray-800 border border-gray-200 rounded-lg text-sm font-mono text-gray-500 cursor-not-allowed"
        />
        <p className="text-[10px] text-gray-500 mt-1">Version is managed by the skill lifecycle (publish/bump).</p>
      </Field>
    </div>
  );

  const renderDiscovery = () => (
    <div className="space-y-4 pt-3">
      <Field
        label="Description (router-matching)"
        hint="This is what the agent uses to decide if your skill applies. Describe WHAT it does and WHEN to use it."
      >
        <div className="flex items-center justify-between mb-1">
          <span className="text-[10px] text-gray-500">Per Agent Skills spec: ≤ 1024 chars</span>
          <span
            className="text-[10px] font-mono"
            style={{
              color: description.length > 1024 ? '#ef4444'
                : description.length > 900 ? '#D97757' : '#5C5A55',
            }}
          >
            {description.length} / 1024
          </span>
        </div>
        <textarea
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          placeholder="e.g. Search the web for current information. Use when user asks about recent events..."
          rows={3}
          maxLength={1100}
          className="w-full px-3 py-2 bg-white dark:bg-background-dark border border-gray-200 rounded-lg text-sm resize-none focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent"
          style={{ borderColor: description.length > 1024 ? '#ef4444' : undefined }}
        />
      </Field>

      <Field label="Tags" hint="Categorize for filtering and search.">
        <div className="flex flex-wrap gap-1.5 mb-2">
          {tags.map((tag) => (
            <span key={tag} className="inline-flex items-center gap-1 text-xs px-2 py-1 rounded-md"
              style={{ backgroundColor: 'rgba(217,119,87,0.12)', color: '#A85A2E', border: '1px solid #D97757' }}>
              <Hash size={10} />{tag}
              <button onClick={() => removeTag(tag)} className="ml-1 hover:text-red-500"><X size={10} /></button>
            </span>
          ))}
        </div>
        <div className="flex gap-2">
          <input
            type="text"
            value={newTag}
            onChange={(e) => setNewTag(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && (e.preventDefault(), addTag())}
            placeholder="add tag…"
            className="flex-1 px-3 py-2 bg-white dark:bg-background-dark border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-primary"
          />
          <button onClick={addTag} className="px-3 py-2 rounded-lg text-sm font-medium bg-gray-100 hover:bg-gray-200 dark:bg-gray-800 dark:hover:bg-gray-700">
            <Plus size={14} />
          </button>
        </div>
      </Field>

      <Field label="Triggers" hint="Phrases that indicate this skill should be activated.">
        <div className="space-y-1.5 mb-2">
          {triggers.map((tr) => (
            <div key={tr} className="flex items-center gap-2 text-xs px-2.5 py-1.5 rounded-md"
              style={{ backgroundColor: '#FAF9F5', color: '#1F1E1B', border: '1px solid #E8E4DA' }}>
              <Zap size={11} style={{ color: '#D97757' }} />
              <span className="flex-1 font-mono">{tr}</span>
              <button onClick={() => removeTrigger(tr)} className="hover:text-red-500"><X size={12} /></button>
            </div>
          ))}
        </div>
        <div className="flex gap-2">
          <input
            type="text"
            value={newTrigger}
            onChange={(e) => setNewTrigger(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && (e.preventDefault(), addTrigger())}
            placeholder='e.g. "when user asks to summarize text"'
            className="flex-1 px-3 py-2 bg-white dark:bg-background-dark border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-primary"
          />
          <button onClick={addTrigger} className="px-3 py-2 rounded-lg text-sm font-medium bg-gray-100 hover:bg-gray-200 dark:bg-gray-800 dark:hover:bg-gray-700">
            <Plus size={14} />
          </button>
        </div>
      </Field>
    </div>
  );

  const renderConfiguration = () => (
    <div className="space-y-4 pt-3">
      <Field
        label="Allowed Tools"
        hint="Pre-approve these LLM tools for this skill (per Agent Skills spec field `allowed-tools`)."
      >
        <div className="flex flex-wrap gap-1.5 mb-2">
          {allowedTools.length === 0 && (
            <span className="text-xs text-gray-400 italic">No tools restricted — agent uses main agent's tools</span>
          )}
          {allowedTools.map((tl) => (
            <span key={tl} className="inline-flex items-center gap-1 text-xs px-2 py-1 rounded-md font-mono"
              style={{ backgroundColor: '#F5E6DC', color: '#A85A2E', border: '1px solid #D97757' }}>
              <FileCode size={10} />{tl}
              <button onClick={() => removeTool(tl)} className="ml-1 hover:text-red-500"><X size={10} /></button>
            </span>
          ))}
        </div>
        <div className="flex gap-2">
          <input
            type="text"
            value={newTool}
            onChange={(e) => setNewTool(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && (e.preventDefault(), addTool())}
            placeholder="e.g. web_search, filesystem, shell, python"
            className="flex-1 px-3 py-2 bg-white dark:bg-background-dark border border-gray-200 rounded-lg text-sm font-mono focus:outline-none focus:ring-2 focus:ring-primary"
          />
          <button onClick={addTool} className="px-3 py-2 rounded-lg text-sm font-medium bg-gray-100 hover:bg-gray-200 dark:bg-gray-800 dark:hover:bg-gray-700">
            <Plus size={14} />
          </button>
        </div>
        <p className="text-[10px] text-gray-500 mt-2">
          💡 Reference tools by name in the Instructions body — agent will call them via the main agent's tool registry.
        </p>
      </Field>
    </div>
  );

  const renderBody = () => (
    <div className="space-y-2 pt-3">
      <div className="flex items-center justify-between">
        <div>
          <label className="text-xs font-medium text-gray-700 uppercase flex items-center gap-1">
            <BookOpen size={12} /> Instructions (SKILL.md body)
          </label>
          <p className="text-[10px] text-gray-500 mt-0.5">Markdown. Loaded when skill activates (progressive disclosure).</p>
        </div>
        <span className="text-[10px] font-mono text-gray-500">
          {instructions.length} chars · ~{Math.ceil(instructions.split(/\s+/).filter(Boolean).length)} words
        </span>
      </div>
      <textarea
        value={instructions}
        onChange={(e) => setInstructions(e.target.value)}
        placeholder={`# My Skill\n\n## Overview\n\n...\n\n## Instructions\n\n### Step 1: ...\n`}
        rows={16}
        className="w-full px-3 py-2 bg-white dark:bg-background-dark border border-gray-200 rounded-lg text-sm font-mono resize-none focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent"
        style={{ minHeight: 320 }}
      />
    </div>
  );

  const renderExamples = () => (
    <div className="space-y-2 pt-3">
      <div className="flex items-center justify-between">
        <label className="text-xs font-medium text-gray-700 uppercase flex items-center gap-1">
          <FileText size={12} /> Examples (optional)
        </label>
        <span className="text-[10px] font-mono text-gray-500">{examples.length} chars</span>
      </div>
      <p className="text-[10px] text-gray-500">Markdown examples showing input/output of this skill.</p>
      <textarea
        value={examples}
        onChange={(e) => setExamples(e.target.value)}
        placeholder={`User: What's the latest news about Apple?\nAsst: [calls web_search('latest Apple news'), returns top 3 with citations]\n`}
        rows={6}
        className="w-full px-3 py-2 bg-white dark:bg-background-dark border border-gray-200 rounded-lg text-sm font-mono resize-none focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent"
      />
    </div>
  );

  const renderFiles = () => (
    <div className="space-y-3 pt-3">
      <p className="text-[11px] text-gray-500">
        Files in this skill's directory (read-only — use filesystem to add/edit scripts/, references/, assets/):
      </p>
      {existingSkill?.source_path ? (
        <div className="rounded-lg border border-gray-200 bg-gray-50 p-3 font-mono text-xs">
          <div className="flex items-center gap-1.5 text-gray-700 mb-2">
            <FolderOpen size={12} />
            <span>{existingSkill.source_path}</span>
          </div>
          <div className="pl-4 space-y-1 text-gray-600">
            <div className="flex items-center gap-1.5"><FileText size={11} /> SKILL.md <span className="text-gray-400">(required)</span></div>
            <div className="flex items-center gap-1.5 opacity-60"><FolderOpen size={11} /> scripts/ <span className="text-gray-400">(optional — executable code)</span></div>
            <div className="flex items-center gap-1.5 opacity-60"><FolderOpen size={11} /> references/ <span className="text-gray-400">(optional — extra docs)</span></div>
            <div className="flex items-center gap-1.5 opacity-60"><FolderOpen size={11} /> assets/ <span className="text-gray-400">(optional — templates)</span></div>
          </div>
          <p className="text-[10px] text-gray-400 mt-3">
            💡 Future: upload/manage scripts and references through this UI.
          </p>
        </div>
      ) : (
        <div className="rounded-lg border border-dashed border-gray-300 p-4 text-center text-xs text-gray-500">
          No source path (skill created in DB only).
        </div>
      )}
    </div>
  );

  const sections: Array<{ id: SectionId; icon: string; title: string; subtitle: string; render: () => ReactNode }> = [
    { id: 'identity',      icon: '📇', title: 'Identity',       subtitle: 'Name, version, immutable id',          render: renderIdentity },
    { id: 'discovery',     icon: '📝', title: 'Discovery',      subtitle: 'Description, tags, triggers (routing)', render: renderDiscovery },
    { id: 'configuration', icon: '⚙️', title: 'Configuration',  subtitle: 'Allowed tools',                        render: renderConfiguration },
    { id: 'body',          icon: '📜', title: 'Body (SKILL.md)',subtitle: 'Instructions loaded on activation',    render: renderBody },
    { id: 'examples',      icon: '📚', title: 'Examples',       subtitle: 'Optional USER/ASST dialogs',           render: renderExamples },
    { id: 'files',         icon: '🗂️', title: 'Files',          subtitle: 'scripts/ · references/ · assets/',     render: renderFiles },
  ];

  return (
    <div
      className="fixed inset-0 bg-black/50 flex items-center justify-center z-50"
      onClick={onClose}
    >
      {/* Modal container — draggable + resizable */}
      <div
        ref={containerRef}
        className="bg-gray-50 dark:bg-background-dark border border-gray-200 dark:border-border-dark rounded-xl shadow-2xl flex flex-col overflow-hidden"
        style={{
          width: size.width,
          height: size.height,
          transform: `translate(${position.x}px, ${position.y}px)`,
          maxWidth: '95vw',
          maxHeight: '95vh',
        }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* === Header (draggable) === */}
        <div
          className="border-b p-5 flex-shrink-0 cursor-move select-none"
          style={{
            backgroundColor: 'var(--color-primary)',
            borderBottomColor: 'var(--color-border-dark)',
          }}
          onMouseDown={handleDragMouseDown}
        >
          <div className="flex items-start justify-between gap-4">
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2 mb-1">
                <GripHorizontal size={14} className="text-white/70" />
                <h2 className="text-xl font-semibold text-white truncate" style={{ textShadow: '0 1px 2px rgba(0,0,0,0.25)' }}>
                  {isEditing ? `Edit: ${existingSkill!.name}` : 'New Skill'}
                </h2>
              </div>
              <p className="text-xs text-white/90" style={{ textShadow: '0 1px 2px rgba(0,0,0,0.15)' }}>
                {existingSkill?.source_path || 'Drag header to move · Resize from bottom-right corner'}
              </p>
            </div>
            <div className="flex items-center gap-2">
              <button
                onClick={resetAll}
                className="flex items-center gap-1 px-3 py-1.5 text-xs font-medium text-white/95 hover:text-white bg-white/15 hover:bg-white/25 rounded-lg"
                title="Reset to original values"
              >
                <RotateCcw size={12} /> Reset
              </button>
              <button
                onClick={onClose}
                className="p-2 text-white/90 hover:text-white hover:bg-white/15 rounded-lg"
                title="Close"
              >
                <X size={18} />
              </button>
            </div>
          </div>
        </div>

        {/* === Body (scrollable, sections) === */}
        <div className="flex-1 overflow-y-auto">
          <div className="px-6 py-5 space-y-3">
            {sections.map((sec) => {
              const open = openSections.has(sec.id);
              const error = sectionErrors[sec.id];
              const saving = sectionSaving[sec.id];
              return (
                <div key={sec.id} className="rounded-xl border border-gray-200 dark:border-border-dark overflow-hidden bg-white dark:bg-panel-dark">
                  {/* Section header */}
                  <div className="flex items-center justify-between gap-2 px-4 py-2.5" style={{ backgroundColor: '#FAF9F5', borderBottom: open ? '1px solid #E8E4DA' : 'none' }}>
                    <button
                      onClick={() => toggleSection(sec.id)}
                      className="flex items-center gap-2 flex-1 text-left"
                    >
                      {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                      <span className="text-base">{sec.icon}</span>
                      <div>
                        <div className="text-sm font-semibold" style={{ color: '#1F1E1B' }}>{sec.title}</div>
                        <div className="text-[10px] text-gray-500">{sec.subtitle}</div>
                      </div>
                    </button>
                    <div className="flex items-center gap-2">
                      {error && (
                        <span className="text-[10px] font-mono" style={{ color: error === '✓ Saved' ? '#10b981' : '#ef4444' }}>
                          {error === '✓ Saved' ? '✓ Saved' : error.length > 50 ? error.slice(0, 50) + '…' : error}
                        </span>
                      )}
                      {isEditing && sec.id !== 'files' && (
                        <button
                          onClick={() => handleSaveSection(sec.id)}
                          disabled={saving}
                          className="flex items-center gap-1 px-3 py-1 text-xs font-medium text-white rounded-lg disabled:opacity-50"
                          style={{ backgroundColor: 'var(--color-primary)' }}
                          title={`Save changes to ${sec.title}`}
                        >
                          <Save size={11} />
                          {saving ? 'Saving…' : 'Save'}
                        </button>
                      )}
                      {!isEditing && sec.id === 'body' && (
                        <button
                          onClick={() => handleSaveSection(sec.id)}
                          disabled={saving}
                          className="flex items-center gap-1 px-3 py-1 text-xs font-medium text-white rounded-lg disabled:opacity-50"
                          style={{ backgroundColor: 'var(--color-primary)' }}
                          title="Create this skill"
                        >
                          <Check size={11} />
                          {saving ? 'Creating…' : 'Create skill'}
                        </button>
                      )}
                    </div>
                  </div>
                  {/* Section body */}
                  {open && <div className="px-4 pb-4">{sec.render()}</div>}
                </div>
              );
            })}
          </div>
        </div>

        {/* === Footer === */}
        <div className="flex items-center justify-between gap-3 px-5 py-3 border-t bg-white dark:bg-panel-dark flex-shrink-0" style={{ borderColor: '#E8E4DA' }}>
          <div className="text-[10px] text-gray-500 flex items-center gap-2">
            <Maximize2 size={11} />
            {size.width} × {size.height}
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={onClose}
              className="px-4 py-2 rounded-lg text-sm font-medium bg-gray-100 dark:bg-gray-800 text-gray-700 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-700 transition-colors"
            >
              Close
            </button>
            {!isEditing && (
              <button
                onClick={() => handleSaveSection('body')}
                disabled={sectionSaving.body}
                className="px-4 py-2 rounded-lg text-sm font-medium text-white flex items-center gap-2 disabled:opacity-50"
                style={{ backgroundColor: 'var(--color-primary)' }}
              >
                <Save size={14} />
                {sectionSaving.body ? 'Creating…' : 'Create skill'}
              </button>
            )}
          </div>
        </div>

        {/* === Resize handle (bottom-right) === */}
        <div
          onMouseDown={handleResizeMouseDown}
          className="absolute bottom-0 right-0 w-5 h-5 cursor-se-resize"
          style={{
            background: 'linear-gradient(135deg, transparent 50%, var(--color-primary) 50%)',
            borderBottomRightRadius: 12,
          }}
          title="Drag to resize"
        />
      </div>
    </div>
  );
};

// Helper component
const Field = ({ label, hint, required, children }: { label: string; hint?: string; required?: boolean; children: React.ReactNode }) => (
  <div>
    <label className="block text-xs font-medium text-gray-700 mb-1 uppercase">
      {label} {required && <span style={{ color: '#D97757' }}>*</span>}
    </label>
    {hint && <p className="text-[10px] text-gray-500 mb-1.5">{hint}</p>}
    {children}
  </div>
);

export default SkillBuilderModal;