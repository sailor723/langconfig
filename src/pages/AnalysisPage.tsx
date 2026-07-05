/**
 * AnalysisPage — Dashboard viewer for generated Plotly HTML dashboards.
 * Upload CSV + skill.md from the main page (no need to open a dashboard first).
 */
import { useState, useEffect, useRef } from 'react';
import { Monitor, Loader2, FileText, ExternalLink, Upload } from 'lucide-react';
import apiClient from '../lib/api-client';

interface DashboardFile {
  filename: string;
  path: string;
  size_bytes: number;
  created: string;
}

export default function AnalysisPage() {
  const [dashboards, setDashboards] = useState<DashboardFile[]>([]);
  const [loading, setLoading] = useState(true);
  const [activeDashboard, setActiveDashboard] = useState<DashboardFile | null>(null);
  const [htmlContent, setHtmlContent] = useState<string | null>(null);
  const [loadingContent, setLoadingContent] = useState(false);
  const [csvFile, setCsvFile] = useState<File | null>(null);
  const [skillFile, setSkillFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadStatus, setUploadStatus] = useState('');
  const iframeRef = useRef<HTMLIFrameElement>(null);

  // ── Load dashboard list ─────────────────────────────────────────

  const loadDashboards = async () => {
    setLoading(true);
    try {
      const resp = await apiClient.get('/api/analysis/dashboards');
      setDashboards(resp.data || []);
    } catch {
      setDashboards([]);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadDashboards();
  }, []);

  // ── Load dashboard HTML ─────────────────────────────────────────

  const openDashboard = async (d: DashboardFile) => {
    setActiveDashboard(d);
    setLoadingContent(true);
    try {
      const resp = await apiClient.get(d.path, { responseType: 'text' });
      setHtmlContent(resp.data as string);
    } catch {
      setHtmlContent(null);
    } finally {
      setLoadingContent(false);
    }
  };

  const closeDashboard = () => {
    setActiveDashboard(null);
    setHtmlContent(null);
  };

  // ── Upload CSV + companion skill ─────────────────────────────
  const handleUpload = async () => {
    if (!csvFile) return;
    setUploading(true);
    setUploadStatus('Uploading and generating dashboard...');
    try {
      const form = new FormData();
      form.append('file', csvFile);
      if (skillFile) form.append('skill_file', skillFile);
      await apiClient.post('/api/analysis/upload', form);
      await loadDashboards();
      setUploadStatus('Done!');
      setCsvFile(null);
      setSkillFile(null);
    } catch (e: any) {
      setUploadStatus('Error: ' + (e?.response?.data?.detail || e.message));
    } finally {
      setUploading(false);
    }
  };

  // ── Format size ─────────────────────────────────────────────────

  const formatSize = (bytes: number) => {
    if (bytes < 1024) return `${bytes} B`;
    return `${(bytes / 1024).toFixed(1)} KB`;
  };

  // ── Upload section (shared) ──────────────────────────────────────
  const uploadBar = (
    <div className="px-6 pt-4 pb-3 border-b bg-white dark:bg-panel-dark flex-shrink-0">
      <div className="flex items-center gap-3 flex-wrap">
        <label className="flex items-center gap-2 px-3 py-1.5 text-sm bg-blue-50 text-blue-700 rounded-lg cursor-pointer hover:bg-blue-100">
          <Upload className="w-4 h-4" />
          {csvFile ? csvFile.name : 'Select CSV...'}
          <input type="file" accept=".csv" className="hidden" onChange={e => setCsvFile(e.target.files?.[0] || null)} />
        </label>
        <label className="flex items-center gap-2 px-3 py-1.5 text-sm bg-gray-50 text-gray-600 rounded-lg cursor-pointer hover:bg-gray-100">
          {skillFile ? skillFile.name : '+ Skill .md'}
          <input type="file" accept=".md" className="hidden" onChange={e => setSkillFile(e.target.files?.[0] || null)} />
        </label>
        <button
          onClick={handleUpload}
          disabled={!csvFile || uploading}
          className="px-4 py-1.5 text-sm bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50"
        >
          {uploading ? 'Generating...' : 'Generate Dashboard'}
        </button>
        {uploadStatus && (
          <span className={"text-sm " + (uploadStatus.includes('Error') ? 'text-red-500' : 'text-gray-500')}>
            {uploadStatus}
          </span>
        )}
      </div>
    </div>
  );

  // ── Dashboard detail view ────────────────────────────────────────

  if (activeDashboard && htmlContent) {
    return (
      <div className="flex-1 flex flex-col h-full">
        {uploadBar}
        <div className="flex items-center justify-between px-6 py-3 border-b bg-white dark:bg-panel-dark flex-shrink-0">
          <div className="flex items-center gap-3">
            <Monitor className="w-5 h-5 text-blue-600" />
            <span className="font-semibold text-sm">{activeDashboard.filename}</span>
            <span className="text-xs text-gray-400">{formatSize(activeDashboard.size_bytes)}</span>
          </div>
          <button
            onClick={closeDashboard}
            className="px-3 py-1.5 text-sm text-gray-500 hover:text-gray-700 bg-gray-100 hover:bg-gray-200 rounded-lg transition-colors"
          >
            Back to list
          </button>
        </div>
        <div className="flex-1">
          <iframe
            ref={iframeRef}
            srcDoc={htmlContent}
            className="w-full h-full border-0"
            title={activeDashboard.filename}
            sandbox="allow-scripts allow-same-origin"
          />
        </div>
      </div>
    );
  }

  // ── List view ────────────────────────────────────────────────────

  return (
    <div className="flex-1 flex flex-col h-full overflow-y-auto">
      {/* Header + Upload */}
      <div className="flex-shrink-0">
        <div className="flex items-center justify-between px-6 py-4 border-b bg-white dark:bg-panel-dark">
          <div className="flex items-center gap-3">
            <Monitor className="w-5 h-5 text-blue-600" />
            <h1 className="text-lg font-semibold">Dashboards</h1>
          </div>
          <button
            onClick={loadDashboards}
            className="px-3 py-1.5 text-sm text-blue-600 hover:bg-blue-50 rounded-lg transition-colors"
          >
            Refresh
          </button>
        </div>
        {uploadBar}
      </div>

      {/* Content */}
      <div className="flex-1 p-6">
        {loading && (
          <div className="flex items-center justify-center py-16">
            <Loader2 className="w-8 h-8 animate-spin text-gray-400" />
          </div>
        )}

        {!loading && dashboards.length === 0 && (
          <div className="flex flex-col items-center justify-center py-16 gap-4">
            <Monitor className="w-16 h-16 text-gray-200" />
            <div className="text-center">
              <p className="text-gray-500 font-medium">No dashboards yet</p>
              <p className="text-gray-400 text-sm mt-1">
                Upload a CSV above, then click <b>Generate Dashboard</b> to create one.
              </p>
            </div>
          </div>
        )}

        {!loading && dashboards.length > 0 && (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {dashboards.map((d) => (
              <button
                key={d.filename}
                onClick={() => openDashboard(d)}
                className="flex flex-col items-center gap-3 p-6 bg-white dark:bg-panel-dark border rounded-xl hover:shadow-md hover:border-blue-300 transition-all text-left"
              >
                <FileText className="w-10 h-10 text-blue-500" />
                <div className="text-center">
                  <p className="text-sm font-medium text-gray-700 truncate max-w-full">
                    {d.filename}
                  </p>
                  <p className="text-xs text-gray-400 mt-1">
                    {formatSize(d.size_bytes)}
                  </p>
                </div>
                <span className="text-xs text-blue-500 flex items-center gap-1 mt-auto">
                  Open <ExternalLink className="w-3 h-3" />
                </span>
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
