/**
 * AnalysisPage — resizable vertical side panel for Data, Skill, Chat.
 */
import { useState, useEffect, useRef, useCallback } from 'react';
import { Monitor, Loader2, FileText, ExternalLink, Upload, Table, FileCode, MessageSquare, Send, X, GripVertical, Copy, Download, Check } from 'lucide-react';
import apiClient from '../lib/api-client';
import { useTheme } from '../lib/themes';

interface DashboardFile { filename: string; path: string; size_bytes: number; created: string; }
interface ChatMessage { role: 'user' | 'assistant'; content: string; }

export default function AnalysisPage() {
  const { theme } = useTheme();
  const [dashboards, setDashboards] = useState<DashboardFile[]>([]);
  const [loading, setLoading] = useState(true);
  const [activeDashboard, setActiveDashboard] = useState<DashboardFile | null>(null);
  const [htmlContent, setHtmlContent] = useState<string | null>(null);
  const [loadingContent, setLoadingContent] = useState(false);
  const rawHtmlRef = useRef<string | null>(null);
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
  const [panelWidth, setPanelWidth] = useState(() => Math.round(window.innerWidth * 0.5));
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const chatEndRef = useRef<HTMLDivElement>(null);
  const chatSessId = useRef(0);
  const resizing = useRef(false);
  const startX = useRef(0);
  const startW = useRef(400);

  const loadDashboards = async () => {
    setLoading(true);
    try { const r = await apiClient.get('/api/analysis/dashboards'); setDashboards(r.data || []); }
    catch { setDashboards([]); } finally { setLoading(false); }
  };
  useEffect(() => { loadDashboards(); }, []);
  useEffect(() => { chatEndRef.current?.scrollIntoView({ behavior: 'smooth' }); }, [chatMessages]);
  useEffect(() => {
    if (rawHtmlRef.current) {
      setHtmlContent(applyDashTheme(rawHtmlRef.current, theme.name));
    }
  }, [theme.name]);

  const openDashboard = async (d: DashboardFile) => {
    setActiveDashboard(d); setLoadingContent(true); setRawData(null); setActivePanel(null); setChatMessages([]); setDbPath('');
    chatSessId.current = Date.now();
    try {
      const r = await apiClient.get(d.path, { responseType: 'text' }); setHtmlContent(r.data as string);
      const hash = d.filename.replace(/^dashboard_|\.html$/g, '');
      try { const dr = await apiClient.get(`/api/analysis/data/${hash}`); setRawData(dr.data || null); } catch { setRawData(null); }
      try { const mr = await apiClient.get(`/api/analysis/meta/${hash}`); const m = mr.data; setSkillContent(m?.skill_content || ''); setDbPath(m?.db_path || ''); } catch { setSkillContent(''); setDbPath(''); }
    } catch { setHtmlContent(null); } finally { setLoadingContent(false); }
  };
  const closeDashboard = () => { setActiveDashboard(null); setHtmlContent(null); setRawData(null); setActivePanel(null); setChatMessages([]); };
  const applyDashTheme = (html: string, _themeName: string): string => {
    // Inject a dark theme style block regardless of current theme
    const darkCSS = `<style id="__dashTheme">
*{transition: background-color 0.3s ease, color 0.3s ease!important}
body{background:#1a1a1a!important;color:#d0d0d0!important}
.header,.header *{background:#1e1e1e!important;color:#d0d0d0!important}
.container{background:#1a1a1a!important}
.section{background:#242424!important;box-shadow:none!important}
.section-title{color:#e0e0e0!important}
.section-desc,.kpi-label,.kpi-sub{color:#999!important}
.kpi-card{background:#242424!important;border-left-color:#555!important}
.kpi-value{color:#e0e0e0!important}
.insights{background:#242424!important;border-left-color:#555!important}
.insights li,.insights strong{color:#d0d0d0!important}
</style>
<div style="background:#ff0;color:#000;padding:2px 8px;font-size:11px;text-align:center">DARK MODE INJECTED</div>`;
    html = html.replace('<body>', '<body>' + darkCSS);
    // Regex replacements for Plotly
    html = html.replace(/plot_bgcolor:\s*['"][^'"]*['"]/g, "plot_bgcolor:'#1a1a1a'");
    html = html.replace(/paper_bgcolor:\s*['"][^'"]*['"]/g, "paper_bgcolor:'#242424'");
    html = html.replace(/gridcolor:\s*['"][^'"]*['"]/g, "gridcolor:'#333'");
    return html;
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
      const r = await apiClient.post('/api/analysis/chat', { session_id: `analysis-${chatSessId.current}`, db_path: dbPath, message: msg, skill_content: skillContent || undefined });
      setChatMessages(p => [...p, { role: 'assistant', content: r.data.message || r.data.content || '(no response)' }]);
    } catch (e: any) { setChatMessages(p => [...p, { role: 'assistant', content: 'Error: ' + (e?.response?.data?.detail || e.message) }]); }
    finally { setChatLoading(false); }
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
        <div className="text-gray-400 mb-1 shrink-0">{rawData.length} rows, {Object.keys(rawData[0] || {}).length} cols</div>
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
        {skillContent ? <pre className="whitespace-pre-wrap font-mono text-gray-700">{skillContent}</pre>
        : <div className="text-center py-8 text-gray-400"><FileCode className="w-8 h-8 mx-auto mb-2 opacity-50" /><p>No skill file</p></div>}
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
              <div className={"max-w-[85%] px-3 py-2 rounded-xl text-base " + (m.role === 'user' ? 'bg-blue-500 text-white' : 'bg-gray-100 text-gray-800')}>
                {m.content}
              </div>
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
          <button onClick={sendChat} disabled={!chatInput.trim() || chatLoading || !dbPath}
            className="px-2 py-1 bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50"><Send className="w-3 h-3" /></button>
        </div>
      </div>
    );
    return null;
  };

  // ── Detail view ──
  if (activeDashboard && htmlContent) {
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
            <iframe ref={iframeRef} srcDoc={htmlContent} className="w-full h-full border-0" title={activeDashboard.filename} sandbox="allow-scripts allow-same-origin" />
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
            <Upload className="w-4 h-4" />{csvFile ? csvFile.name : 'Select CSV...'}
            <input type="file" accept=".csv" className="hidden" onChange={e => setCsvFile(e.target.files?.[0] || null)} />
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
