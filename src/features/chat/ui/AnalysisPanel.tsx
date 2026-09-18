/**
 * AnalysisPanel — Loads a pre-generated dashboard HTML from the backend.
 *
 * Dashboard is auto-generated asynchronously right after CSV upload.
 * This panel just loads and displays it in an iframe.
 */
import { useState, useEffect, useRef } from 'react';
import { X, Monitor, Loader2, BarChart3, RefreshCw } from 'lucide-react';

interface AnalysisPanelProps {
  sessionId: string;
  /** URL path to the dashboard HTML file (e.g. /api/files/sales_dashboard.html) */
  dashboardUrl: string;
  /** Number of rows in the loaded CSV */
  rowCount?: number;
  /** Number of columns */
  colCount?: number;
  onClose: () => void;
}

export default function AnalysisPanel({
  sessionId,
  dashboardUrl,
  rowCount,
  colCount,
  onClose,
}: AnalysisPanelProps) {
  const [htmlContent, setHtmlContent] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [generating, setGenerating] = useState(
    // If we have a sessionId but no dashboardUrl, it means the backend is still generating
    !dashboardUrl
  );
  const iframeRef = useRef<HTMLIFrameElement>(null);

  // ── Load dashboard HTML ─────────────────────────────────────────

  useEffect(() => {
    if (!dashboardUrl) {
      setLoading(false);
      setGenerating(true);
      return;
    }

    (async () => {
      setLoading(true);
      setError(null);
      try {
        const resp = await fetch(dashboardUrl);
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        const html = await resp.text();
        setHtmlContent(html);
        setGenerating(false);
      } catch (err: any) {
        setError(err.message || 'Failed to load dashboard');
        setGenerating(false);
      } finally {
        setLoading(false);
      }
    })();
  }, [dashboardUrl]);

  // ── Poll for dashboard if still generating ──────────────────────

  useEffect(() => {
    if (!generating || dashboardUrl) return;

    const interval = setInterval(async () => {
      try {
        // Try loading the latest dashboard file
        const dashResp = await fetch('/api/analysis/dashboards');
        const files = await dashResp.json();
        if (files && files.length > 0) {
          const latest = files[0];
          const fileResp = await fetch(latest.path);
          if (fileResp.ok) {
            const html = await fileResp.text();
            setHtmlContent(html);
            setGenerating(false);
            setLoading(false);
            clearInterval(interval);
          }
        }
      } catch {
        // Keep polling
      }
    }, 5000); // Check every 5s

    return () => clearInterval(interval);
  }, [generating, dashboardUrl]);

  // ── Render ──────────────────────────────────────────────────────

  return (
    <div className="flex flex-col bg-white rounded-lg border shadow-sm" style={{ height: '520px' }}>
      {/* Header */}
      <div className="flex items-center justify-between p-3 border-b bg-gray-50 rounded-t-lg flex-shrink-0">
        <div className="flex items-center gap-2">
          <BarChart3 className="w-5 h-5 text-blue-600" />
          <span className="font-semibold text-sm">Dashboard</span>
          {rowCount !== undefined && (
            <span className="text-xs text-gray-500">({rowCount} rows, {colCount} cols)</span>
          )}
        </div>
        <button onClick={onClose} className="p-1 hover:bg-gray-200 rounded ml-1">
          <X className="w-4 h-4" />
        </button>
      </div>

      {/* Body */}
      <div className="flex-1 flex flex-col min-h-0">
        {loading && (
          <div className="flex-1 flex items-center justify-center">
            <div className="flex flex-col items-center gap-3 text-gray-500">
              <Loader2 className="w-8 h-8 animate-spin text-blue-500" />
              <span className="text-sm">Loading dashboard...</span>
            </div>
          </div>
        )}

        {generating && !loading && (
          <div className="flex-1 flex items-center justify-center">
            <div className="flex flex-col items-center gap-3 text-gray-500">
              <Loader2 className="w-8 h-8 animate-spin text-blue-500" />
              <span className="text-sm">Agent is generating dashboard...</span>
              <p className="text-xs text-gray-400">Usually takes 30-60 seconds</p>
            </div>
          </div>
        )}

        {error && (
          <div className="flex-1 flex items-center justify-center p-4">
            <div className="text-red-600 text-sm bg-red-50 p-4 rounded-lg">{error}</div>
          </div>
        )}

        {htmlContent && !loading && (
          <div className="flex-1 relative">
            <iframe
              ref={iframeRef}
              srcDoc={htmlContent}
              className="w-full h-full border-0"
              title="Dashboard"
              sandbox="allow-scripts allow-same-origin"
            />
          </div>
        )}

        {!loading && !generating && !htmlContent && !error && (
          <div className="flex-1 flex items-center justify-center p-4">
            <div className="text-gray-400 text-sm">
              <Monitor className="w-10 h-10 mx-auto mb-2 text-gray-300" />
              No dashboard available. Upload a CSV first.
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
