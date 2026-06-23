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
import { useAvailableTools } from '@/hooks/useAvailableTools';

interface SkillBuilderModalProps {
  onClose: () => void;
  onSave?: (skill: any) => void;
  initialTab?: 'form' | 'markdown' | 'test';  // which tab to show on open (default: form)
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

type SectionId = 'identity' | 'discovery' | 'triggers' | 'configuration' | 'body' | 'examples' | 'files';

// ============================================================
// SKILL.md (markdown) ↔ Form state conversion helpers
// The markdown is the source of truth (matches Agent Skills spec).
// YAML frontmatter is parsed and re-generated; the body is plain markdown.
// ============================================================

interface ParsedSkill {
  name: string;
  description: string;
  tags: string[];
  triggers: string[];
  allowed_tools: string[];
  instructions: string;
  examples: string;
}

/**
 * Build a YAML list value. Flow style for short lists:
 *   tags: [web, research]
 * Block style if any item contains a comma or is multi-line.
 */
function yamlList(items: string[]): string {
  if (!items || items.length === 0) return '[]';
  const simple = items.every((s) => s && !s.includes(',') && !s.includes('\n') && !s.startsWith('['));
  if (simple && items.length <= 5) {
    return `[${items.join(', ')}]`;
  }
  return items.map((i) => `  - ${i.replace(/\n/g, ' ')}`).join('\n');
}

/**
 * Serialize a multi-line string as YAML scalar.
 * Uses block scalar (|) so markdown formatting (lists, headings) is preserved.
 */
function yamlMultiline(value: string): string {
  if (!value) return '""';
  // If the string contains newlines, use block scalar style
  if (value.includes('\n')) {
    // Indent each line by 2 spaces
    const lines = value.split('\n');
    return '|\n' + lines.map((l) => '  ' + l).join('\n');
  }
  // Otherwise use double-quoted scalar
  return JSON.stringify(value);
}

/**
 * Build a full SKILL.md text from structured form state.
 */
function buildSkillMarkdown(state: {
  name: string;
  description: string;
  tags: string[];
  triggers: string[];
  allowed_tools: string[];
  instructions: string;
  examples: string;
}): string {
  const frontmatter = [
    '---',
    `name: ${state.name || 'untitled'}`,
    `description: ${yamlMultiline(state.description || '')}`,
    `tags: ${yamlList(state.tags || [])}`,
    `triggers:`,
    ...(state.triggers || []).map((t) => `  - ${t}`),
    `allowed-tools: ${yamlList(state.allowed_tools || [])}`,
    '---',
  ].join('\n');

  // Body — just the instructions (per Agent Skills spec, body is the SKILL.md content after frontmatter)
  let body = state.instructions || '';
  if (state.examples && state.examples.trim()) {
    body += '\n\n## Examples\n\n' + state.examples;
  }
  if (!body) body = '# Instructions\n\n(Write the skill instructions here)\n';
  return frontmatter + '\n\n' + body + '\n';
}

/**
 * Parse a SKILL.md text into structured form state.
 * Returns null if the text doesn't start with a YAML frontmatter block.
 */
function parseSkillMarkdown(text: string): ParsedSkill | null {
  const trimmed = text.trim();
  // Frontmatter must start with --- on its own line and end with ---
  const m = trimmed.match(/^---\s*\n([\s\S]*?)\n---\s*\n?([\s\S]*)$/);
  if (!m) return null;

  const yaml = m[1];
  const body = m[2] || '';

  // Parse YAML — simple line-based parser good enough for our schema:
  //   key: value
  //   key: [a, b, c]
  //   key:
  //     - item
  const result: ParsedSkill = {
    name: '',
    description: '',
    tags: [],
    triggers: [],
    allowed_tools: [],
    instructions: body,
    examples: '',
  };

  // Split body out of "## Examples" section if present
  const examplesMatch = body.match(/\n## Examples\s*\n([\s\S]*?)$/);
  if (examplesMatch) {
    result.instructions = body.slice(0, examplesMatch.index).trim();
    result.examples = examplesMatch[1].trim();
  }

  const lines = yaml.split('\n');
  let currentKey: string | null = null;
  let blockList: string[] = [];
  let blockScalarValue = '';
  let blockScalarActive = false;
  let blockScalarIndent = 0;

  function commitList() {
    if (currentKey === 'tags') result.tags = blockList.slice();
    else if (currentKey === 'triggers') result.triggers = blockList.slice();
    else if (currentKey === 'allowed-tools') result.allowed_tools = blockList.slice();
    blockList = [];
    currentKey = null;
  }

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    // Continuation of block scalar (|)
    if (blockScalarActive) {
      // Empty line in block scalar: include as literal newline
      if (line.trim() === '') {
        blockScalarValue += '\n';
        continue;
      }
      // Check indentation — must be at least blockScalarIndent
      const leading = line.match(/^(\s*)/)?.[1].length ?? 0;
      if (leading >= blockScalarIndent) {
        const content = line.slice(blockScalarIndent);
        blockScalarValue += (blockScalarValue ? '\n' : '') + content;
        continue;
      } else {
        // End of block scalar
        if (currentKey === 'description') result.description = blockScalarValue.trimEnd();
        blockScalarActive = false;
      }
    }

    // Match "key: value" or "key:" (start of list / block scalar)
    const kvMatch = line.match(/^([a-zA-Z][\w-]*)\s*:\s*(.*)$/);
    if (kvMatch) {
      // Flush any pending list
      if (currentKey && !blockScalarActive) commitList();

      const key = kvMatch[1];
      const value = kvMatch[2];

      if (value === '' || value === undefined) {
        // Could be start of list or block scalar — peek next non-empty line
        let nextIdx = i + 1;
        while (nextIdx < lines.length && lines[nextIdx].trim() === '') nextIdx++;
        const nextLine = lines[nextIdx] || '';
        if (nextLine.match(/^\s+- /)) {
          currentKey = key;
        } else if (nextLine.match(/^\s+\S/) && key === 'description') {
          // Start of block scalar
          blockScalarActive = true;
          blockScalarIndent = nextLine.match(/^(\s*)/)?.[1].length ?? 2;
          currentKey = key;
          blockScalarValue = '';
        } else {
          // Empty value
          if (key === 'name') result.name = '';
          currentKey = null;
        }
      } else if (value === '|' || value.startsWith('|')) {
        // Block scalar
        blockScalarActive = true;
        blockScalarIndent = 2;
        currentKey = key;
        blockScalarValue = '';
      } else if (value.startsWith('[') && value.endsWith(']')) {
        // Inline list
        const items = value
          .slice(1, -1)
          .split(',')
          .map((s) => s.trim().replace(/^["']|["']$/g, ''))
          .filter(Boolean);
        if (key === 'tags') result.tags = items;
        else if (key === 'triggers') result.triggers = items;
        else if (key === 'allowed-tools') result.allowed_tools = items;
        currentKey = null;
      } else {
        // Plain scalar
        const unquoted = value.replace(/^["']|["']$/g, '');
        if (key === 'name') result.name = unquoted;
        else if (key === 'description') result.description = unquoted;
        currentKey = null;
      }
    } else {
      // Continuation of list: "  - item"
      const listItemMatch = line.match(/^\s+-\s+(.*)$/);
      if (listItemMatch && currentKey) {
        const item = listItemMatch[1].replace(/^["']|["']$/g, '');
        blockList.push(item);
      }
    }
  }

  // Flush
  if (blockScalarActive && currentKey === 'description') {
    result.description = blockScalarValue.trimEnd();
  } else if (currentKey) {
    commitList();
  }

  return result;
}

const SkillBuilderModal = ({ onClose, onSave, existingSkill, initialTab = 'form' }: SkillBuilderModalProps) => {
  const { t } = useTranslation('chat');
  // After a new skill is created, store it here so the modal can switch to
  // edit-mode (PUT instead of POST) without closing. This makes iterative
  // editing easy: create → keep tweaking → close when done.
  const [createdSkill, setCreatedSkill] = useState<typeof existingSkill | null>(null);
  const effectiveExistingSkill = existingSkill ?? createdSkill ?? undefined;
  const isEditing = !!effectiveExistingSkill;

  // -------- View mode (form / markdown / test) --------
  // form     — default structured sections editor
  // markdown — full SKILL.md as one text document, with bi-directional sync
  // test     — test trigger matching against sample user input
  type ViewMode = 'form' | 'markdown' | 'test';
  const [viewMode, setViewMode] = useState<ViewMode>(initialTab);
  const [skillMarkdown, setSkillMarkdown] = useState<string>('');  // for markdown view
  const [testInput, setTestInput] = useState<string>('');            // for test triggers view
  const [testResults, setTestResults] = useState<Array<{
    skill_id?: string;
    name?: string;
    skill?: { name?: string; skill_id?: string };
    score: number;
    matched_trigger?: string;
    match_reason?: string;
}> | null>(null);
  const [testSkillPool, setTestSkillPool] = useState<Set<string> | null>(null);  // null = all
  const [showTestPoolEditor, setShowTestPoolEditor] = useState(false);
  const [allSkills, setAllSkills] = useState<Array<{skill_id: string; name: string; source_type: string}>>([]);
  const [testRunning, setTestRunning] = useState(false);
  const [markdownSync, setMarkdownSync] = useState<'idle' | 'parsing' | 'ok' | 'error'>('idle');

  // Load all skills for the Test Triggers skill-pool selector
  useEffect(() => {
    (async () => {
      try {
        const resp = await apiClient.get('/api/skills');
        const skills = (resp.data || []).map((s: any) => ({
          skill_id: s.skill_id,
          name: s.name,
          source_type: s.source_type,
        }));
        setAllSkills(skills);
      } catch (e) {
        // non-fatal
      }
    })();
  }, []);

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

  // Tool Pool selector state (reuses Skill Pool pattern from Test Triggers tab)
  const { tools: registryTools, isLoading: toolsLoading } = useAvailableTools();
  const [showToolPoolEditor, setShowToolPoolEditor] = useState(false);

  // Common skill-related tools that aren't in /api/tools/registry (e.g., 'execute', 'filesystem')
  const SKILL_NATIVE_TOOLS = [
    { id: 'execute',       name: 'Execute',       description: 'Run a skill script in the sandbox (e.g., data_analysis.py)', category: 'skill' },
    { id: 'filesystem',    name: 'Filesystem',    description: 'Read/write files in the agent sandbox',                       category: 'skill' },
    { id: 'shell',         name: 'Shell',         description: 'Run shell commands (with safety sandbox)',                    category: 'skill' },
    { id: 'read_file',     name: 'Read File',     description: 'Read a single file from the agent filesystem',                category: 'filesystem' },
    { id: 'write_file',    name: 'Write File',    description: 'Write or create a file in the agent filesystem',              category: 'filesystem' },
    { id: 'edit_file',     name: 'Edit File',     description: 'Apply edits to an existing file',                             category: 'filesystem' },
  ];
  // Full list: registry tools + skill-native tools (deduped by id)
  const TOOL_POOL = [
    ...SKILL_NATIVE_TOOLS,
    ...registryTools.filter(rt => !SKILL_NATIVE_TOOLS.some(snt => snt.id === rt.id)),
  ];
  const toggleToolFromPool = (toolId: string) => {
    if (allowedTools.includes(toolId)) {
      setAllowedTools(allowedTools.filter((x: string) => x !== toolId));
    } else {
      setAllowedTools([...allowedTools, toolId]);
    }
  };

  // -------- Section UI state --------
// New skills: open Identity + Discovery + Triggers + Body so user sees required fields
// Edit skills: open Discovery + Triggers + Body
  const [openSections, setOpenSections] = useState<Set<SectionId>>(
    new Set<SectionId>(
      existingSkill
        ? ['discovery', 'triggers', 'body']
        : ['identity', 'discovery', 'triggers', 'body']
    )
  );
  const [sectionErrors, setSectionErrors] = useState<Record<SectionId, string | null>>({
    identity: null, discovery: null, triggers: null, configuration: null, body: null, examples: null, files: null,
  });
  const [sectionSaving, setSectionSaving] = useState<Record<SectionId, boolean>>({
    identity: false, discovery: false, triggers: false, configuration: false, body: false, examples: false, files: false,
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
      if (!effectiveExistingSkill) {
        // For new skills, POST once with everything
        const missing: string[] = [];
        if (!name.trim()) missing.push('name');
        if (!description.trim()) missing.push('description');
        if (!instructions.trim()) missing.push('instructions');
        if (missing.length > 0) {
          // Open the section(s) that contain the missing fields, so user sees them
          setOpenSections((prev) => {
            const next = new Set(prev);
            if (missing.includes('name')) next.add('identity');
            if (missing.includes('description')) next.add('discovery');
            if (missing.includes('instructions')) next.add('body');
            return next;
          });
          setSectionError(
            id,
            `Missing required field(s): ${missing.join(', ')}. Please fill them and try again.`
          );
          setSectionIsSaving(id, false);
          // Also scroll to top of modal so the user sees the error
          const body = document.querySelector('[data-skill-modal-body]');
          if (body) body.scrollTop = 0;
          return;
        }
        const result = await apiClient.post('/api/skills', {
          name: name.trim(),
          description: description.trim(),
          tags,
          triggers,
          instructions,
          examples: examples || null,
          'allowed-tools': allowedTools,  // kebab-case per Agent Skills spec
        });
        // Switch to edit mode — keep modal open so user can keep tweaking.
        // Store the created skill locally so subsequent saves use PUT.
        const newSkill = {
          skill_id: result.data.skill_id,
          name: result.data.name,
          description: result.data.description,
          tags: result.data.tags,
          triggers: result.data.triggers,
          instructions: result.data.instructions,
          examples: result.data.examples,
          version: result.data.version,
          allowed_tools: result.data['allowed-tools'] ?? result.data.allowed_tools,
          source_path: result.data.source_path,
          source_type: result.data.source_type,
        };
        setCreatedSkill(newSkill);
        if (onSave) onSave(result.data);  // parent refreshes skill list
        setSectionError(id, `✓ Created — now in edit mode. Keep tweaking or close when done.`);
        setTimeout(() => setSectionError(id, null), 3000);
        // Collapse default-open sections — user has filled required fields
        setOpenSections(new Set<SectionId>(['discovery', 'triggers', 'body']));
      } else {
        const payload = buildUpdatePayload();
        // DEBUG: log so user can verify what's being sent
        // eslint-disable-next-line no-console
        console.log(`[SkillBuilderModal] PUT ${effectiveExistingSkill.skill_id}:`, payload);
        const result = await apiClient.put(
          `/api/skills/${encodeURIComponent(effectiveExistingSkill.skill_id)}`,
          payload
        );
        // eslint-disable-next-line no-console
        console.log(`[SkillBuilderModal] PUT response:`, result.data);
        if (onSave) onSave(result.data);
        setSectionError(id, `✓ Saved ${id} section (${payload.triggers?.length || 0} triggers, ${payload.tags?.length || 0} tags)`);
        setTimeout(() => setSectionError(id, null), 3000);
      }
    } catch (e: any) {
      const msg = e.response?.data?.detail || e.message || 'Failed to save skill';
      setSectionError(id, msg);
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

  const addTrigger = (overrideValue?: string) => {
    // Use overrideValue if provided (avoids stale closure on Enter keypress);
    // otherwise read from the newTrigger state.
    const raw = overrideValue !== undefined ? overrideValue : newTrigger;
    // DEBUG: trace so user can verify what addTrigger is seeing
    // eslint-disable-next-line no-console
    console.log(`[SkillBuilderModal] addTrigger called with ${raw.split('\n').length} line(s):`, raw);
    const lines = raw
      .split('\n')
      .map((s) => s.trim())
      .filter(Boolean);
    if (lines.length === 0) return;
    setTriggers((prev) => {
      const next = [...prev];
      for (const ln of lines) {
        if (!next.includes(ln)) next.push(ln);
      }
      // eslint-disable-next-line no-console
      console.log(`[SkillBuilderModal] triggers now: ${next.length} items`);
      return next;
    });
    setNewTrigger('');
  }
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
    if (!effectiveExistingSkill) {
      setName(''); setDescription(''); setTags(['custom']); setTriggers([]);
      setInstructions(''); setExamples(''); setAllowedTools([]);
    } else {
      setName(effectiveExistingSkill.name);
      setDescription(effectiveExistingSkill.description);
      setTags(effectiveExistingSkill.tags);
      setTriggers(effectiveExistingSkill.triggers);
      setInstructions(effectiveExistingSkill.instructions);
      setExamples(effectiveExistingSkill.examples || '');
      setAllowedTools(Array.isArray(effectiveExistingSkill.allowed_tools) ? effectiveExistingSkill.allowed_tools : []);
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
          className="w-full px-3 py-2 bg-white dark:bg-background-dark border border-gray-200 rounded-lg text-sm text-gray-900 dark:text-white placeholder:text-gray-400 focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent"
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
          placeholder={`e.g. Search the web for current information and synthesize answers.

Use when the user asks:
- About recent events or current news
- For external facts not in your training data
- To look up information on a specific topic`}
          rows={6}
          maxLength={1100}
          className="w-full px-3 py-2 bg-white dark:bg-background-dark border border-gray-200 rounded-lg text-sm text-gray-900 dark:text-white placeholder:text-gray-400 focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent"
          style={{
            borderColor: description.length > 1024 ? '#ef4444' : undefined,
            minHeight: 130,
          }}
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
            className="flex-1 px-3 py-2 bg-white dark:bg-background-dark border border-gray-200 rounded-lg text-sm text-gray-900 dark:text-white placeholder:text-gray-400 focus:outline-none focus:ring-2 focus:ring-primary"
          />
          <button onClick={addTag} className="px-3 py-2 rounded-lg text-sm font-medium bg-gray-100 hover:bg-gray-200 dark:bg-gray-800 dark:hover:bg-gray-700">
            <Plus size={14} />
          </button>
        </div>
      </Field>
    </div>
  );

  const renderTriggers = () => (
    <div className="space-y-3 pt-3">
      {/* Existing triggers as chips */}
      <div className="space-y-1.5">
        {triggers.length === 0 ? (
          <div className="text-[11px] text-gray-400 italic px-2.5 py-2 border border-dashed border-gray-300 rounded-md text-center">
            No triggers yet — paste a list or type one and press Enter
          </div>
        ) : (
          <>
            <div className="text-[10px] text-gray-500 mb-1">
              {triggers.length} trigger{triggers.length === 1 ? '' : 's'} added:
            </div>
            {triggers.map((tr) => (
              <div key={tr} className="flex items-center gap-2 text-xs px-2.5 py-1.5 rounded-md"
                style={{ backgroundColor: '#FAF9F5', color: '#1F1E1B', border: '1px solid #E8E4DA' }}>
                <Zap size={11} style={{ color: '#D97757' }} />
                <span className="flex-1 font-mono">{tr}</span>
                <button onClick={() => removeTrigger(tr)} className="hover:text-red-500" title="Remove this trigger">
                  <X size={12} />
                </button>
              </div>
            ))}
          </>
        )}
      </div>
      {/* Input area — simple, reliable */}
      <div>
        <label className="text-[10px] text-gray-500 mb-1 block font-medium">
          Type or paste your triggers (one per line) — Enter or click Add to commit
        </label>
        <div className="flex gap-2 items-stretch">
          <textarea
            id="trigger-input-textarea"
            value={newTrigger}
            onChange={(e) => {
              // eslint-disable-next-line no-console
              console.log(`[SkillBuilderModal] textarea onChange: "${e.target.value.slice(0, 30)}..."`);
              setNewTrigger(e.target.value);
            }}
            onPaste={(e) => {
              // When user pastes multi-line text, auto-add each line as a trigger
              // and CLEAR the textarea so they see the result.
              const pasted = e.clipboardData.getData('text');
              // eslint-disable-next-line no-console
              console.log(`[SkillBuilderModal] paste detected: ${pasted.split('\n').length} line(s)`);
              if (pasted.includes('\n') && pasted.trim()) {
                e.preventDefault();
                addTrigger(pasted);
              }
            }}
            onKeyDown={(e) => {
              // Plain Enter → add trigger (and consume newline)
              // Shift+Enter → allow newline within the textarea
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                // eslint-disable-next-line no-console
                console.log(`[SkillBuilderModal] Enter pressed in textarea`);
                const currentValue = (e.target as HTMLTextAreaElement).value;
                addTrigger(currentValue);
              }
            }}
            placeholder={`Paste your 8 triggers here (one per line) and they'll auto-add:

when user asks about recent events or current news
when user needs external facts not in their training data
...`}
            rows={6}
            className="flex-1 px-3 py-2 bg-white border-2 border-gray-300 rounded-lg text-sm text-gray-900 placeholder:text-gray-400 focus:outline-none focus:ring-2 focus:ring-primary focus:border-primary"
            style={{ minHeight: 130 }}
          />
        </div>
        {/* Action buttons — bigger, more obvious */}
        <div className="flex gap-2 mt-2">
          <button
            onClick={() => {
              // eslint-disable-next-line no-console
              console.log(`[SkillBuilderModal] Add button clicked`);
              addTrigger();
            }}
            className="flex items-center gap-1.5 px-4 py-2 rounded-lg text-sm font-semibold text-white"
            style={{ backgroundColor: 'var(--color-primary)' }}
          >
            <Plus size={14} />
            Add trigger(s) from box
          </button>
          <button
            onClick={() => setNewTrigger('')}
            className="px-3 py-2 rounded-lg text-sm font-medium bg-gray-100 hover:bg-gray-200 text-gray-700"
          >
            Clear box
          </button>
        </div>
      </div>
    </div>
  );

  const renderConfiguration = () => (
    <div className="space-y-4 pt-3">
      <Field
        label="Allowed Tools"
        hint="Pre-approve these LLM tools for this skill (per Agent Skills spec field `allowed-tools`)."
      >
        {/* Selected tools as chips (same pattern as Triggers/Tags) */}
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

        {/* Tool Pool selector — reuses Skill Pool pattern from Test Triggers tab */}
        <div className="rounded-lg border p-3 mb-3" style={{ backgroundColor: '#F9FAFB', borderColor: '#E8E4DA' }}>
          <div className="flex items-center justify-between mb-2">
            <label className="text-xs font-semibold uppercase" style={{ color: '#1F1E1B' }}>
              🔧 Tool Pool
            </label>
            <button
              onClick={() => setShowToolPoolEditor((s) => !s)}
              className="text-[10px] px-2 py-0.5 rounded hover:bg-gray-200"
              style={{ backgroundColor: '#E8E4DA', color: '#1F1E1B' }}
            >
              {showToolPoolEditor ? '▾ Hide' : '✎ Edit'}
            </button>
          </div>
          <div className="text-[11px]" style={{ color: '#374151' }}>
            <span><strong>{allowedTools.length}</strong> of {TOOL_POOL.length} tools selected</span>
            {toolsLoading && <span className="ml-2 italic">(loading more from registry…)</span>}
          </div>
          {showToolPoolEditor && (
            <div className="mt-2 max-h-48 overflow-y-auto space-y-1">
              <div className="flex gap-1 mb-2">
                <button
                  onClick={() => setAllowedTools(TOOL_POOL.map(t => t.id))}
                  className="text-[10px] px-2 py-0.5 rounded hover:bg-gray-200"
                  style={{ backgroundColor: '#E8E4DA', color: '#1F1E1B' }}
                >
                  Select all
                </button>
                <button
                  onClick={() => setAllowedTools([])}
                  className="text-[10px] px-2 py-0.5 rounded hover:bg-gray-200"
                  style={{ backgroundColor: '#E8E4DA', color: '#1F1E1B' }}
                >
                  Clear
                </button>
              </div>
              {TOOL_POOL.map((t) => {
                const isChecked = allowedTools.includes(t.id);
                return (
                  <label
                    key={t.id}
                    className="flex items-center gap-2 px-2 py-1 rounded hover:bg-white cursor-pointer"
                    title={t.description}
                  >
                    <input
                      type="checkbox"
                      checked={isChecked}
                      onChange={() => toggleToolFromPool(t.id)}
                      style={{ accentColor: '#D97757' }}
                    />
                    <span className="text-[11px] flex-1" style={{ color: '#1F1E1B' }}>
                      {t.name}
                    </span>
                    <span className="text-[9px] font-mono" style={{ color: '#6B7280' }}>{t.id}</span>
                  </label>
                );
              })}
            </div>
          )}
        </div>

        {/* Fallback: free-form input for custom tool names not in the pool */}
        <div className="flex gap-2">
          <input
            type="text"
            value={newTool}
            onChange={(e) => setNewTool(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && (e.preventDefault(), addTool())}
            placeholder="Add custom tool name (not in pool) — e.g. my_custom_tool"
            className="flex-1 px-3 py-2 bg-white dark:bg-background-dark border border-gray-200 rounded-lg text-sm font-mono text-gray-900 dark:text-white placeholder:text-gray-400 focus:outline-none focus:ring-2 focus:ring-primary"
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
        className="w-full px-3 py-2 bg-white dark:bg-background-dark border border-gray-200 rounded-lg text-sm font-mono text-gray-900 dark:text-white placeholder:text-gray-400 resize-none focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent"
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
        className="w-full px-3 py-2 bg-white dark:bg-background-dark border border-gray-200 rounded-lg text-sm font-mono text-gray-900 dark:text-white placeholder:text-gray-400 resize-none focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent"
      />
    </div>
  );

  const renderFiles = () => (
    <div className="space-y-3 pt-3">
      <p className="text-[11px] text-gray-500">
        Files in this skill's directory (read-only — use filesystem to add/edit scripts/, references/, assets/):
      </p>
      {effectiveExistingSkill?.source_path ? (
        <div className="rounded-lg border border-gray-200 bg-gray-50 p-3 font-mono text-xs">
          <div className="flex items-center gap-1.5 text-gray-700 mb-2">
            <FolderOpen size={12} />
            <span>{effectiveExistingSkill.source_path}</span>
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
    { id: 'discovery',     icon: '📝', title: 'Discovery',      subtitle: 'Description + tags (router-matching)', render: renderDiscovery },
    { id: 'triggers',      icon: '⚡', title: 'Triggers',       subtitle: 'Phrases that activate this skill',     render: renderTriggers },
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
                  {isEditing ? `Edit: ${effectiveExistingSkill!.name}` : 'New Skill'}
                </h2>
              </div>
              <p className="text-xs text-white/90" style={{ textShadow: '0 1px 2px rgba(0,0,0,0.15)' }}>
                {effectiveExistingSkill?.source_path || 'Drag header to move · Resize from bottom-right corner'}
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
        <div className="flex-1 overflow-y-auto" data-skill-modal-body>
          <div className="px-6 py-5 space-y-3">
            {/* Top-level error banner — visible immediately when save fails */}
            {!isEditing && (() => {
              // Aggregate any error from the body section (where create logic lives)
              const createErr = sectionErrors.body;
              if (!createErr || createErr === '✓ Saved') return null;
              return (
                <div className="flex items-start gap-2 px-4 py-3 rounded-lg border" style={{ backgroundColor: '#FEE2E2', borderColor: '#FCA5A5', color: '#991B1B' }}>
                  <X size={16} className="flex-shrink-0 mt-0.5" />
                  <div className="flex-1 text-sm">
                    <div className="font-semibold">Cannot create skill</div>
                    <div>{createErr}</div>
                  </div>
                </div>
              );
            })()}
            {/* === View-mode tabs === */}
            <div className="flex items-center gap-1 px-1 py-1 rounded-lg bg-gray-100 dark:bg-gray-800 w-fit">
              <TabButton
                active={viewMode === 'form'}
                onClick={() => setViewMode('form')}
                icon="📝"
                label="Form"
              />
              <TabButton
                active={viewMode === 'markdown'}
                onClick={() => {
                  // When switching to markdown, regenerate from current form state
                  const md = buildSkillMarkdown({
                    name, description, tags, triggers,
                    allowed_tools: allowedTools, instructions, examples,
                  });
                  setSkillMarkdown(md);
                  setMarkdownSync('idle');
                  setViewMode('markdown');
                }}
                icon="📄"
                label="Markdown"
              />
              <TabButton
                active={viewMode === 'test'}
                onClick={() => setViewMode('test')}
                icon="🎯"
                label="Test Triggers"
              />
            </div>
            {/* === Conditional view rendering === */}
            {viewMode === 'form' && sections.map((sec) => {
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

            {/* === Markdown view === */}
            {viewMode === 'markdown' && (
              <div className="rounded-xl border border-gray-200 overflow-hidden bg-white">
                <div className="flex items-center justify-between gap-2 px-4 py-2.5" style={{ backgroundColor: '#FAF9F5', borderBottom: '1px solid #E8E4DA' }}>
                  <div className="flex items-center gap-2">
                    <span className="text-sm">📄</span>
                    <span className="text-sm font-medium">SKILL.md</span>
                    {markdownSync === 'ok' && (
                      <span className="text-[10px] px-2 py-0.5 rounded" style={{ backgroundColor: '#D1FAE5', color: '#065F46' }}>
                        ✓ parsed
                      </span>
                    )}
                    {markdownSync === 'error' && (
                      <span className="text-[10px] px-2 py-0.5 rounded" style={{ backgroundColor: '#FEE2E2', color: '#991B1B' }}>
                        ✗ not valid SKILL.md
                      </span>
                    )}
                  </div>
                  <div className="flex gap-2">
                    <button
                      onClick={() => {
                        // Re-generate markdown from current form state
                        const md = buildSkillMarkdown({
                          name, description, tags, triggers,
                          allowed_tools: allowedTools, instructions, examples,
                        });
                        setSkillMarkdown(md);
                        setMarkdownSync('idle');
                      }}
                      className="px-3 py-1 text-xs font-medium bg-gray-100 hover:bg-gray-200 rounded-md"
                      title="Re-generate markdown from current form state"
                    >
                      ↻ Reset to form
                    </button>
                    <button
                      onClick={() => {
                        // Sync form state from markdown text
                        const parsed = parseSkillMarkdown(skillMarkdown);
                        if (parsed) {
                          setName(parsed.name);
                          setDescription(parsed.description);
                          setTags(parsed.tags);
                          setTriggers(parsed.triggers);
                          setAllowedTools(parsed.allowed_tools);
                          setInstructions(parsed.instructions);
                          setExamples(parsed.examples);
                          setMarkdownSync('ok');
                          setTimeout(() => setMarkdownSync('idle'), 1800);
                        } else {
                          setMarkdownSync('error');
                        }
                      }}
                      className="px-3 py-1 text-xs font-medium text-white rounded-md"
                      style={{ backgroundColor: 'var(--color-primary)' }}
                      title="Apply markdown to form fields (one-way: markdown → form)"
                    >
                      ↓ Sync to form
                    </button>
                  </div>
                </div>
                <div className="p-4">
                  <p className="text-[11px] text-gray-500 mb-2">
                    Edit the full SKILL.md text. YAML frontmatter is parsed; body is the skill instructions. Click "Sync to form" to push changes back to form fields.
                  </p>
                  <textarea
                    value={skillMarkdown}
                    onChange={(e) => {
                      setSkillMarkdown(e.target.value);
                      setMarkdownSync('idle');
                    }}
                    className="w-full px-3 py-2 bg-gray-50 border border-gray-200 rounded-lg font-mono text-xs text-gray-900 focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent"
                    style={{ minHeight: 480, lineHeight: 1.5 }}
                    spellCheck={false}
                  />
                </div>
              </div>
            )}

            {/* === Test Triggers view === */}
            {viewMode === 'test' && (
              <div className="rounded-xl border border-gray-200 overflow-hidden bg-white">
                <div className="flex items-center gap-2 px-4 py-2.5" style={{ backgroundColor: '#FAF9F5', borderBottom: '1px solid #E8E4DA' }}>
                  <span className="text-sm">🎯</span>
                  <span className="text-sm font-medium">Test Triggers</span>
                  <span className="text-[10px] text-gray-500">
                    — type a sample user query and see which skills would activate
                  </span>
                </div>
                <div className="p-4 space-y-3">
                  {/* === Skill Pool selector (same pattern as Skill Playground) === */}
                  <div className="rounded-lg border p-3" style={{ backgroundColor: '#F9FAFB', borderColor: '#E8E4DA' }}>
                    <div className="flex items-center justify-between mb-2">
                      <label className="text-xs font-semibold uppercase" style={{ color: '#1F1E1B' }}>
                        🎯 Skill Pool
                      </label>
                      <button
                        onClick={() => setShowTestPoolEditor((s) => !s)}
                        className="text-[10px] px-2 py-0.5 rounded hover:bg-gray-200"
                        style={{ backgroundColor: '#E8E4DA', color: '#1F1E1B' }}
                      >
                        {showTestPoolEditor ? '▾ Hide' : '✎ Edit'}
                      </button>
                    </div>
                    <div className="text-[11px]" style={{ color: '#374151' }}>
                      {testSkillPool === null ? (
                        <span>All <strong>{allSkills.length}</strong> skills (default)</span>
                      ) : (
                        <span><strong>{testSkillPool.size}</strong> of {allSkills.length} skills selected</span>
                      )}
                    </div>
                    {showTestPoolEditor && (
                      <div className="mt-2 max-h-40 overflow-y-auto space-y-1">
                        <div className="flex gap-1 mb-2">
                          <button
                            onClick={() => setTestSkillPool(new Set(allSkills.map((s) => s.skill_id)))}
                            className="text-[10px] px-2 py-0.5 rounded hover:bg-gray-200"
                            style={{ backgroundColor: '#E8E4DA', color: '#1F1E1B' }}
                          >
                            Select all
                          </button>
                          <button
                            onClick={() => setTestSkillPool(new Set())}
                            className="text-[10px] px-2 py-0.5 rounded hover:bg-gray-200"
                            style={{ backgroundColor: '#E8E4DA', color: '#1F1E1B' }}
                          >
                            Clear
                          </button>
                          <button
                            onClick={() => setTestSkillPool(null)}
                            className="text-[10px] px-2 py-0.5 rounded hover:bg-gray-200"
                            style={{ backgroundColor: '#D1FAE5', color: '#065F46' }}
                          >
                            Use all
                          </button>
                        </div>
                        {allSkills.map((s) => {
                          const isAll = testSkillPool === null;
                          const isChecked = isAll || testSkillPool.has(s.skill_id);
                          return (
                            <label key={s.skill_id} className="flex items-center gap-2 px-2 py-1 rounded hover:bg-white cursor-pointer">
                              <input
                                type="checkbox"
                                checked={isChecked}
                                disabled={isAll}
                                onChange={(e) => {
                                  if (testSkillPool === null) return;
                                  const next = new Set(testSkillPool);
                                  if (e.target.checked) next.add(s.skill_id);
                                  else next.delete(s.skill_id);
                                  setTestSkillPool(next);
                                }}
                                style={{ accentColor: '#D97757' }}
                              />
                              <span className="text-[11px] flex-1" style={{ color: '#1F1E1B' }}>
                                {s.source_type === 'builtin' ? '🔧' : '👤'} {s.name}
                              </span>
                              <span className="text-[9px] font-mono" style={{ color: '#6B7280' }}>{s.skill_id}</span>
                            </label>
                          );
                        })}
                      </div>
                    )}
                  </div>

                  <label className="block text-xs font-medium text-gray-700 uppercase">
                    Sample user input
                  </label>
                  <textarea
                    value={testInput}
                    onChange={(e) => setTestInput(e.target.value)}
                    placeholder={`e.g. "What's the latest news on AI?"\nor "Can you help me analyze this CSV file?"`}
                    rows={3}
                    className="w-full px-3 py-2 bg-white border border-gray-200 rounded-lg text-sm text-gray-900 placeholder:text-gray-400 focus:outline-none focus:ring-2 focus:ring-primary"
                  />
                  <button
                    onClick={async () => {
                      if (!testInput.trim()) return;
                      setTestRunning(true);
                      setTestResults(null);
                      try {
                        const matchPayload: any = {
                          query: testInput,
                          max_results: 20,
                        };
                        if (testSkillPool !== null) {
                          matchPayload.skill_ids = Array.from(testSkillPool);
                        }
                        const resp = await apiClient.post('/api/skills/match', matchPayload);
                        // The endpoint may return matches in various shapes
                        const data = resp.data;
                        if (Array.isArray(data)) {
                          setTestResults(data);
                        } else if (data?.matches) {
                          setTestResults(data.matches);
                        } else {
                          setTestResults([]);
                        }
                      } catch (err: any) {
                        setTestResults([]);
                        setSectionError('body', `Test failed: ${err.message}`);
                      } finally {
                        setTestRunning(false);
                      }
                    }}
                    disabled={testRunning || !testInput.trim()}
                    className="px-4 py-2 rounded-lg text-sm font-medium text-white disabled:opacity-50"
                    style={{ backgroundColor: 'var(--color-primary)' }}
                  >
                    {testRunning ? 'Testing…' : '▶ Run test'}
                  </button>
                  {testResults !== null && (
                    <div className="space-y-2">
                      <div className="text-xs font-medium text-gray-700 uppercase flex items-center gap-2">
                        <span>Results ({testResults.length} match{testResults.length === 1 ? '' : 'es'})</span>
                        {testSkillPool !== null && (
                          <span className="text-[10px] normal-case font-normal" style={{ color: '#6B7280' }}>
                            from pool of {testSkillPool.size} skills
                          </span>
                        )}
                      </div>
                      {testResults.length === 0 && (
                        <div className="text-xs italic" style={{ color: '#374151' }}>No skills match. Try adding more triggers or improve description.</div>
                      )}
                      {testResults.map((r, i) => {
                        // Handle both flat shape {skill_id, score} and nested {skill: {name}, score}
                        const skillName = r.skill?.name || r.name || r.skill_id || '—';
                        const matchedTrigger = r.matched_trigger || r.match_reason;
                        return (
                          <div key={i} className="px-3 py-2 rounded-lg border" style={{
                            backgroundColor: '#FAF9F5',
                            borderColor: r.score >= 0.7 ? '#10B981' : r.score >= 0.4 ? '#F59E0B' : '#E5E7EB',
                          }}>
                            <div className="flex items-center justify-between mb-1">
                              <span
                                className="text-sm font-semibold"
                                style={{ color: '#000000', fontWeight: 700 }}
                              >
                                {skillName}
                              </span>
                              <span className="text-xs font-mono font-semibold" style={{
                                color: r.score >= 0.7 ? '#047857' : r.score >= 0.4 ? '#B45309' : '#1F2937',
                                fontWeight: 700,
                              }}>
                                score: {typeof r.score === 'number' ? r.score.toFixed(2) : '—'}
                              </span>
                            </div>
                            {matchedTrigger && (
                              <div className="text-[11px]" style={{ color: '#374151' }}>
                                Reason: <span className="font-mono">{matchedTrigger}</span>
                              </div>
                            )}
                          </div>
                        );
                      })}
                    </div>
                  )}
                </div>
              </div>
            )}
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

// Tab button — used for the Form / Markdown / Test Triggers view-mode switch
const TabButton = ({ active, onClick, icon, label }: { active: boolean; onClick: () => void; icon: string; label: string }) => (
  <button
    onClick={onClick}
    className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-colors"
    style={{
      backgroundColor: active ? 'white' : 'transparent',
      color: active ? '#1F1E1B' : '#6B7280',
      boxShadow: active ? '0 1px 3px rgba(0,0,0,0.08)' : 'none',
    }}
  >
    <span>{icon}</span>
    <span>{label}</span>
  </button>
);

export default SkillBuilderModal;