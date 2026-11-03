/**
 * Graph Engineering sidebar — the left rail for the studio.
 *
 * Lists the code-defined assistants grouped by type (SQL Agents / Neo4j
 * Agents) plus their studio threads. Selecting an assistant loads its
 * graph into the canvas; selecting a thread loads its checkpointed state
 * into the inspector.
 *
 * The grouping mirrors the two agent flavors registered in the backend:
 *   backend/langgraph/sql_agent*.py    →  SQL Agents
 *   backend/langgraph/neo4j_agent*.py →  Neo4j Agents
 *
 * The "type" of each assistant is inferred from its `assistant_id` prefix
 * (the same convention used by studioStore.ts to pick SQL vs Neo4j
 * endpoints) so the grouping stays consistent with the canvas header.
 */
import { Plus, Database, Network, ChevronRight, Send, Eraser } from 'lucide-react';
import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useLayoutTokens } from '../../components/layout2/tokens';
import { studio, useStudioState } from './studioStore';
import type { Assistant, Thread } from './api';

const STATUS_COLORS: Record<Thread['status'], string> = {
  idle: '#9ca3af',
  running: '#4aa3ff',
  completed: '#4caf50',
  error: '#e5484d',
};

function threadTime(iso: string): string {
  const d2 = new Date(iso);
  if (Number.isNaN(d2.getTime())) return iso.slice(11, 19);
  return d2.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

/** Group assistants by their inferred DB type. The same convention is used
 *  in studioStore.ts to dispatch SQL vs Neo4j API endpoints. */
type AgentType = 'sql' | 'neo4j';

function agentType(a: Assistant): AgentType {
  return a.assistant_id.startsWith('neo4j_') ? 'neo4j' : 'sql';
}

interface TypeGroup {
  type: AgentType;
  /** Short label rendered as the section heading. */
  label: string;
  /** Accent color for the active row + group icon. */
  accent: string;
  /** Lucide icon for the group header. */
  Icon: typeof Database;
}

const TYPE_GROUPS: TypeGroup[] = [
  { type: 'sql',   label: 'SQL Agents',   accent: '#4aa3ff', Icon: Database },
  { type: 'neo4j', label: 'Neo4j Agents', accent: '#8b5cf6', Icon: Network },
];

export default function GraphStudioSidebar() {
  const t = useLayoutTokens();
  // Publishing is a two-step contract: the graph must already be *assigned*
  // (backend/langgraph/assigned.py — a reviewable diff), and chat needs an agent
  // record pointing at it. This button only does the second part; the backend
  // refuses with the exact reason when the first part is missing.
  const [publishing, setPublishing] = useState<string | null>(null);
  // Chat only runs *assigned* graphs (backend/langgraph/assigned.py). Studio runs
  // them all — that is the whole point of the split — so the publish button is
  // shown only for the graphs chat would accept; the rest stay draft/testable here.
  const [assignedIds, setAssignedIds] = useState<string[]>([]);
  useEffect(() => {
    let alive = true;
    fetch('/api/graph-studio/assigned')
      .then((r) => (r.ok ? r.json() : []))
      .then((rows: { graph_id: string }[]) => {
        if (alive && Array.isArray(rows)) setAssignedIds(rows.map((x) => x.graph_id));
      })
      .catch(() => { /* offline: no publish buttons, canvas still works */ });
    return () => { alive = false; };
  }, []);
  const notify = (message: string, type: 'success' | 'error' | 'warning' = 'success') => {
    window.dispatchEvent(new CustomEvent('graph-studio:toast', { detail: { message, type } }));
  };
  const publishToChat = async (assistantId: string, name: string) => {
    setPublishing(assistantId);
    try {
      const r = await fetch(
        `/api/graph-studio/assistants/${encodeURIComponent(assistantId)}/publish`,
        { method: 'POST' },
      );
      const body = await r.json().catch(() => ({}));
      if (!r.ok) {
        // 409 carries the reason the graph is not assignable — show it verbatim,
        // it names the file to edit.
        notify(body?.detail || `publish failed (HTTP ${r.status})`, 'error');
      } else if (body.created) {
        notify(`Published "${name}" to Agents as "${body.name}" (agent ${body.agent_id}).`);
      } else {
        notify(`"${name}" is already published as "${body.name}" (agent ${body.agent_id}).`, 'warning');
      }
    } catch (e) {
      notify(`publish failed: ${e instanceof Error ? e.message : String(e)}`, 'error');
    } finally {
      setPublishing(null);
    }
  };
  const { t: tr } = useTranslation('chat');
  const {
    assistants, activeAssistantId, threads, currentThreadId,
    sqlDatabases, neo4jDatabases, activeSqlDatabase, activeNeo4jDatabase,
    dbSummary,
  } = useStudioState();

  // The dropdown swaps source based on the active assistant's DB type.
  // Convention: assistant_id starts with 'sql_' or 'neo4j_'. Falls back to
  // SQL if the assistant id doesn't match (e.g. legacy agents).
  const dbType: 'sql' | 'neo4j' = activeAssistantId.startsWith('neo4j_')
    ? 'neo4j'
    : 'sql';
  const databases = dbType === 'neo4j' ? neo4jDatabases : sqlDatabases;
  const activeDatabase = dbType === 'neo4j' ? activeNeo4jDatabase : activeSqlDatabase;
  const dbTypeLabel = dbType === 'neo4j' ? 'Neo4j DB' : 'SQL DB';

  const sectionTitle: React.CSSProperties = {
    fontSize: 10.5,
    fontWeight: 600,
    textTransform: 'uppercase',
    letterSpacing: 0.6,
    color: t.textDim,
    padding: '8px 10px 4px',
  };

  return (
    <div
      style={{
        height: '100%',
        display: 'flex',
        flexDirection: 'column',
        background: t.bgSidebar,
        color: t.textPrimary,
        fontSize: 12,
        overflow: 'hidden',
      }}
    >
      {/* Target database: the DB the active assistant's tools query.
       *  Source swaps with the assistant type (SQL DBs vs Neo4j DBs). */}
      <div style={{ ...sectionTitle, display: 'flex', alignItems: 'center', gap: 6 }}>
        <span>Database</span>
        <span style={{
          fontSize: 9.5, padding: '1px 5px', borderRadius: 3,
          background: dbType === 'neo4j' ? 'rgba(24,144,255,0.18)' : 'rgba(127,127,127,0.18)',
          color: dbType === 'neo4j' ? '#1890ff' : t.textMuted,
          fontFamily: 'monospace', fontWeight: 500,
        }}>
          {dbTypeLabel}
        </span>
      </div>
      <div style={{ padding: '0 8px 2px' }}>
        <select
          value={activeDatabase}
          onChange={(e) => void studio.selectDatabase(e.target.value, dbType)}
          disabled={databases.length === 0}
          title={`Target database for the ${dbTypeLabel} tools`}
          style={{
            width: '100%',
            padding: '4px 6px',
            fontSize: 11.5,
            fontFamily: 'monospace',
            color: t.textPrimary,
            background: t.bgContent,
            border: `1px solid ${t.border}`,
            borderRadius: 6,
            outline: 'none',
            cursor: databases.length ? 'pointer' : 'not-allowed',
          }}
        >
          {databases.length === 0 && <option value="">no databases</option>}
          {databases.map((db) => (
            <option key={db} value={db}>
              {db}
              {db === activeDatabase ? ' (active)' : ''}
            </option>
          ))}
        </select>
      </div>

      {/* Assistants — grouped by DB type (SQL Agents / Neo4j Agents).
        *  Matches the studioStore convention (assistant_id prefix). The
        *  type determines which /databases/* API the canvas header talks
        *  to, so grouping them visually keeps the relationship obvious. */}
      <div style={sectionTitle}>Assistants</div>
      <div style={{
        flexShrink: 0,
        overflowY: 'auto',
        display: 'flex',
        flexDirection: 'column',
        gap: 4,
        padding: '0 6px',
      }}>
        {assistants.length === 0 && (
          <span style={{ color: t.textDim, padding: '2px 8px', fontSize: 11 }}>No assistants found.</span>
        )}
        {TYPE_GROUPS.map((group) => {
          const groupItems = assistants.filter((a) => agentType(a) === group.type);
          if (groupItems.length === 0) return null;
          const Icon = group.Icon;
          return (
            <div key={group.type} style={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
              {/* Group header (clickable to expand/collapse — collapses by
               *  default for groups with more than 2 items so the sidebar
               *  stays compact; always expanded for small groups). */}
              <div style={{
                display: 'flex',
                alignItems: 'center',
                gap: 5,
                padding: '4px 8px 2px',
                fontSize: 10,
                fontWeight: 600,
                textTransform: 'uppercase',
                letterSpacing: 0.5,
                color: group.accent,
              }}>
                <Icon size={11} />
                <span>{group.label}</span>
                <span style={{ marginLeft: 'auto', color: t.textDim, fontWeight: 500, fontSize: 10 }}>
                  {groupItems.length}
                </span>
              </div>
              {groupItems.map((a) => {
                const active = a.assistant_id === activeAssistantId;
                return (
                  <div
                    key={a.assistant_id}
                    style={{ display: 'flex', alignItems: 'stretch', borderRadius: 6,
                             background: active ? t.bgSelected : 'transparent' }}
                  >
                  <button
                    onClick={() => void studio.selectAssistant(a)}
                    title={a.description ?? a.name}
                    style={{
                      display: 'flex',
                      flexDirection: 'column',
                      alignItems: 'flex-start',
                      gap: 2,
                      padding: '5px 8px 5px 22px', // indent under the group header
                      border: 'none',
                      borderRadius: 6,
                      background: 'transparent',
                      borderLeft: active ? `2px solid ${group.accent}` : '2px solid transparent',
                      cursor: 'pointer',
                      textAlign: 'left',
                      flex: 1,
                      minWidth: 0,
                    }}
                  >
                    <span style={{
                      color: active ? t.textWhite : t.textPrimary,
                      fontSize: 12,
                      fontWeight: active ? 600 : 500,
                      display: 'flex',
                      alignItems: 'center',
                      gap: 4,
                    }}>
                      {active && <ChevronRight size={10} color={group.accent} />}
                      {a.name}
                    </span>
                    <span style={{ color: t.textDim, fontSize: 10, fontFamily: 'monospace',
                                   overflow: 'hidden', textOverflow: 'ellipsis', maxWidth: '100%' }}>{a.graph_id}</span>
                  </button>
                  {/* Publish → chat, only for graphs chat is allowed to run. */}
                  {assignedIds.includes(a.graph_id) && (
                    <button
                      onClick={(e) => { e.stopPropagation(); void publishToChat(a.assistant_id, a.name); }}
                      disabled={publishing === a.assistant_id}
                      title={`Publish "${a.name}" to chat (creates/returns the agent bound to ${a.graph_id})`}
                      style={{
                        border: 'none', background: 'transparent', cursor: 'pointer',
                        padding: '0 6px', color: group.accent, display: 'flex',
                        alignItems: 'center', opacity: publishing === a.assistant_id ? 0.4 : 1,
                      }}
                    >
                      <Send size={11} />
                    </button>
                  )}
                  </div>
                );
              })}
            </div>
          );
        })}
      </div>

      {/* Tables in the active database (below the assistant list) */}
      <div style={sectionTitle}>{tr('graph_db_tables')}</div>
      <div
        style={{
          flex: 1,
          minHeight: 120,
          maxHeight: 360,
          overflowY: 'auto',
          display: 'flex',
          flexDirection: 'column',
          gap: 1,
          padding: '0 6px',
        }}
      >
        {!dbSummary && <span style={{ color: t.textDim, padding: '2px 8px', fontSize: 11 }}>—</span>}
        {dbSummary && (dbSummary.tables ?? []).length === 0 && (
          <span style={{ color: t.textDim, padding: '2px 8px', fontSize: 11 }}>no tables</span>
        )}
        {dbSummary?.tables?.map((tbl) => (
          <div
            key={tbl.name}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 6,
              padding: '3px 8px',
              borderRadius: 5,
            }}
          >
            <span
              style={{
                flex: 1,
                minWidth: 0,
                overflow: 'hidden',
                textOverflow: 'ellipsis',
                whiteSpace: 'nowrap',
                fontFamily: 'monospace',
                fontSize: 11,
                color: t.textPrimary,
              }}
            >
              {tbl.name}
            </span>
            <span style={{ color: t.textDim, fontSize: 10, fontFamily: 'monospace', flexShrink: 0 }}>
              {tbl.rows?.toLocaleString() ?? '?'}
            </span>
          </div>
        ))}
      </div>

      <div style={{ height: 1, background: t.border, margin: '6px 10px' }} />

      {/* Threads */}
      <div style={{ display: 'flex', alignItems: 'center', padding: '8px 10px 4px' }}>
        <span style={{ fontSize: 10.5, fontWeight: 600, textTransform: 'uppercase', letterSpacing: 0.6, color: t.textDim }}>
          Threads
        </span>
        <button
          onClick={async () => {
            const assistant = assistants.find((a) => a.assistant_id === activeAssistantId);
            if (!assistant) return;
            const msg = `清空 ${assistant.name} 的对话记录？\n\n`
              + 'Studio 的线程列表和这张图的 checkpoint 记忆都会清掉，'
              + '换数据库调试时应该先做这一步。';
            if (!window.confirm(msg)) return;
            try {
              const res = await studio.clearThreads();
              window.dispatchEvent(new CustomEvent('graph-studio:toast', {
                detail: {
                  message: `已清空 ${res.cleared} 条对话（checkpoint ${res.checkpoints_deleted}），并新开一条线程`,
                  type: 'success',
                },
              }));
            } catch (e) {
              window.dispatchEvent(new CustomEvent('graph-studio:toast', {
                detail: { message: `清空失败：${e instanceof Error ? e.message : String(e)}`, type: 'error' },
              }));
            }
          }}
          title="清空对话记录（换库前用）"
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            width: 20,
            height: 20,
            border: `1px solid ${t.border}`,
            borderRadius: 5,
            background: 'transparent',
            color: t.textMuted,
            cursor: 'pointer',
            marginRight: 4,
          }}
        >
          <Eraser size={12} />
        </button>
        <button
          onClick={() => void studio.createThread()}
          title="New thread"
          style={{
            marginLeft: 'auto',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            width: 20,
            height: 20,
            border: `1px solid ${t.border}`,
            borderRadius: 5,
            background: 'transparent',
            color: t.textMuted,
            cursor: 'pointer',
          }}
        >
          <Plus size={12} />
        </button>
      </div>
      <div style={{ flex: 1, minHeight: 0, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 1, padding: '0 6px 8px' }}>
        {threads.length === 0 && (
          <span style={{ color: t.textDim, padding: '2px 8px', fontSize: 11 }}>
            No threads yet. Start a new one.
          </span>
        )}
        {threads.map((th) => {
          const active = th.thread_id === currentThreadId;
          return (
            <button
              key={th.thread_id}
              onClick={() => void studio.selectThread(th.thread_id)}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 6,
                padding: '5px 8px',
                border: 'none',
                borderRadius: 6,
                background: active ? t.bgSelected : 'transparent',
                cursor: 'pointer',
                textAlign: 'left',
              }}
            >
              <span
                style={{
                  fontSize: 10,
                  fontFamily: 'monospace',
                  color: active ? t.textWhite : t.textPrimary,
                  flex: 1,
                  minWidth: 0,
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                  whiteSpace: 'nowrap',
                }}
              >
                #{th.thread_id.slice(0, 6)}
              </span>
              <span
                style={{
                  width: 6,
                  height: 6,
                  borderRadius: '50%',
                  background: STATUS_COLORS[th.status] ?? STATUS_COLORS.idle,
                  flexShrink: 0,
                }}
              />
              <span style={{ color: t.textDim, fontSize: 10, flexShrink: 0 }}>{threadTime(th.created_at)}</span>
            </button>
          );
        })}
      </div>
    </div>
  );
}
