/**
 * SubagentsEditor — one editing surface for `config.subagents`, shared by both
 * agent editors.
 *
 * Why this file exists: `DeepAgentEditor` had an editable Subagents section and
 * `AgentEditor` (what a `use_deepagents: false` agent opens) had nothing, so a
 * normal agent's roster was only visible to someone who opened the JSON tab. Two
 * copies of this form would drift the moment one of them learned a new entry
 * shape, so there is one component and both editors render it.
 *
 * The entry shapes are the ones the backend understands:
 *
 *   dictionary  name / description / system_prompt / tools / model / interrupt_on
 *   compiled    + workflow_id (a workflow compiled into a subgraph)
 *   langgraph   + graph_id (+ database) — a code-defined agent (neo4j_agent, …)
 *
 * Two behaviours worth knowing:
 *
 * * **Unknown keys are preserved.** Saving a card merges over the existing entry
 *   instead of replacing it, because `interrupt_on` and anything a future version
 *   adds must survive a round-trip through this form. The deep editor used to
 *   replace the object outright, which silently dropped a subagent's approval
 *   policy the first time somebody opened and saved the card.
 * * **`interrupt_on` is editable here**, per subagent. A subagent runs its own
 *   graph, so the parent's middleware never sees its tool calls — the approval has
 *   to live on the entry itself (this is the whole point of case 4's
 *   `email_expert`).
 */
import { useState } from 'react';
import { ChevronDown, ChevronRight } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import type { LayoutTokens } from './tokens';
import HitlPolicyEditor from './HitlPolicyEditor';

/** One entry of `config.subagents`. Loose on purpose: the field set varies by type. */
export interface SubagentEntry {
  name?: string;
  description?: string;
  system_prompt?: string;
  tools?: string[];
  model?: string;
  type?: 'dictionary' | 'compiled' | 'langgraph' | string;
  graph_id?: string;
  database?: string;
  workflow_id?: number;
  interrupt_on?: Record<string, unknown>;
  [key: string]: unknown;
}

export interface Draft {
  name: string;
  description: string;
  model: string;
  system_prompt: string;
  tools: string;
  type: string;
  graph_id: string;
  database: string;
  workflow_id: string;
}

const EMPTY_DRAFT: Draft = {
  name: '',
  description: '',
  model: '',
  system_prompt: '',
  tools: '',
  type: 'dictionary',
  graph_id: '',
  database: '',
  workflow_id: '',
};

/**
 * Build a `config.subagents` entry from the form, merging over whatever was there.
 *
 * Pure and exported so it can be exercised without a browser, and because this is
 * where the two easy-to-get-wrong behaviours live:
 *
 * * unknown keys survive (an entry's `interrupt_on` must not be dropped by a save
 *   that only changed its description);
 * * shape-specific keys are dropped when the type changes, so a card switched from
 *   `langgraph` to `dictionary` does not keep a stale `graph_id` the backend would
 *   then try to honour.
 */
export function subagentFromDraft(existing: SubagentEntry | undefined, draft: Draft): SubagentEntry {
  const next: SubagentEntry = { ...(existing || {}) };

  next.name = draft.name.trim();
  next.description = draft.description.trim();
  next.system_prompt = draft.system_prompt;

  delete next.type;
  delete next.graph_id;
  delete next.database;
  delete next.workflow_id;
  if (draft.type === 'langgraph') {
    next.type = 'langgraph';
    next.graph_id = draft.graph_id.trim();
    if (draft.database.trim()) next.database = draft.database.trim();
  } else if (draft.type === 'compiled') {
    next.type = 'compiled';
    const wid = Number(draft.workflow_id.trim());
    if (Number.isInteger(wid) && wid > 0) next.workflow_id = wid;
  }

  if (draft.model.trim()) next.model = draft.model.trim();
  else delete next.model;

  const tools = draft.tools.split(',').map(s => s.trim()).filter(Boolean);
  if (tools.length > 0) next.tools = tools;
  else delete next.tools;

  return next;
}

export interface SubagentsEditorProps {
  subagents: SubagentEntry[];
  /** Receives the whole new list; the caller decides where it is stored. */
  onChange: (next: SubagentEntry[]) => void;
  t: LayoutTokens;
  /** Extra line above the cards — each editor has its own caveat to make. */
  notice?: React.ReactNode;
  /** Copy for the empty state. */
  emptyHint?: string;
}

export default function SubagentsEditor({ subagents, onChange, t, notice, emptyHint }: SubagentsEditorProps) {
  // `t` is the layout token bundle here, so the translator is `tr`.
  const { t: tr } = useTranslation('chat');
  const [draft, setDraft] = useState<Draft | null>(null);
  const [editIdx, setEditIdx] = useState<number | null>(null);
  const [expanded, setExpanded] = useState<Record<number, boolean>>({});
  const [message, setMessage] = useState<{ tone: 'ok' | 'error'; text: string } | null>(null);

  const flash = (tone: 'ok' | 'error', text: string) => {
    setMessage({ tone, text });
    window.setTimeout(() => setMessage(null), 2500);
  };

  const startAdd = () => {
    setDraft({ ...EMPTY_DRAFT });
    setEditIdx(null);
  };

  const startEdit = (idx: number) => {
    const sa = subagents[idx] || {};
    setDraft({
      name: sa.name || '',
      description: sa.description || '',
      model: sa.model || '',
      system_prompt: sa.system_prompt || '',
      tools: Array.isArray(sa.tools) ? sa.tools.join(', ') : '',
      type: (sa.type as string) || 'dictionary',
      graph_id: sa.graph_id || '',
      database: sa.database || '',
      workflow_id: sa.workflow_id != null ? String(sa.workflow_id) : '',
    });
    setEditIdx(idx);
    setExpanded(prev => ({ ...prev, [idx]: true }));
  };

  const saveDraft = () => {
    if (!draft) return;
    if (!draft.name.trim()) return flash('error', tr('sa_need_name'));
    if (draft.type === 'langgraph' && !draft.graph_id.trim()) {
      return flash('error', tr('sa_need_graph'));
    }

    const next = subagentFromDraft(editIdx !== null ? subagents[editIdx] : undefined, draft);

    const list = [...subagents];
    if (editIdx !== null && editIdx < list.length) list[editIdx] = next;
    else list.push(next);
    onChange(list);
    flash('ok', editIdx !== null ? tr('sa_updated') : tr('sa_added'));
    setDraft(null);
    setEditIdx(null);
  };

  const remove = (idx: number) => {
    onChange(subagents.filter((_, i) => i !== idx));
    if (editIdx === idx) {
      setDraft(null);
      setEditIdx(null);
    }
    flash('ok', tr('sa_removed'));
  };

  const patchEntry = (idx: number, patch: Partial<SubagentEntry>) => {
    const list = [...subagents];
    list[idx] = { ...list[idx], ...patch };
    onChange(list);
  };

  const cardStyle: React.CSSProperties = {
    background: t.bgContent,
    border: `1px solid ${t.border}`,
    borderRadius: 4,
    padding: 10,
    marginTop: 8,
  };
  const labelStyle: React.CSSProperties = {
    fontSize: 11,
    color: t.textMuted,
    textTransform: 'uppercase',
    letterSpacing: 0.4,
    marginBottom: 4,
  };
  const valueStyle: React.CSSProperties = { fontSize: 13, color: t.textPrimary };
  const inputStyle: React.CSSProperties = {
    width: '100%',
    height: 28,
    padding: '0 6px',
    background: t.bgContent,
    border: `1px solid ${t.border}`,
    borderRadius: 3,
    color: t.textPrimary,
    fontSize: 12,
    outline: 'none',
    boxSizing: 'border-box',
  };
  const smallBtn: React.CSSProperties = {
    height: 24,
    padding: '0 8px',
    fontSize: 11,
    color: t.textPrimary,
    background: 'transparent',
    border: `1px solid ${t.border}`,
    borderRadius: 5,
    cursor: 'pointer',
  };

  return (
    <div style={{ padding: 4 }}>
      {notice && (
        <div style={{ fontSize: 11, color: t.textMuted, marginBottom: 10, lineHeight: 1.6 }}>
          {notice}
        </div>
      )}

      {message && (
        <div style={{
          fontSize: 11, marginBottom: 8,
          color: message.tone === 'ok' ? '#4ade80' : '#f87171',
        }}>
          {message.text}
        </div>
      )}

      <button
        onClick={startAdd}
        style={{ ...cardStyle, marginTop: 0, width: '100%', cursor: 'pointer', color: t.accent,
                 background: 'transparent', border: `1px dashed ${t.accent}`, fontWeight: 600,
                 display: 'flex', alignItems: 'center', gap: 6, justifyContent: 'center' }}
      >
        <span style={{ fontSize: 14 }}>+</span> {tr('sa_add')}
      </button>

      {draft && editIdx === null && (
        <div style={cardStyle}>
          <DraftForm
            draft={draft}
            setDraft={setDraft}
            t={t}
            inputStyle={inputStyle}
            onSave={saveDraft}
            onCancel={() => setDraft(null)}
            smallBtn={smallBtn}
            isNew
          />
        </div>
      )}

      {subagents.length === 0 && !draft && (
        <div style={{ ...valueStyle, color: t.textMuted, fontStyle: 'italic', marginTop: 10, fontSize: 12 }}>
          {emptyHint || tr('sa_empty')}
        </div>
      )}

      {subagents.map((sa, i) => {
        const open = expanded[i] ?? true;
        const isEditing = draft !== null && editIdx === i;
        const tools = Array.isArray(sa.tools) ? sa.tools : [];
        return (
          <div key={i} style={cardStyle}>
            {isEditing && draft ? (
              <DraftForm
                draft={draft}
                setDraft={setDraft}
                t={t}
                inputStyle={inputStyle}
                onSave={saveDraft}
                onCancel={() => { setDraft(null); setEditIdx(null); }}
                smallBtn={smallBtn}
              />
            ) : (
              <>
                <div
                  onClick={() => setExpanded(prev => ({ ...prev, [i]: !open }))}
                  style={{ display: 'flex', alignItems: 'center', gap: 6, cursor: 'pointer', userSelect: 'none' }}
                >
                  {open ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
                  <span style={{ ...valueStyle, fontWeight: 600 }}>{sa.name || tr('sa_card_default', { n: i + 1 })}</span>
                  <span style={{ ...valueStyle, fontSize: 11, color: t.textMuted, flex: 1, marginLeft: 6 }}>
                    {(sa.description || '').slice(0, 70)}
                  </span>
                  <span style={{ fontSize: 10, color: t.textMuted, fontFamily: 'monospace' }}>
                    {sa.type || 'dictionary'}
                  </span>
                  <button onClick={e => { e.stopPropagation(); startEdit(i); }} style={smallBtn}>{tr('sa_edit')}</button>
                  <button onClick={e => { e.stopPropagation(); remove(i); }}
                          style={{ ...smallBtn, color: '#e5484d' }}>{tr('sa_remove')}</button>
                </div>

                {open && (
                  <div style={{ marginTop: 10, paddingLeft: 19 }}>
                    <div style={labelStyle}>{tr('sa_desc_label')}</div>
                    <div style={{ ...valueStyle, marginBottom: 8 }}>{sa.description || '—'}</div>

                    {!!sa.model && (
                      <>
                        <div style={labelStyle}>{tr('sa_model_label')}</div>
                        <div style={{ ...valueStyle, fontFamily: 'monospace', marginBottom: 8 }}>{sa.model}</div>
                      </>
                    )}

                    {!!sa.graph_id && (
                      <>
                        <div style={labelStyle}>{tr('sa_graph_label')}</div>
                        <div style={{ ...valueStyle, fontFamily: 'monospace', marginBottom: 8 }}>
                          {sa.graph_id}{sa.database ? ` · ${sa.database}` : ''}
                        </div>
                      </>
                    )}

                    {sa.workflow_id != null && (
                      <>
                        <div style={labelStyle}>{tr('sa_wf_label')}</div>
                        <div style={{ ...valueStyle, fontFamily: 'monospace', marginBottom: 8 }}>{sa.workflow_id}</div>
                      </>
                    )}

                    <div style={labelStyle}>{tr('sa_tools_label')} ({tools.length})</div>
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginBottom: 8 }}>
                      {tools.length === 0 ? (
                        <span style={{ fontSize: 11, color: t.textMuted }}>
                          {tr('sa_tools_none')}
                        </span>
                      ) : (
                        tools.map((tool, j) => (
                          <span key={j} style={{
                            fontSize: 11, padding: '2px 6px', background: t.bgHover,
                            borderRadius: 3, color: t.textPrimary, fontFamily: 'monospace',
                          }}>{tool}</span>
                        ))
                      )}
                    </div>

                    {/* Approval lives on the entry, not on the parent: a subagent runs
                        its own graph, so parent middleware never sees its tool calls. */}
                    <div style={{ borderTop: `1px solid ${t.border}`, paddingTop: 8, marginTop: 4 }}>
                      <HitlPolicyEditor
                        value={sa.interrupt_on as any}
                        onChange={next => patchEntry(i, { interrupt_on: next as any })}
                        candidateTools={tools}
                        t={t}
                      />
                    </div>

                    {!!sa.system_prompt && (
                      <>
                        <div style={{ ...labelStyle, marginTop: 10 }}>{tr('sa_prompt_label')}</div>
                        <pre style={{
                          whiteSpace: 'pre-wrap', wordBreak: 'break-word',
                          fontFamily: '"SF Mono", monospace', fontSize: 11,
                          color: t.textMuted, lineHeight: 1.5, margin: 0,
                          maxHeight: 180, overflow: 'auto',
                        }}>{sa.system_prompt}</pre>
                      </>
                    )}
                  </div>
                )}
              </>
            )}
          </div>
        );
      })}
    </div>
  );
}

function DraftForm({
  draft, setDraft, t, inputStyle, onSave, onCancel, smallBtn, isNew,
}: {
  draft: Draft;
  setDraft: React.Dispatch<React.SetStateAction<Draft | null>>;
  t: LayoutTokens;
  inputStyle: React.CSSProperties;
  onSave: () => void;
  onCancel: () => void;
  smallBtn: React.CSSProperties;
  isNew?: boolean;
}) {
  // The parent guarantees a draft exists whenever this form is mounted.
  const { t: tr } = useTranslation('chat');
  const set = (patch: Partial<Draft>) => setDraft(d => ({ ...(d ?? draft), ...patch }));
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
      {isNew && (
        <div style={{ fontSize: 11, color: t.textMuted }}>{tr('sa_new')}</div>
      )}
      <input value={draft.name} onChange={e => set({ name: e.target.value })}
             placeholder={tr('sa_name_ph')} style={inputStyle} />
      <input value={draft.description} onChange={e => set({ description: e.target.value })}
             placeholder={tr('sa_desc_ph')} style={inputStyle} />
      <select value={draft.type} onChange={e => set({ type: e.target.value })}
              style={{ ...inputStyle, height: 26 }}>
        <option value="dictionary">{tr('sa_type_dictionary')}</option>
        <option value="compiled">{tr('sa_type_compiled')}</option>
        <option value="langgraph">{tr('sa_type_langgraph')}</option>
      </select>
      {draft.type === 'langgraph' && (
        <>
          <input value={draft.graph_id} onChange={e => set({ graph_id: e.target.value })}
                 placeholder={tr('sa_graph_ph')} style={inputStyle} />
          <input value={draft.database} onChange={e => set({ database: e.target.value })}
                 placeholder={tr('sa_db_ph')} style={inputStyle} />
        </>
      )}
      {draft.type === 'compiled' && (
        <input value={draft.workflow_id} onChange={e => set({ workflow_id: e.target.value })}
               placeholder={tr('sa_wf_ph')} style={inputStyle} />
      )}
      <input value={draft.model} onChange={e => set({ model: e.target.value })}
             placeholder={tr('sa_model_ph')} style={inputStyle} />
      <textarea value={draft.system_prompt} onChange={e => set({ system_prompt: e.target.value })}
                placeholder={tr('sa_prompt_ph')} rows={3}
                style={{ ...inputStyle, height: 'auto', padding: 6, fontFamily: 'monospace', resize: 'vertical' }} />
      <input value={draft.tools} onChange={e => set({ tools: e.target.value })}
             placeholder={tr('sa_tools_ph')} style={inputStyle} />
      <div style={{ display: 'flex', gap: 6 }}>
        <button onClick={onSave}
                style={{ ...smallBtn, background: t.accent, color: '#fff', border: 'none' }}>
          {isNew ? tr('sa_add_btn') : tr('sa_update_btn')}
        </button>
        <button onClick={onCancel} style={smallBtn}>{tr('sa_cancel')}</button>
      </div>
    </div>
  );
}
