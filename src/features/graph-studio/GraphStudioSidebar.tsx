/**
 * Graph Engineering sidebar — the left rail for the studio.
 *
 * Lists the code-defined assistants and their studio threads. Selecting an
 * assistant loads its graph into the canvas; selecting a thread loads its
 * checkpointed state into the inspector.
 */
import { Plus } from 'lucide-react';
import { useLayoutTokens } from '../../components/layout2/tokens';
import { studio, useStudioState } from './studioStore';
import type { Thread } from './api';

const STATUS_COLORS: Record<Thread['status'], string> = {
  idle: '#9ca3af',
  running: '#4aa3ff',
  completed: '#4caf50',
  error: '#e5484d',
};

function threadTime(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso.slice(11, 19);
  return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

export default function GraphStudioSidebar() {
  const t = useLayoutTokens();
  const { assistants, activeAssistantId, threads, currentThreadId, databases, activeDatabase } =
    useStudioState();

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
      {/* Target database: the DB the SQL tools query */}
      <div style={sectionTitle}>Database</div>
      <div style={{ padding: '0 8px 2px' }}>
        <select
          value={activeDatabase}
          onChange={(e) => void studio.selectDatabase(e.target.value)}
          disabled={databases.length === 0}
          title="Target database for the SQL tools"
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

      {/* Assistants */}
      <div style={sectionTitle}>Assistants</div>
      <div style={{ flexShrink: 0, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 1, padding: '0 6px' }}>
        {assistants.length === 0 && (
          <span style={{ color: t.textDim, padding: '2px 8px', fontSize: 11 }}>No assistants found.</span>
        )}
        {assistants.map((a) => {
          const active = a.assistant_id === activeAssistantId;
          return (
            <button
              key={a.assistant_id}
              onClick={() => void studio.selectAssistant(a)}
              style={{
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'flex-start',
                gap: 2,
                padding: '5px 8px',
                border: 'none',
                borderRadius: 6,
                background: active ? t.bgSelected : 'transparent',
                cursor: 'pointer',
                textAlign: 'left',
              }}
            >
              <span style={{ color: active ? t.textWhite : t.textPrimary, fontSize: 12, fontWeight: 500 }}>
                {a.name}
              </span>
              <span style={{ color: t.textDim, fontSize: 10, fontFamily: 'monospace' }}>{a.graph_id}</span>
            </button>
          );
        })}
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
