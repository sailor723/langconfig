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
import { Plus, Database, Network, ChevronRight } from 'lucide-react';
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
                  <button
                    key={a.assistant_id}
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
                      background: active ? t.bgSelected : 'transparent',
                      borderLeft: active ? `2px solid ${group.accent}` : '2px solid transparent',
                      cursor: 'pointer',
                      textAlign: 'left',
                      width: '100%',
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
                    <span style={{ color: t.textDim, fontSize: 10, fontFamily: 'monospace' }}>{a.graph_id}</span>
                  </button>
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
