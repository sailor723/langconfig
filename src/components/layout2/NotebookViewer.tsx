/**
 * NotebookViewer — full notebook editor with cell editing, execution, and save.
 *
 * Features:
 *   - Editable code cells (textarea) / markdown cells (toggle edit/preview)
 *   - +Code and +Markdown buttons between cells
 *   - Delete cell button
 *   - Run cell via stateful IPython kernel (jupyter_client)
 *   - Save notebook to .ipynb file
 *   - Kernel restart
 */
import { useEffect, useState, useCallback, useRef } from 'react';
import { useLayoutTokens } from './tokens';
import apiClient from '../../lib/api-client';
import {
  Loader, Play, Square, Terminal, AlertCircle, ChevronDown, ChevronRight,
  Plus, Trash2, Save, RefreshCw, Code, FileText, Eye, Edit3,
} from 'lucide-react';
import type { Tab } from './useLayout';

interface NotebookCellData {
  index: number;
  cell_type: string;
  source: string;
  outputs: any[];
}

interface NotebookDetail {
  module: string;
  name: string;
  display_name: string;
  cells: NotebookCellData[];
  kernel?: string;
  language: string;
}

interface CellExecutionResult {
  success: boolean;
  stdout: string;
  stderr: string;
  execute_result: string;
  error_name: string;
  error_value: string;
}

interface EditableCell extends NotebookCellData {
  /** Frontend-only: whether markdown is in edit mode */
  _editing?: boolean;
  /** Frontend-only: whether output is collapsed */
  _outputCollapsed?: boolean;
}

interface NotebookViewerProps {
  tab: Tab;
}

/** Escape HTML so user-controlled markdown cannot inject scripts (stored XSS). */
function escapeHtml(s: string): string {
  return s
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

/** Allow only safe URL schemes in rendered links/images. */
function safeUrl(url: string): string {
  const trimmed = url.trim();
  return /^(https?:|mailto:|#|\/|\.\/|\.\.\/)/i.test(trimmed) ? trimmed : '#';
}

function renderMarkdown(text: string): string {
  // Escape first, then apply the markdown transforms so captured content stays inert.
  const escaped = escapeHtml(text);
  let html = escaped
    .replace(/^### (.+)$/gm, '<h3>$1</h3>')
    .replace(/^## (.+)$/gm, '<h2>$1</h2>')
    .replace(/^# (.+)$/gm, '<h1>$1</h1>')
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.+?)\*/g, '<em>$1</em>')
    .replace(/`(.+?)`/g, '<code style="background:#2d2d2d;padding:1px 4px;border-radius:3px;font-size:0.9em">$1</code>')
    .replace(/\[([^\]]+)\]\(([^)]+)\)/g, (_m, label, url) =>
      `<a href="${safeUrl(url)}" target="_blank" style="color:#58a6ff">${label}</a>`)
    .replace(/!\[([^\]]*)\]\(([^)]+)\)/g, (_m, alt, url) =>
      `<img src="${safeUrl(url)}" alt="${alt}" style="max-width:100%;border-radius:6px;margin:8px 0" />`)
    .replace(/\n\n/g, '</p><p>')
    .replace(/^- (.+)$/gm, '<li style="margin-left:20px">$1</li>')
    .replace(/^\d+\. (.+)$/gm, '<li style="margin-left:20px">$1</li>');
  return `<p>${html}</p>`;
}

/** Styling helpers — generate style objects from layout tokens */
function useStyles(t: ReturnType<typeof useLayoutTokens>) {
  return {
    cellContainer: {
      marginBottom: 16,
      borderRadius: 8,
      border: `1px solid ${t.border}`,
      overflow: 'hidden' as const,
    },
    cellHeader: (isCode: boolean) => ({
      display: 'flex' as const,
      alignItems: 'center' as const,
      justifyContent: 'space-between' as const,
      padding: '4px 12px',
      fontSize: 11,
      background: isCode ? '#16162a' : 'transparent',
      color: t.textMuted,
      borderBottom: isCode ? `1px solid ${t.border}` : 'none',
    }),
    codeBg: '#1a1a2e',
    actionBtn: (color: string) => ({
      display: 'flex' as const,
      alignItems: 'center' as const,
      gap: 4,
      padding: '3px 10px',
      borderRadius: 4,
      border: 'none',
      background: color,
      color: '#fff',
      cursor: 'pointer' as const,
      fontSize: 11,
    }),
    addCellBtn: (t: ReturnType<typeof useLayoutTokens>) => ({
      display: 'flex' as const,
      alignItems: 'center' as const,
      justifyContent: 'center' as const,
      gap: 8,
      padding: '6px 0',
      cursor: 'pointer' as const,
      fontSize: 11,
      color: t.textMuted,
      borderTop: `1px solid transparent`,
      borderBottom: `1px solid transparent`,
      transition: 'all 0.15s',
    }),
    textarea: {
      width: '100%',
      minHeight: 60,
      border: 'none',
      outline: 'none',
      resize: 'vertical' as const,
      background: '#0d0d1a',
      color: '#e6e6e6',
      fontSize: 12,
      fontFamily: "'SF Mono', 'Fira Code', monospace",
      padding: '8px 12px',
      lineHeight: 1.5,
    },
  };
}

export default function NotebookViewer({ tab }: NotebookViewerProps) {
  const t = useLayoutTokens();
  const s = useStyles(t);
  const { module: modName, name: nbName } = tab.data || {};

  const [notebook, setNotebook] = useState<NotebookDetail | null>(null);
  const [cells, setCells] = useState<EditableCell[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saveMsg, setSaveMsg] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [executingCell, setExecutingCell] = useState<number | null>(null);
  const [executingAll, setExecutingAll] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const [cellResults, setCellResults] = useState<Record<number, CellExecutionResult>>({});

  const loadNotebook = useCallback(async () => {
    if (!modName || !nbName) { setError('Missing notebook module/name'); setLoading(false); return; }
    setLoading(true); setError(null);
    try {
      const res = await apiClient.get(`/api/notebooks/${modName}/${nbName}`);
      const nb: NotebookDetail = res.data;
      setNotebook(nb);

      // Load saved cel outputs from sessionStorage
      const savedResults = sessionStorage.getItem(`nb-results-${modName}-${nbName}`);
      if (savedResults) {
        try { setCellResults(JSON.parse(savedResults)); } catch { /* ignore */ }
      }

      setCells(nb.cells.map((c: NotebookCellData) => ({
        ...c,
        _editing: c.cell_type === 'code',
        _outputCollapsed: false,
      })));
    } catch (err: any) {
      setError(err?.message || 'Failed to load notebook');
    } finally { setLoading(false); }
  }, [modName, nbName]);

  useEffect(() => { loadNotebook(); }, [loadNotebook]);

  /** Persist cell results to sessionStorage */
  const persistResults = useCallback((results: Record<number, CellExecutionResult>) => {
    if (modName && nbName) {
      sessionStorage.setItem(`nb-results-${modName}-${nbName}`, JSON.stringify(results));
    }
  }, [modName, nbName]);

  /** Update a cell's source text */
  const updateCellSource = useCallback((index: number, source: string) => {
    setCells(prev => prev.map((c, i) => i === index ? { ...c, source } : c));
  }, []);

  /** Add a new cell at a specific index */
  const addCell = useCallback((afterIndex: number, cellType: 'code' | 'markdown') => {
    setCells(prev => {
      const newCell: EditableCell = {
        index: prev.length,
        cell_type: cellType,
        source: cellType === 'code' ? '' : '',
        outputs: [],
        _editing: true,
        _outputCollapsed: false,
      };
      const result = [...prev];
      result.splice(afterIndex + 1, 0, newCell);
      return result.map((c, i) => ({ ...c, index: i }));
    });
  }, []);

  /** Delete a cell */
  const deleteCell = useCallback((index: number) => {
    setCells(prev => prev.filter((_, i) => i !== index).map((c, i) => ({ ...c, index: i })));
  }, []);

  /** Run a single cell via kernel */
  const handleRunCell = useCallback(async (index: number) => {
    if (!modName || !nbName) return;
    const cell = cells[index];
    if (!cell || cell.cell_type !== 'code') return;

    setExecutingCell(index);
    const controller = new AbortController();
    abortRef.current = controller;
    try {
      const res = await apiClient.post(
        `/api/notebooks/${modName}/${nbName}/execute`,
        { cell_index: index },
        { signal: controller.signal },
      );
      const result: CellExecutionResult = res.data;
      setCellResults(prev => {
        const updated = { ...prev, [index]: result };
        persistResults(updated);
        return updated;
      });
    } catch (err: any) {
      if (err?.code === 'ERR_CANCELED' || err?.name === 'CanceledError') return; // User cancelled
      const result: CellExecutionResult = {
        success: false, stdout: '', stderr: `Error: ${err?.message || 'Unknown'}`,
        execute_result: '', error_name: 'APIError', error_value: err?.message || '',
      };
      setCellResults(prev => {
        const updated = { ...prev, [index]: result };
        persistResults(updated);
        return updated;
      });
    } finally {
      setExecutingCell(null);
      abortRef.current = null;
    }
  }, [modName, nbName, cells, persistResults]);

  /** Interrupt the currently running cell */
  const handleInterrupt = useCallback(async () => {
    if (!modName || !nbName) return;
    // Cancel the HTTP request
    if (abortRef.current) {
      abortRef.current.abort();
      abortRef.current = null;
    }
    // Also tell the backend to interrupt the kernel
    try {
      await apiClient.post(`/api/notebooks/${modName}/${nbName}/interrupt`);
    } catch { /* ignore */ }
    setExecutingCell(null);
    setExecutingAll(false);
  }, [modName, nbName]);

  /** Run all code cells sequentially from the beginning */
  const handleRunAll = useCallback(async () => {
    if (!modName || !nbName) return;
    setExecutingAll(true);
    // First restart the kernel to get clean state
    try {
      await apiClient.post(`/api/notebooks/${modName}/${nbName}/restart`);
    } catch { /* ignore */ }
    setCellResults({});
    persistResults({});

    // Run each code cell in sequence with a small delay
    for (let i = 0; i < cells.length; i++) {
      if (cells[i].cell_type === 'code') {
        setExecutingCell(i);
        try {
          const res = await apiClient.post(
            `/api/notebooks/${modName}/${nbName}/execute`,
            { cell_index: i },
          );
          const result: CellExecutionResult = res.data;
          setCellResults(prev => {
            const updated = { ...prev, [i]: result };
            persistResults(updated);
            return updated;
          });
        } catch (err: any) {
          setCellResults(prev => {
            const updated = { ...prev, [i]: { success: false, stdout: '', stderr: `Error: ${err?.message || ''}`, execute_result: '', error_name: 'APIError', error_value: '' } as CellExecutionResult };
            persistResults(updated);
            return updated;
          });
        } finally {
          setExecutingCell(null);
        }
        // Brief delay to let kernel breathe
        await new Promise(r => setTimeout(r, 100));
      }
    }
    setExecutingAll(false);
  }, [modName, nbName, cells, persistResults]);

  /** Restart kernel */
  const handleRestartKernel = useCallback(async () => {
    if (!modName || !nbName) return;
    try {
      await apiClient.post(`/api/notebooks/${modName}/${nbName}/restart`);
      setCellResults({});
      persistResults({});
    } catch { /* ignore */ }
  }, [modName, nbName, persistResults]);

  /** Save notebook to file */
  const handleSave = useCallback(async () => {
    if (!modName || !nbName || saving) return;
    setSaving(true); setSaveMsg('');
    try {
      const payload = {
        cells: cells.map(c => ({
          index: c.index,
          cell_type: c.cell_type,
          source: c.source,
          outputs: [],
        })),
      };
      const res = await apiClient.put(`/api/notebooks/${modName}/${nbName}/cells`, payload);
      setNotebook(res.data);
      setSaveMsg('Saved!');
      setTimeout(() => setSaveMsg(''), 2000);
    } catch (err: any) {
      setSaveMsg(`Save failed: ${err?.message || ''}`);
    } finally { setSaving(false); }
  }, [modName, nbName, cells, saving]);

  /** Toggle markdown cell edit mode */
  const toggleMarkdownEdit = useCallback((index: number) => {
    setCells(prev => prev.map((c, i) =>
      i === index ? { ...c, _editing: !c._editing } : c,
    ));
  }, []);

  /** Toggle output collapse */
  const toggleOutput = useCallback((index: number) => {
    setCells(prev => prev.map((c, i) =>
      i === index ? { ...c, _outputCollapsed: !c._outputCollapsed } : c,
    ));
  }, []);

  if (loading) {
    return (
      <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', color: t.textMuted, gap: 8 }}>
        <Loader size={16} style={{ animation: 'spin 1s linear infinite' }} />
        Loading notebook...
      </div>
    );
  }

  if (error) {
    return (
      <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#e5484d', gap: 8, padding: 40, flexDirection: 'column' }}>
        <AlertCircle size={24} />
        <p>{error}</p>
        <button onClick={loadNotebook} style={s.actionBtn(t.accent)}>Retry</button>
      </div>
    );
  }

  if (!notebook) return null;

  return (
    <div style={{
      flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden',
      background: t.bgContent,
    }}>
      {/* ===== Header ===== */}
      <div style={{
        padding: '12px 24px', borderBottom: `1px solid ${t.border}`,
        display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12,
      }}>
        <div>
          <h2 style={{ margin: 0, fontSize: 18, fontWeight: 600, color: t.textPrimary }}>
            {notebook.display_name}
          </h2>
          <p style={{ margin: '4px 0 0', fontSize: 12, color: t.textMuted }}>
            {notebook.module} &middot; {cells.length} cells
            {notebook.kernel && ` · ${notebook.kernel}`}
            {saveMsg && <span style={{ marginLeft: 12, color: saveMsg.includes('failed') ? '#e5484d' : '#3fb950' }}>{saveMsg}</span>}
          </p>
        </div>
        <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
          {executingAll ? (
            <button onClick={handleInterrupt} title="Stop All" style={s.actionBtn('#da3633')}>
              <Square size={12} /> Stop All
            </button>
          ) : (
            <button onClick={handleRunAll} title="Run All Cells" style={s.actionBtn('#238636')}>
              <Play size={12} /> Run All
            </button>
          )}
          <button onClick={handleRestartKernel} title="Restart Kernel" style={{
            ...s.actionBtn('#555'),
            background: 'transparent', color: t.textMuted, border: `1px solid ${t.border}`,
          }}>
            <RefreshCw size={12} /> Restart Kernel
          </button>
          <button onClick={handleSave} disabled={saving} title="Save Notebook" style={{
            ...s.actionBtn(t.accent),
            opacity: saving ? 0.6 : 1,
          }}>
            {saving ? <Loader size={12} style={{ animation: 'spin 1s linear infinite' }} /> : <Save size={12} />}
            Save
          </button>
        </div>
      </div>

      {/* ===== Cells Area ===== */}
      <div style={{ flex: 1, overflow: 'auto', padding: '16px 24px' }}>
        <div style={{ maxWidth: 720, margin: '0 auto' }}>
          {cells.map((cell, idx) => (
            <div key={`cell-${idx}`}>
              {/* Add-cell buttons above this cell */}
              <AddCellButtons onAdd={(type) => addCell(idx - 1, type)} t={t} />

              {/* Cell card */}
              <div style={s.cellContainer}>
              {/* Cell header */}
              <div style={s.cellHeader(cell.cell_type === 'code')}>
                <span>
                  [{idx + 1}] {cell.cell_type === 'code' ? 'Code' : 'Markdown'}
                </span>
                <div style={{ display: 'flex', gap: 4, alignItems: 'center' }}>
                  {/* Toggle markdown edit/preview */}
                  {cell.cell_type === 'markdown' && (
                    <button
                      onClick={() => toggleMarkdownEdit(idx)}
                      title={cell._editing ? 'Preview' : 'Edit'}
                      style={{
                        background: 'none', border: 'none', color: t.textMuted,
                        cursor: 'pointer', padding: 2, display: 'flex',
                      }}
                    >
                      {cell._editing ? <Eye size={12} /> : <Edit3 size={12} />}
                    </button>
                  )}
                  {/* Run button (code cells only) */}
                  {cell.cell_type === 'code' && (
                    executingCell === idx ? (
                      <button
                        onClick={handleInterrupt}
                        title="Interrupt cell"
                        style={{ ...s.actionBtn('#da3633') }}
                      >
                        <Square size={12} /> Stop
                      </button>
                    ) : (
                      <button
                        onClick={() => handleRunCell(idx)}
                        title="Run cell"
                        style={s.actionBtn('#238636')}
                      >
                        <Play size={12} /> Run
                      </button>
                    )
                  )}
                  {/* Delete cell */}
                  <button
                    onClick={() => deleteCell(idx)}
                    title="Delete cell"
                    style={{
                      background: 'none', border: 'none', color: t.textMuted,
                      cursor: 'pointer', padding: 2, display: 'flex',
                      opacity: 0.6,
                    }}
                    onMouseEnter={e => { e.currentTarget.style.color = '#e5484d'; e.currentTarget.style.opacity = '1'; }}
                    onMouseLeave={e => { e.currentTarget.style.color = t.textMuted; e.currentTarget.style.opacity = '0.6'; }}
                  >
                    <Trash2 size={12} />
                  </button>
                </div>
              </div>

              {/* Cell content */}
              <div style={{ background: cell.cell_type === 'code' ? s.codeBg : 'transparent' }}>
                {cell._editing ? (
                  /* Editable textarea */
                  <textarea
                    value={cell.source}
                    onChange={e => updateCellSource(idx, e.target.value)}
                    placeholder={cell.cell_type === 'code' ? '# Type your code here...' : 'Type markdown here...'}
                    style={{
                      ...s.textarea,
                      minHeight: cell.source ? Math.max(60, cell.source.split('\n').length * 20) : 60,
                    }}
                    spellCheck={cell.cell_type === 'markdown'}
                  />
                ) : (
                  /* Rendered markdown */
                  <div style={{ padding: '8px 12px', fontSize: 13, lineHeight: 1.6, color: t.textPrimary }}>
                    {cell.cell_type === 'markdown' ? (
                      cell.source ? (
                        <div className="notebook-markdown" dangerouslySetInnerHTML={{ __html: renderMarkdown(cell.source) }} />
                      ) : (
                        <span style={{ color: t.textMuted, fontStyle: 'italic' }}>Empty markdown cell</span>
                      )
                    ) : (
                      <pre style={{
                        margin: 0, overflow: 'auto', fontSize: 12, lineHeight: 1.5,
                        color: '#e6e6e6', fontFamily: "'SF Mono', 'Fira Code', monospace",
                      }}>
                        <code>{cell.source || <span style={{ opacity: 0.4 }}>Empty code cell</span>}</code>
                      </pre>
                    )}
                  </div>
                )}
              </div>

              {/* Cell Output (code cells with results) */}
              {cell.cell_type === 'code' && cellResults[idx] !== undefined && (
                <div style={{ borderTop: `1px solid ${t.border}` }}>
                  {/* Output toggle */}
                  <div
                    onClick={() => toggleOutput(idx)}
                    style={{
                      display: 'flex', alignItems: 'center', gap: 4,
                      padding: '4px 12px', cursor: 'pointer', fontSize: 11,
                      color: t.textMuted, userSelect: 'none', background: '#16162a',
                    }}
                    onMouseEnter={e => { e.currentTarget.style.background = '#1c1c36'; }}
                    onMouseLeave={e => { e.currentTarget.style.background = '#16162a'; }}
                  >
                    {cell._outputCollapsed ? <ChevronRight size={12} /> : <ChevronDown size={12} />}
                    <Terminal size={11} />
                    <span>Output</span>
                    {!cellResults[idx].success && (
                      <span style={{ color: '#e5484d', marginLeft: 4 }}>
                        ({cellResults[idx].error_name}: {cellResults[idx].error_value?.slice(0, 40)})
                      </span>
                    )}
                  </div>

                  {/* Output content */}
                  {!cell._outputCollapsed && (
                    <div style={{ padding: '8px 12px', fontSize: 12, lineHeight: 1.5 }}>
                      {cellResults[idx].stdout && (
                        <pre style={{ margin: 0, whiteSpace: 'pre-wrap', color: '#e6e6e6', fontFamily: "'SF Mono', 'Fira Code', monospace" }}>
                          {cellResults[idx].stdout}
                        </pre>
                      )}
                      {cellResults[idx].stderr && (
                        <pre style={{ margin: '4px 0 0', whiteSpace: 'pre-wrap', color: '#e5484d', fontFamily: "'SF Mono', 'Fira Code', monospace" }}>
                          {cellResults[idx].stderr}
                        </pre>
                      )}
                      {cellResults[idx].execute_result && (
                        <pre style={{ margin: '4px 0 0', whiteSpace: 'pre-wrap', color: '#79c0ff', fontFamily: "'SF Mono', 'Fira Code', monospace" }}>
                          Out[{idx + 1}]: {cellResults[idx].execute_result}
                        </pre>
                      )}
                      {!cellResults[idx].stdout && !cellResults[idx].stderr && !cellResults[idx].execute_result && (
                        <span style={{ color: t.textMuted, fontStyle: 'italic' }}>(no output)</span>
                      )}
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>
        ))}

        {/* Add-cell buttons at the very bottom */}
        <AddCellButtons onAdd={(type) => addCell(cells.length - 1, type)} t={t} />
        </div>
      </div>
    </div>
  );
}

/** Inline "+ Code" / "+ Markdown" buttons between cells */
function AddCellButtons({ onAdd, t }: {
  onAdd: (type: 'code' | 'markdown') => void;
  t: ReturnType<typeof useLayoutTokens>;
}) {
  const [hover, setHover] = useState(false);
  return (
    <div
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      style={{
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        gap: 8, padding: '4px 0',
        borderTop: hover ? `1px solid ${t.border}` : '1px solid transparent',
        borderBottom: hover ? `1px solid ${t.border}` : '1px solid transparent',
        transition: 'all 0.15s',
      }}
    >
      {hover && <>
        <button
          onClick={() => onAdd('code')}
          title="Add Code Cell"
          style={{
            display: 'flex', alignItems: 'center', gap: 4,
            padding: '2px 10px', borderRadius: 4, border: `1px solid ${t.border}`,
            background: t.bgContent, color: t.textMuted, cursor: 'pointer', fontSize: 11,
          }}
        >
          <Code size={11} /> + Code
        </button>
        <button
          onClick={() => onAdd('markdown')}
          title="Add Markdown Cell"
          style={{
            display: 'flex', alignItems: 'center', gap: 4,
            padding: '2px 10px', borderRadius: 4, border: `1px solid ${t.border}`,
            background: t.bgContent, color: t.textMuted, cursor: 'pointer', fontSize: 11,
          }}
        >
          <FileText size={11} /> + Markdown
        </button>
      </>}
      {!hover && <span style={{ color: t.textMuted, fontSize: 11, opacity: 0.3 }}>···</span>}
    </div>
  );
}
