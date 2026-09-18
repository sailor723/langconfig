/**
 * ToolInspectModal — view + configure a tool for the CURRENT agent.
 *
 * Opens when a tool card body is clicked in the ToolsPicker (the card no
 * longer toggles selection — see editorToolsPicker.tsx). Shows the tool's
 * details and lets you pin per-agent default parameters (``tool_params``),
 * e.g. ``database`` for ``neo4j_agent_tool`` — so the agent knows its target
 * database at runtime without the model having to remember it.
 */
import { useEffect, useState } from 'react';
import type { LayoutTokens } from './tokens';
import apiClient from '../../lib/api-client';

export interface InspectTool {
  id: string;
  name: string;
  description: string;
}

interface DbLists {
  sql: string[];
  neo4j: string[];
}

// Module-level cache: fetch /api/graph-studio/databases once per session so
// every modal open lists the live Postgres / Neo4j databases without refetch.
let _dbListsCache: DbLists | null = null;
let _dbListsPromise: Promise<DbLists | null> | null = null;

function fetchDbLists(): Promise<DbLists | null> {
  if (_dbListsCache) return Promise.resolve(_dbListsCache);
  if (!_dbListsPromise) {
    _dbListsPromise = apiClient
      .get('/api/graph-studio/databases')
      .then((res: any) => {
        const d = res?.data ?? res ?? {};
        _dbListsCache = {
          sql: Array.isArray(d.sql) ? d.sql.map(String) : [],
          neo4j: Array.isArray(d.neo4j) ? d.neo4j.map(String) : [],
        };
        return _dbListsCache;
      })
      .catch(() => null)
      .finally(() => { _dbListsPromise = null; });
  }
  return _dbListsPromise;
}

interface Props {
  tool: InspectTool | null;
  toolParams?: Record<string, any>;
  onSave: (toolId: string, params: Record<string, any>) => void;
  onClose: () => void;
  t: LayoutTokens;
}

export default function ToolInspectModal({ tool, toolParams, onSave, onClose, t }: Props) {
  const [paramsText, setParamsText] = useState('{}');
  const [jsonError, setJsonError] = useState<string | null>(null);
  const [dbLists, setDbLists] = useState<DbLists | null>(_dbListsCache);

  useEffect(() => {
    if (!tool) return;
    const current = (toolParams && toolParams[tool.id]) || {};
    setParamsText(JSON.stringify(current, null, 2));
    setJsonError(null);
  }, [tool, toolParams]);

  useEffect(() => {
    let cancelled = false;
    fetchDbLists().then((lists) => { if (!cancelled && lists) setDbLists(lists); });
    return () => { cancelled = true; };
  }, []);

  if (!tool) return null;

  const parsed = (() => {
    try { return JSON.parse(paramsText || '{}'); }
    catch { return null; }
  })();
  const dbValue = parsed && typeof parsed.database === 'string' ? parsed.database : '';
  // Database-parameterized agents: the four wrapped LangGraph tools all
  // accept a target database — the basic pair (sql_agent_tool,
  // neo4j_agent_tool) and the planner-based advanced pair
  // (advanced_sql_agent_tool, neo4j_agent_advanced_tool). Match the exact
  // families so lookalike tools (sqlite_execute, neo4j_list_docs, ...) —
  // which don't take a `database` param — don't get the field.
  const isNeo4j =
    tool.id.startsWith('neo4j_agent_tool') ||
    tool.id.startsWith('neo4j_agent_advanced_tool');
  const isSql =
    tool.id.startsWith('sql_agent_tool') ||
    tool.id.startsWith('advanced_sql_agent_tool');
  const hasDatabase = isNeo4j || isSql;
  const dbLabel = isNeo4j ? 'Database (Neo4j)' : 'Database (PostgreSQL)';
  const dbPlaceholder = isNeo4j
    ? 'e.g. neo4j — empty = default (env NEO4J_DATABASE)'
    : 'e.g. chinook — empty = default (env SQL_POSTGRES_DB)';

  const setDatabase = (db: string) => {
    setJsonError(null);
    const base = parsed || {};
    setParamsText(JSON.stringify({ ...base, database: db }, null, 2));
  };

  const handleSave = () => {
    if (parsed === null) {
      setJsonError('Invalid JSON — fix it before saving.');
      return;
    }
    if (typeof parsed !== 'object' || Array.isArray(parsed)) {
      setJsonError('Parameters must be a JSON object (e.g. {"database": "neo4j"}).');
      return;
    }
    onSave(tool.id, parsed);
  };

  const inputStyle: React.CSSProperties = {
    width: '100%', boxSizing: 'border-box', padding: '6px 8px',
    background: t.bgContent, border: `1px solid ${t.border}`,
    borderRadius: 3, color: t.textPrimary, fontSize: 12, outline: 'none',
  };
  const labelStyle: React.CSSProperties = {
    fontSize: 11, color: t.textMuted, textTransform: 'uppercase',
    letterSpacing: 0.4, marginBottom: 4,
  };

  return (
    <div
      onClick={onClose}
      style={{
        position: 'fixed', inset: 0, zIndex: 1000,
        background: 'rgba(0,0,0,0.55)',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          width: 420, maxWidth: '90vw', maxHeight: '80vh', overflow: 'auto',
          background: t.bgSidebar, border: `1px solid ${t.border}`,
          borderRadius: 8, padding: 16, display: 'flex', flexDirection: 'column', gap: 10,
        }}
      >
        <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 8 }}>
          <div>
            <div style={{ fontSize: 15, fontWeight: 700, color: t.textPrimary }}>{tool.name}</div>
            <div style={{ fontSize: 11, color: t.textMuted, fontFamily: 'monospace' }}>{tool.id}</div>
          </div>
          <button
            onClick={onClose}
            style={{ background: 'transparent', border: 'none', color: t.textMuted, fontSize: 16, cursor: 'pointer' }}
          >✕</button>
        </div>

        <div>
          <div style={labelStyle}>Description</div>
          <div style={{ fontSize: 12, color: t.textMuted, lineHeight: 1.5 }}>{tool.description || '—'}</div>
        </div>

        {hasDatabase && (
          <div>
            <div style={labelStyle}>{dbLabel}</div>
            {(() => {
              const list = isNeo4j ? (dbLists?.neo4j ?? []) : (dbLists?.sql ?? []);
              // Preserve a saved value that isn't in the live list (e.g. a
              // database that was dropped) so the user can still see it.
              const options = dbValue && !list.includes(dbValue) ? [dbValue, ...list] : list;
              if (list.length === 0 && !dbValue) {
                // No live lists available (endpoint unreachable) — fall back
                // to free text so configuration still works.
                return (
                  <input
                    value={dbValue}
                    onChange={(e) => setDatabase(e.target.value)}
                    placeholder={dbPlaceholder}
                    style={inputStyle}
                  />
                );
              }
              return (
                <select
                  value={dbValue}
                  onChange={(e) => setDatabase(e.target.value)}
                  style={{
                    width: '100%', height: 28, padding: '0 6px', boxSizing: 'border-box',
                    background: t.bgContent, border: `1px solid ${t.border}`,
                    borderRadius: 3, color: t.textPrimary, fontSize: 12, outline: 'none',
                  }}
                >
                  <option value="">(default — env / studio)</option>
                  {options.map(db => (
                    <option key={db} value={db}>{db}</option>
                  ))}
                </select>
              );
            })()}
            <div style={{ fontSize: 10, color: t.textMuted, marginTop: 3 }}>
              Pinned onto this agent's {tool.id} — the agent queries this
              database on every call unless the model explicitly passes another.
            </div>
          </div>
        )}

        <div>
          <div style={labelStyle}>Parameters (tool_params) — JSON</div>
          <textarea
            value={paramsText}
            onChange={(e) => { setParamsText(e.target.value); setJsonError(null); }}
            rows={5}
            spellCheck={false}
            style={{ ...inputStyle, fontFamily: '"SF Mono", monospace', fontSize: 11, resize: 'vertical' }}
          />
          {jsonError && <div style={{ color: '#e5484d', fontSize: 11, marginTop: 3 }}>{jsonError}</div>}
        </div>

        <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
          <button onClick={onClose} style={{
            padding: '5px 14px', borderRadius: 4, cursor: 'pointer',
            background: 'transparent', border: `1px solid ${t.border}`, color: t.textPrimary, fontSize: 12,
          }}>Cancel</button>
          <button onClick={handleSave} style={{
            padding: '5px 14px', borderRadius: 4, cursor: 'pointer',
            background: t.accent, border: 'none', color: '#fff', fontSize: 12, fontWeight: 600,
          }}>Save</button>
        </div>
      </div>
    </div>
  );
}
