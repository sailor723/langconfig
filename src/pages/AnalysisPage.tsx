/**
 * AnalysisPage — resizable vertical side panel for Data, Skill, Chat.
 */
import { useState, useEffect, useRef, useCallback } from 'react';
import { Monitor, Loader2, FileText, ExternalLink, Upload, Table, FileCode, MessageSquare, Send, X, GripVertical, Copy, Download, Check } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import apiClient from '../lib/api-client';
import { API_BASE_URL } from '../config/api';

interface DashboardFile {
  filename: string;
  path: string;
  size_bytes: number;
  created: string;
  // Optional enrichment from the dashboard's LangConfig Dashboard Meta block.
  db_path?: string | null;
  skills?: string[];
  mode?: string | null;
}
interface ToolTraceStep { step: number; type: string; name: string; input?: string; output?: string; }
interface ChatMessage {
  role: 'user' | 'assistant';
  content: string;
  tool_trace?: ToolTraceStep[] | null;
}

export default function AnalysisPage() {
  const [dashboards, setDashboards] = useState<DashboardFile[]>([]);
  const [loading, setLoading] = useState(true);
  const [activeDashboard, setActiveDashboard] = useState<DashboardFile | null>(null);
  const [loadingContent, setLoadingContent] = useState(false);
  const [csvFile, setCsvFile] = useState<File | null>(null);
  const [skillFile, setSkillFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadStatus, setUploadStatus] = useState('');
  const [rawData, setRawData] = useState<any[] | null>(null);
  const [activePanel, setActivePanel] = useState<'data' | 'skill' | 'chat' | null>(null);
  const [skillContent, setSkillContent] = useState<string>('');
  const [dbPath, setDbPath] = useState<string>('');
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([]);
  const [chatInput, setChatInput] = useState('');
  const [chatLoading, setChatLoading] = useState(false);
  const [copiedIdx, setCopiedIdx] = useState(-1);
  const [downloadedIdx, setDownloadedIdx] = useState(-1);
  // Set of message indices whose tool-trace panel is expanded.
  const [expandedTrace, setExpandedTrace] = useState<Set<number>>(new Set());
  const [panelWidth, setPanelWidth] = useState(() => Math.round(window.innerWidth * 0.5));
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const chatEndRef = useRef<HTMLDivElement>(null);
  const chatSessId = useRef(0);
  const resizing = useRef(false);
  const startX = useRef(0);
  const startW = useRef(400);

  const loadDashboards = async () => {
    setLoading(true);
    try {
      const r = await apiClient.get('/api/analysis/dashboards');
      const all: DashboardFile[] = r.data || [];
      setDashboards(all.filter(d => d.skills?.includes('sunhing-analyst')));
    }
    catch { setDashboards([]); } finally { setLoading(false); }
  };
  useEffect(() => { loadDashboards(); }, []);
  useEffect(() => { chatEndRef.current?.scrollIntoView({ behavior: 'smooth' }); }, [chatMessages]);

  const openDashboard = async (d: DashboardFile) => {
    setActiveDashboard(d); setLoadingContent(true); setRawData(null); setActivePanel(null); setChatMessages([]); setDbPath(''); setExpandedTrace(new Set());
    chatSessId.current = Date.now();
    try {
      // /api/analysis/dashboards now returns db_path, skills, mode from
      // the HTML's LangConfig Dashboard Meta block — so we have everything
      // we need without an extra round-trip. The legacy /data/{hash} and
      // /meta/{hash} endpoints still exist for backward compat.
      const m = d;  // DashboardFile
      setDbPath(m.db_path || '');
      // /data/{filename} → embedded data (preferred) or live DB
      try {
        const dr = await apiClient.get(`/api/analysis/data-embedded/${encodeURIComponent(d.filename)}`);
        const embedded = dr.data || {};
        // Find the largest array (the row data the dashboard renders)
        let rows: any[] = [];
        let bestKey = '';
        for (const [k, v] of Object.entries(embedded)) {
          if (Array.isArray(v) && v.length > rows.length && typeof v[0] === 'object') {
            rows = v;
            bestKey = k;
          }
        }
        setRawData(rows);
      } catch { setRawData(null); }
      // /skill-content/{filename} → concatenated SKILL.md files
      try {
        const sr = await apiClient.get(`/api/analysis/skill-content/${encodeURIComponent(d.filename)}`);
        setSkillContent(sr.data?.content || '');
      } catch { setSkillContent(''); }
      // Load prior chat history for this dashboard so reopening shows the
      // full conversation. Failures are silent — empty chat is fine.
      try {
        const hr = await apiClient.get(`/api/analysis/chat-history/${encodeURIComponent(d.filename)}`);
        const hist = (hr.data || []) as Array<{ role: string; content: string; tool_trace: ToolTraceStep[] | null }>;
        setChatMessages(hist.map(m => ({
          role: m.role as 'user' | 'assistant',
          content: m.content,
          tool_trace: m.tool_trace,
        })));
      } catch { /* no history yet */ }
    } finally { setLoadingContent(false); }
  };
  const closeDashboard = () => { setActiveDashboard(null); setRawData(null); setActivePanel(null); setChatMessages([]); setExpandedTrace(new Set()); };

  // Wipe chat history for the active dashboard (both server and UI).
  const clearChatHistory = async () => {
    if (!activeDashboard) return;
    if (!confirm(`清除本仪表盘的全部聊天记录 (${activeDashboard.filename})？`)) return;
    try {
      await apiClient.delete(`/api/analysis/chat-history/${encodeURIComponent(activeDashboard.filename)}`);
    } catch (e: any) {
      // ignore; UI will clear anyway
    }
    setChatMessages([]);
    setExpandedTrace(new Set());
  };


  const handleUpload = async () => {
    if (!csvFile) return; setUploading(true); setUploadStatus('Uploading...');
    try {
      const f = new FormData(); f.append('file', csvFile); if (skillFile) f.append('skill_file', skillFile);
      await apiClient.post('/api/analysis/upload', f); await loadDashboards(); setUploadStatus('Done!'); setCsvFile(null); setSkillFile(null);
    } catch (e: any) { setUploadStatus('Error: ' + (e?.response?.data?.detail || e.message)); } finally { setUploading(false); }
  };

  const sendChat = async () => {
    if (!chatInput.trim() || !dbPath) return;
    const msg = chatInput.trim(); setChatInput('');
    setChatMessages(p => [...p, { role: 'user', content: msg }]); setChatLoading(true);
    try {
      const res = await fetch(`${API_BASE_URL}/api/analysis/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          session_id: `analysis-${chatSessId.current}`,
          db_path: dbPath,
          message: msg,
          skill_content: skillContent || undefined,
          dashboard_filename: activeDashboard?.filename,
        }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}: ${res.statusText}`);
      // Read SSE stream from the response
      const reader = res.body?.getReader();
      if (!reader) throw new Error('No response body');
      const decoder = new TextDecoder();
      let buffer = '';
      let fullResponse = '';
      let tool_trace: any = null;
      // Insert a placeholder assistant message that will be updated
      setChatMessages(p => [...p, { role: 'assistant', content: '' }]);
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        // Parse SSE lines: each event is "data: {...}\n\n"
        const lines = buffer.split('\n');
        buffer = lines.pop() || ''; // keep incomplete line in buffer
        for (const line of lines) {
          if (line.startsWith('data: ')) {
            try {
              const evt = JSON.parse(line.slice(6));
              if (evt.type === 'chunk' && evt.content) {
                fullResponse += evt.content;
                // Update the assistant message reactively
                setChatMessages(p => p.map((m, i) =>
                  i === p.length - 1 && m.role === 'assistant'
                    ? { ...m, content: fullResponse }
                    : m
                ));
              } else if (evt.type === 'done') {
                fullResponse = evt.content || fullResponse;
                tool_trace = evt.tool_trace || null;
                // Final update
                setChatMessages(p => p.map((m, i) =>
                  i === p.length - 1 && m.role === 'assistant'
                    ? { ...m, content: fullResponse, tool_trace }
                    : m
                ));
              } else if (evt.type === 'error') {
                throw new Error(evt.message);
              }
            } catch (parseErr: any) {
              // ignore malformed events
            }
          }
        }
      }
      // If we never got a "done" event, finalize with whatever we have
      setChatMessages(p => p.map((m, i) =>
        i === p.length - 1 && m.role === 'assistant' && !m.content
          ? { ...m, content: fullResponse || '(no response)', tool_trace }
          : m
      ));
    } catch (e: any) {
      setChatMessages(p => [...p, { role: 'assistant', content: 'Error: ' + (e?.message || String(e)) }]);
    } finally { setChatLoading(false); }
  };

  // ── Resize handler ──
  const onMouseDown = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    resizing.current = true;
    startX.current = e.clientX;
    startW.current = panelWidth;
    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';
  }, [panelWidth]);

  useEffect(() => {
    const onMove = (e: MouseEvent) => {
      if (!resizing.current) return;
      const newW = Math.max(200, Math.min(window.innerWidth * 0.55, startW.current - (e.clientX - startX.current)));
      setPanelWidth(newW);
    };
    const onUp = () => {
      if (!resizing.current) return;
      resizing.current = false;
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
    };
    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', onUp);
    return () => { window.removeEventListener('mousemove', onMove); window.removeEventListener('mouseup', onUp); };
  }, []);

  const fmtSize = (b: number) => b < 1024 ? `${b} B` : `${(b / 1024).toFixed(1)} KB`;

  const panelBtn = (id: 'data' | 'skill' | 'chat', icon: any, label: string) => (
    <button onClick={() => setActivePanel(activePanel === id ? null : id)}
      className={"flex items-center gap-1.5 px-3 py-1.5 text-sm rounded-lg transition-colors " + (activePanel === id ? 'bg-blue-100 text-blue-700' : 'text-gray-500 hover:text-gray-700 bg-gray-100 hover:bg-gray-200')}>
      {icon} {label}
    </button>
  );

  const panelContent = () => {
    if (activePanel === 'data' && rawData) return (
      <div className="p-3 text-xs h-full flex flex-col">
        <div className="text-gray-500 mb-1.5 shrink-0 flex flex-wrap gap-x-3 gap-y-0.5">
          <span><b className="text-gray-700">源数据库:</b> <code className="bg-gray-100 px-1 rounded">{dbPath || '未知'}</code></span>
          <span><b className="text-gray-700">行数:</b> {rawData.length}</span>
          <span><b className="text-gray-700">列数:</b> {Object.keys(rawData[0] || {}).length}</span>
        </div>
        <div className="overflow-auto flex-1 border rounded">
          <table className="w-full border-collapse">
            <thead><tr className="bg-gray-100 dark:bg-gray-700 sticky top-0">
              {Object.keys(rawData[0] || {}).map(k => <th key={k} className="border px-1.5 py-1 text-left font-medium whitespace-nowrap">{k}</th>)}
            </tr></thead>
            <tbody>{rawData.map((row, i) => (
              <tr key={i} className={i % 2 === 0 ? 'bg-white' : 'bg-gray-50'}>
                {Object.values(row).map((v: any, j) => <td key={j} className="border px-1.5 py-0.5 whitespace-nowrap">{typeof v === 'number' ? (Number.isInteger(v) ? v : v.toFixed(2)) : String(v)}</td>)}
              </tr>
            ))}</tbody>
          </table>
        </div>
      </div>
    );
    if (activePanel === 'skill') return (
      <div className="p-3 text-xs h-full overflow-auto">
        {skillContent ? (
          <>
            <div className="text-gray-500 mb-1.5 flex flex-wrap gap-x-3 gap-y-0.5">
              <span><b className="text-gray-700">源数据库:</b> <code className="bg-gray-100 px-1 rounded">{dbPath || '未知'}</code></span>
              {activeDashboard?.skills && activeDashboard.skills.length > 0 && (
                <span><b className="text-gray-700">Skills:</b> {activeDashboard.skills.map(s => <code key={s} className="bg-blue-50 text-blue-700 px-1 rounded mx-0.5">{s}</code>)}</span>
              )}
              {activeDashboard?.mode && (
                <span><b className="text-gray-700">模式:</b> <code className="bg-gray-100 px-1 rounded">{activeDashboard.mode}</code></span>
              )}
            </div>
            <div className="markdown-body p-2 border rounded bg-white">
              <ReactMarkdown
                remarkPlugins={[remarkGfm]}
                components={{
                  h1: ({node, ...props}) => <h1 className="text-lg font-bold mt-2 mb-2 border-b pb-1" {...props} />,
                  h2: ({node, ...props}) => <h2 className="text-base font-bold mt-3 mb-1.5" {...props} />,
                  h3: ({node, ...props}) => <h3 className="text-sm font-bold mt-2 mb-1" {...props} />,
                  p: ({node, ...props}) => <p className="my-1" {...props} />,
                  ul: ({node, ...props}) => <ul className="list-disc pl-5 my-1" {...props} />,
                  ol: ({node, ...props}) => <ol className="list-decimal pl-5 my-1" {...props} />,
                  code: ({node, ...props}) => <code className="bg-gray-100 px-1 rounded text-[11px] font-mono" {...props} />,
                  pre: ({node, ...props}) => <pre className="bg-gray-50 border rounded p-1.5 my-1 text-[11px] font-mono overflow-auto" {...props} />,
                  a: ({node, ...props}) => <a className="text-blue-600 underline" target="_blank" rel="noreferrer" {...props} />,
                  table: ({node, ...props}) => <table className="border-collapse border border-gray-300 my-1 text-xs" {...props} />,
                  th: ({node, ...props}) => <th className="border border-gray-300 px-1.5 py-0.5 bg-gray-50" {...props} />,
                  td: ({node, ...props}) => <td className="border border-gray-300 px-1.5 py-0.5" {...props} />,
                }}
              >
                {skillContent}
              </ReactMarkdown>
            </div>
          </>
        ) : (
          <div className="text-center py-8 text-gray-400">
            <FileCode className="w-8 h-8 mx-auto mb-2 opacity-50" />
            <p>本仪表盘未声明任何 skill</p>
          </div>
        )}
      </div>
    );
    if (activePanel === 'chat') return (
      <div className="flex flex-col h-full">
        <div className="flex-1 overflow-auto p-2 space-y-2 text-base" id="chatMessages">
          {chatMessages.length === 0 && !chatLoading && (
            <div className="text-center py-6 text-gray-400 text-base">
              <MessageSquare className="w-6 h-6 mx-auto mb-1 opacity-50" /><p>Ask a question about the data</p>
            </div>
          )}
          {chatMessages.map((m, i) => (
            <div key={i} className={"flex flex-col " + (m.role === 'user' ? 'items-end' : 'items-start')}>
              <div className={"max-w-[85%] px-3 py-2 rounded-xl text-base " + (m.role === 'user' ? 'bg-blue-500 text-white' : 'bg-gray-100 text-gray-800 markdown-body')}>
                {m.role === 'assistant' ? (
                  <ReactMarkdown
                    remarkPlugins={[remarkGfm]}
                    components={{
                      // Tighten spacing inside chat bubbles.
                      p: ({node, ...props}) => <p className="my-1" {...props} />,
                      h1: ({node, ...props}) => <h1 className="text-lg font-bold mt-2 mb-1" {...props} />,
                      h2: ({node, ...props}) => <h2 className="text-base font-bold mt-2 mb-1" {...props} />,
                      h3: ({node, ...props}) => <h3 className="text-sm font-bold mt-1 mb-0.5" {...props} />,
                      ul: ({node, ...props}) => <ul className="list-disc pl-5 my-1" {...props} />,
                      ol: ({node, ...props}) => <ol className="list-decimal pl-5 my-1" {...props} />,
                      li: ({node, ...props}) => <li className="my-0.5" {...props} />,
                      table: ({node, ...props}) => <table className="border-collapse border border-gray-300 my-1 text-xs" {...props} />,
                      th: ({node, ...props}) => <th className="border border-gray-300 px-1.5 py-0.5 bg-gray-50" {...props} />,
                      td: ({node, ...props}) => <td className="border border-gray-300 px-1.5 py-0.5" {...props} />,
                      code: ({node, ...props}) => <code className="bg-gray-100 px-1 rounded text-[12px] font-mono" {...props} />,
                      pre: ({node, ...props}) => <pre className="bg-gray-50 border rounded p-1.5 my-1 text-[12px] font-mono overflow-auto" {...props} />,
                      hr: ({node, ...props}) => <hr className="my-2 border-gray-200" {...props} />,
                      a: ({node, ...props}) => <a className="text-blue-600 underline" target="_blank" rel="noreferrer" {...props} />,
                      strong: ({node, ...props}) => <strong className="font-semibold" {...props} />,
                    }}
                  >
                    {m.content}
                  </ReactMarkdown>
                ) : (
                  m.content
                )}
              </div>
              {/* Tool trace — only for assistant messages that have one. */}
              {m.role === 'assistant' && m.tool_trace && m.tool_trace.length > 0 && (
                <div className="max-w-[85%] mt-1">
                  <button
                    onClick={() => {
                      setExpandedTrace(prev => {
                        const next = new Set(prev);
                        if (next.has(i)) next.delete(i); else next.add(i);
                        return next;
                      });
                    }}
                    className="text-xs text-gray-500 hover:text-gray-700 flex items-center gap-1"
                    title="Show / hide tool calls"
                  >
                    {expandedTrace.has(i) ? '▼' : '▶'} {m.tool_trace.length} 个工具调用
                  </button>
                  {expandedTrace.has(i) && (
                    <div className="mt-1 border-l-2 border-gray-200 pl-2 space-y-1">
                      {m.tool_trace.map((step, si) => (
                        <div key={si} className="text-xs bg-gray-50 border rounded p-1.5">
                          <div className="font-mono text-gray-700">
                            <span className="text-blue-600">[{step.step}]</span> <span className="font-semibold">{step.name}</span>
                          </div>
                          {step.input && (
                            <pre className="mt-0.5 text-[10px] text-gray-600 whitespace-pre-wrap break-all max-h-24 overflow-auto">
                              in: {step.input}
                            </pre>
                          )}
                          {step.output && (
                            <pre className="mt-0.5 text-[10px] text-gray-600 whitespace-pre-wrap break-all max-h-24 overflow-auto">
                              out: {step.output}
                            </pre>
                          )}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}
              <div className={"flex gap-2 pl-2 pt-1 " + (m.role === 'user' ? 'justify-end pr-2' : 'justify-start')}>
                <button
                  onClick={() => {
                    navigator.clipboard.writeText(m.content);
                    setCopiedIdx(i);
                    setTimeout(() => setCopiedIdx(-1), 1500);
                  }}
                  className="text-gray-400 hover:text-gray-600 transition-colors"
                  title="Copy message"
                >
                  {copiedIdx === i ? <Check className="w-3 h-3 text-green-500" /> : <Copy className="w-3 h-3" />}
                </button>
                <button
                  onClick={() => {
                    const blob = new Blob([m.content], {type: 'text/plain'});
                    const a = document.createElement('a');
                    a.href = URL.createObjectURL(blob);
                    a.download = 'message-' + (i+1) + '.txt';
                    a.click();
                    setDownloadedIdx(i);
                    setTimeout(() => setDownloadedIdx(-1), 1500);
                  }}
                  className="text-gray-400 hover:text-gray-600 transition-colors"
                  title="Download message"
                >
                  {downloadedIdx === i ? <Check className="w-3 h-3 text-green-500" /> : <Download className="w-3 h-3" />}
                </button>
              </div>
            </div>
          ))}

{chatLoading && <div className="flex justify-start"><div className="px-3 py-2 rounded-xl bg-gray-100 text-base text-gray-400 italic">Thinking...</div></div>}
          <div ref={chatEndRef} />
        </div>
        <div className="border-t p-1.5 flex gap-1.5 shrink-0">
          <input type="text" value={chatInput} onChange={e => setChatInput(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendChat(); }}}
            placeholder="Ask about the data..." disabled={chatLoading || !dbPath}
            className="flex-1 px-3 py-2 text-base border rounded focus:outline-none focus:ring-2 focus:ring-blue-300" />
          {chatMessages.length > 0 && (
            <button onClick={clearChatHistory} disabled={chatLoading}
              className="px-2 py-1 text-xs text-gray-500 hover:text-red-600 hover:bg-red-50 rounded disabled:opacity-50"
              title="Clear chat history for this dashboard">Clear</button>
          )}
          <button onClick={sendChat} disabled={!chatInput.trim() || chatLoading || !dbPath}
            className="px-2 py-1 bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50"><Send className="w-3 h-3" /></button>
        </div>
      </div>
    );
    return null;
  };

  // ── Detail view ──
  // Load dashboard via <iframe src=...> pointed directly at the FastAPI server
  // (NOT through the Vite /api proxy). The Vite proxy only handles /api/*, so
  // a proxied iframe would keep its document origin at :1420 and any relative
  // asset (notably /static/plotly.min.js rewritten by main.py) would resolve
  // against Vite and 404 / fall back to index.html. Pointing the iframe at
  // :8765 instead makes the inner document origin :8765, so /static/... hits
  // the real Plotly bundle.
  if (activeDashboard) {
    return (
      <div className="flex-1 flex flex-col h-full">
        {uploadBar()}
        <div className="flex items-center justify-between px-6 py-2 border-b bg-white shrink-0">
          <div className="flex items-center gap-3">
            <Monitor className="w-4 h-4 text-blue-600" />
            <span className="text-sm font-semibold">{activeDashboard.filename}</span>
            <span className="text-xs text-gray-400">{rawData ? rawData.length + ' rows' : fmtSize(activeDashboard.size_bytes)}</span>
          </div>
          <div className="flex items-center gap-2">
            {panelBtn('data', <Table className="w-3.5 h-3.5" />, 'Data')}
            {panelBtn('skill', <FileCode className="w-3.5 h-3.5" />, 'Skill')}
            {panelBtn('chat', <MessageSquare className="w-3.5 h-3.5" />, 'Chat')}
            <button onClick={closeDashboard} className="px-2 py-1 text-xs text-gray-500 hover:text-gray-700 bg-gray-100 hover:bg-gray-200 rounded-lg">Back</button>
          </div>
        </div>
        <div className="flex-1 flex overflow-hidden">
          <div className="flex-1 overflow-hidden" style={{ minWidth: '45%' }}>
            <iframe ref={iframeRef} src={`${API_BASE_URL}${activeDashboard.path}`} className="w-full h-full border-0" title={activeDashboard.filename} sandbox="allow-scripts allow-same-origin" />
          </div>
          {activePanel && (
            <>
              <div
                onMouseDown={onMouseDown}
                className="w-1.5 bg-gray-200 hover:bg-blue-400 cursor-col-resize shrink-0 relative group"
              >
                <div className="absolute inset-y-0 -left-1 -right-1" />
                <GripVertical className="w-3 h-3 text-gray-400 absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 opacity-0 group-hover:opacity-100 transition-opacity" />
              </div>
              <div style={{ width: panelWidth }} className="border-l bg-white flex flex-col overflow-hidden shrink-0">
                <div className="flex items-center justify-between px-3 py-1.5 border-b shrink-0">
                  <span className="text-xs font-medium text-gray-500 uppercase">{activePanel}</span>
                  <button onClick={() => setActivePanel(null)} className="text-gray-400 hover:text-gray-600"><X className="w-3.5 h-3.5" /></button>
                </div>
                <div className="flex-1 overflow-hidden">{panelContent()}</div>
              </div>
            </>
          )}
        </div>
      </div>
    );
  }

  // ── List view ──
  return (
    <div className="flex-1 flex flex-col h-full overflow-y-auto">
      <div className="shrink-0">
        <div className="flex items-center justify-between px-6 py-4 border-b bg-white">
          <div className="flex items-center gap-3"><Monitor className="w-5 h-5 text-blue-600" /><h1 className="text-lg font-semibold">Dashboards</h1></div>
          <button onClick={loadDashboards} className="px-3 py-1.5 text-sm text-blue-600 hover:bg-blue-50 rounded-lg">Refresh</button>
        </div>
        {uploadBar()}
      </div>
      <div className="flex-1 p-6">
        {loading && <div className="flex items-center justify-center py-16"><Loader2 className="w-8 h-8 animate-spin text-gray-400" /></div>}
        {!loading && dashboards.length === 0 && (
          <div className="flex flex-col items-center justify-center py-16 gap-4">
            <Monitor className="w-16 h-16 text-gray-200" />
            <p className="text-gray-500 font-medium">No dashboards yet</p>
            <p className="text-gray-400 text-sm">Upload a CSV above, then click <b>Generate Dashboard</b>.</p>
          </div>
        )}
        {!loading && dashboards.length > 0 && (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {dashboards.map(d => (
              <button key={d.filename} onClick={() => openDashboard(d)}
                className="flex flex-col items-center gap-3 p-6 bg-white border rounded-xl hover:shadow-md hover:border-blue-300 transition-all">
                <FileText className="w-10 h-10 text-blue-500" />
                <p className="text-sm font-medium text-gray-700 truncate max-w-full">{d.filename}</p>
                <p className="text-xs text-gray-400">{fmtSize(d.size_bytes)}</p>
                <span className="text-xs text-blue-500 flex items-center gap-1">Open <ExternalLink className="w-3 h-3" /></span>
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );

  function uploadBar() {
    return (
      <div className="px-6 pt-3 pb-2 border-b bg-white shrink-0">
        <div className="flex items-center gap-3 flex-wrap text-sm">
          <label className="flex items-center gap-2 px-3 py-1.5 bg-blue-50 text-blue-700 rounded-lg cursor-pointer hover:bg-blue-100">
            <Upload className="w-4 h-4" />{csvFile ? csvFile.name : 'Select CSV / SQLite...'}
            <input type="file" accept=".csv,.db,.sqlite,.sqlite3" className="hidden" onChange={e => setCsvFile(e.target.files?.[0] || null)} />
          </label>
          <label className="flex items-center gap-2 px-3 py-1.5 bg-gray-50 text-gray-600 rounded-lg cursor-pointer hover:bg-gray-100">
            {skillFile ? skillFile.name : '+ Skill .md'}
            <input type="file" accept=".md" className="hidden" onChange={e => setSkillFile(e.target.files?.[0] || null)} />
          </label>
          <button onClick={handleUpload} disabled={!csvFile || uploading}
            className="px-4 py-1.5 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50">
            {uploading ? 'Generating...' : 'Generate Dashboard'}
          </button>
          {uploadStatus && <span className={"text-xs " + (uploadStatus.includes('Error') ? 'text-red-500' : 'text-gray-500')}>{uploadStatus}</span>}
        </div>
      </div>
    );
  }
}
