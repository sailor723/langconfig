/**
 * AnalysisPanel — Upload CSV → Generate interactive Plotly dashboard.
 *
 * Flow:
 *   1. CSV auto-converted to SQLite (fast, no LLM)
 *   2. User clicks "Generate Dashboard" → agent generates HTML
 *   3. Dashboard rendered in iframe
 *
 * Q&A is handled by the main agent chat, not here.
 */
import { useState, useEffect, useRef } from 'react';
import { X, Monitor, Loader2, BarChart3, RefreshCw } from 'lucide-react';
import apiClient from '../../../lib/api-client';

interface AnalysisPanelProps {
  sessionId: string;
  csvPath: string;
  onClose: () => void;
}

interface SchemaInfo {
  db_path: string;
  table_name: string;
  row_count: number;
  col_count: number;
  columns: string[];
}

export default function AnalysisPanel({ sessionId, csvPath, onClose }: AnalysisPanelProps) {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [schema, setSchema] = useState<SchemaInfo | null>(null);
  const [dashboardHtml, setDashboardHtml] = useState<string | null>(null);
  const [generating, setGenerating] = useState(false);
  const iframeRef = useRef<HTMLIFrameElement>(null);

  // ── Init: CSV → SQLite ─────────────────────────────────────────

  useEffect(() => {
    (async () => {
      try {
        setLoading(true);
        const resp = await apiClient.post('/api/analysis/init', {
          session_id: sessionId,
          csv_path: csvPath,
          table_name: 'data',
        });
        setSchema(resp.data);
      } catch (err: any) {
        setError(err.response?.data?.detail || err.message || 'Failed to load data');
      } finally {
        setLoading(false);
      }
    })();
  }, [sessionId, csvPath]);

  // ── Generate Dashboard ─────────────────────────────────────────

  const generateDashboard = async () => {
    if (!schema || generating) return;
    setGenerating(true);
    setError(null);
    try {
      const resp = await apiClient.post('/api/analysis/chat', {
        session_id: sessionId,
        db_path: schema.db_path,
        message: (
          'Generate an interactive HTML dashboard using Plotly. ' +
          'MUST INCLUDE all 4 sections: ' +
          '1) Control bar with filters for each categorical column + Reset button, ' +
          '2) KPI cards for key metrics, ' +
          '3) 2-3 charts (bar + pie + optional line), ' +
          '4) Key insights section at bottom with <ul id="insightList"> that updates dynamically. ' +
          'Put ALL data rows in the JS array. Save with python_execute.'
        ),
      });
      const fullText = resp.data.message || resp.data.content || '';
      const htmlMatch = fullText.match(/<!DOCTYPE html>[\s\S]*?<\/html>/i);
      if (htmlMatch) {
        setDashboardHtml(htmlMatch[0]);
      } else {
        // Try loading the saved file via /api/files/
        setDashboardHtml(null);
      }
    } catch (err: any) {
      setError(err.response?.data?.detail || err.message || 'Generation failed');
    } finally {
      setGenerating(false);
    }
  };

  // ── Render ─────────────────────────────────────────────────────

  return (
    <div className="flex flex-col bg-white rounded-lg border shadow-sm" style={{ height: '520px' }}>
      {/* Header */}
      <div className="flex items-center justify-between p-3 border-b bg-gray-50 rounded-t-lg flex-shrink-0">
        <div className="flex items-center gap-2">
          <BarChart3 className="w-5 h-5 text-blue-600" />
          <span className="font-semibold text-sm">Dashboard</span>
          {schema && (
            <span className="text-xs text-gray-500">
              ({schema.row_count} rows, {schema.col_count} cols)
            </span>
          )}
        </div>
        <div className="flex items-center gap-1">
          {schema && dashboardHtml && (
            <button
              onClick={generateDashboard}
              disabled={generating}
              className="p-1.5 rounded text-gray-400 hover:text-blue-600 hover:bg-blue-50 disabled:opacity-50"
              title="Regenerate"
            >
              <RefreshCw className="w-4 h-4" />
            </button>
          )}
          <button onClick={onClose} className="p-1 hover:bg-gray-200 rounded ml-1">
            <X className="w-4 h-4" />
          </button>
        </div>
      </div>

      {/* Body */}
      <div className="flex-1 flex flex-col min-h-0">
        {loading && (
          <div className="flex-1 flex items-center justify-center">
            <div className="flex flex-col items-center gap-3 text-gray-500">
              <Loader2 className="w-8 h-8 animate-spin text-blue-500" />
              <span className="text-sm">Loading data...</span>
            </div>
          </div>
        )}

        {error && (
          <div className="flex-1 flex items-center justify-center p-4">
            <div className="text-red-600 text-sm bg-red-50 p-4 rounded-lg">{error}</div>
          </div>
        )}

        {!loading && !error && !dashboardHtml && (
          <div className="flex-1 flex flex-col items-center justify-center p-8 gap-4">
            <Monitor className="w-12 h-12 text-gray-300" />
            <div className="text-center max-w-sm">
              <p className="text-gray-600 font-medium mb-1">Interactive Dashboard</p>
              <p className="text-gray-400 text-xs mb-4">
                {schema
                  ? `${schema.table_name} — ${schema.row_count} rows, ${schema.col_count} columns`
                  : 'Load a CSV to get started'}
              </p>
              <button
                onClick={generateDashboard}
                disabled={generating}
                className="px-6 py-2.5 bg-blue-600 text-white rounded-lg text-sm font-medium
                           hover:bg-blue-700 disabled:opacity-50 flex items-center gap-2 mx-auto"
              >
                {generating ? (
                  <><Loader2 className="w-4 h-4 animate-spin" /> Generating...</>
                ) : (
                  <><Monitor className="w-4 h-4" /> Generate Dashboard</>
                )}
              </button>
            </div>
          </div>
        )}

        {dashboardHtml && (
          <div className="flex-1 relative">
            {generating && (
              <div className="absolute inset-0 flex items-center justify-center bg-white/80 z-10">
                <div className="flex items-center gap-2 text-gray-500">
                  <Loader2 className="w-5 h-5 animate-spin" />
                  <span className="text-sm">Generating...</span>
                </div>
              </div>
            )}
            <iframe
              ref={iframeRef}
              srcDoc={dashboardHtml}
              className="w-full h-full border-0"
              title="Dashboard"
              sandbox="allow-scripts allow-same-origin"
            />
          </div>
        )}
      </div>
    </div>
  );
}
