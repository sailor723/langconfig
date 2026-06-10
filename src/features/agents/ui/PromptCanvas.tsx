/**
 * PromptCanvas - Visual prompt assembly explorer for Deep Agents
 *
 * Shows the 4 prompt components (USER → BASE/CUSTOM → SUFFIX)
 * as stacked blocks in a canvas layout.
 */

import { useState, useEffect, useCallback } from 'react';
import { ChevronDown, ChevronRight, Code, Eye, EyeOff, Layers } from 'lucide-react';
import apiClient from '../../../lib/api-client';

interface PromptSegment {
  name: string;
  source: string;
  content: string;
  editable: boolean;
}

interface PromptData {
  segments: PromptSegment[];
  assembled: string;
}

interface Props {
  model: string;
  systemPrompt: string;
  customPrompt?: string;
  customSuffix?: string;
  onSystemPromptChange?: (val: string) => void;
  onCustomPromptChange?: (val: string) => void;
  onCustomSuffixChange?: (val: string) => void;
}

const SEGMENT_COLORS: Record<string, { bg: string; border: string; badge: string }> = {
  USER: { bg: 'bg-blue-50 dark:bg-blue-900/20', border: 'border-blue-300 dark:border-blue-700', badge: 'bg-blue-500' },
  BASE: { bg: 'bg-gray-50 dark:bg-gray-800/40', border: 'border-gray-300 dark:border-gray-600', badge: 'bg-gray-500' },
  CUSTOM: { bg: 'bg-purple-50 dark:bg-purple-900/20', border: 'border-purple-300 dark:border-purple-700', badge: 'bg-purple-500' },
  SUFFIX: { bg: 'bg-amber-50 dark:bg-amber-900/20', border: 'border-amber-300 dark:border-amber-700', badge: 'bg-amber-500' },
};

export default function PromptCanvas({ model, systemPrompt, customPrompt, customSuffix, onSystemPromptChange, onCustomPromptChange, onCustomSuffixChange }: Props) {
  const [promptData, setPromptData] = useState<PromptData | null>(null);
  const [loading, setLoading] = useState(false);
  const [expandedSegments, setExpandedSegments] = useState<Record<string, boolean>>({ USER: true, CUSTOM: !!customPrompt, SUFFIX: !!customSuffix });
  const [showAssembled, setShowAssembled] = useState(false);

  const fetchPreview = useCallback(async () => {
    setLoading(true);
    try {
      const res = await apiClient.previewPromptAssembly(model, systemPrompt, customPrompt, customSuffix);
      const data = res as any;
      const pd: PromptData = Array.isArray(data)
        ? data[0]
        : data.data
          ? data.data
          : data;
      setPromptData(pd);
    } catch (err) {
      console.error('Failed to load prompt preview:', err);
    } finally {
      setLoading(false);
    }
  }, [model, systemPrompt, customPrompt, customSuffix]);

  useEffect(() => {
    fetchPreview();
  }, [fetchPreview]);

  const toggleSegment = (name: string) => {
    setExpandedSegments(prev => ({ ...prev, [name]: !prev[name] }));
  };

  if (!promptData) {
    return (
      <div className="border rounded-lg p-6 text-center" style={{ borderColor: 'var(--color-border-dark, #e5e7eb)' }}>
        <div className="animate-spin inline-block w-5 h-5 border-2 border-primary border-t-transparent rounded-full mr-2" />
        <span className="text-sm" style={{ color: 'var(--color-text-muted)' }}>Loading prompt assembly...</span>
      </div>
    );
  }

  return (
    <div className="border rounded-lg overflow-hidden" style={{ borderColor: 'var(--color-border-dark, #e5e7eb)' }}>
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-2.5 border-b" style={{
        backgroundColor: 'var(--color-panel-header, #f9fafb)',
        borderColor: 'var(--color-border-dark, #e5e7eb)',
      }}>
        <div className="flex items-center gap-2">
          <Layers className="w-4 h-4" style={{ color: 'var(--color-text-muted)' }} />
          <span className="text-sm font-medium" style={{ color: 'var(--color-text-primary)' }}>
            Prompt Assembly Canvas
          </span>
          <span className="text-xs px-1.5 py-0.5 rounded bg-gray-200 dark:bg-gray-700" style={{ color: 'var(--color-text-muted)' }}>
            {promptData.segments.length} parts
          </span>
        </div>
        <button
          onClick={() => setShowAssembled(!showAssembled)}
          className="flex items-center gap-1 text-xs px-2 py-1 rounded hover:bg-gray-200 dark:hover:bg-gray-700"
          style={{ color: 'var(--color-text-muted)' }}
        >
          {showAssembled ? <EyeOff className="w-3.5 h-3.5" /> : <Eye className="w-3.5 h-3.5" />}
          {showAssembled ? 'Hide' : 'Show'} Full
        </button>
      </div>

      {/* Canvas */}
      <div className="p-4 space-y-3" style={{
        backgroundColor: 'var(--color-canvas-dot, #e8ecf0)',
        backgroundImage: 'radial-gradient(circle, #c8cdd4 1px, transparent 1px)',
        backgroundSize: '20px 20px',
      }}>
        {/* Flow arrows indicator */}
        {promptData.segments.length > 1 && (
          <div className="flex justify-center -mb-1">
            <div className="flex items-center gap-1 text-xs text-gray-400">
              USER <ChevronRight className="w-3 h-3" />
              {promptData.segments.some(s => s.name === 'CUSTOM') ? 'CUSTOM' : 'BASE'}
              {promptData.segments.some(s => s.name === 'SUFFIX') && <> <ChevronRight className="w-3 h-3" /> SUFFIX</>}
            </div>
          </div>
        )}

        {/* Segments */}
        {promptData.segments.map((seg, idx) => {
          const colors = SEGMENT_COLORS[seg.name] || SEGMENT_COLORS.BASE;
          const isExpanded = expandedSegments[seg.name] ?? false;

          return (
            <div key={seg.name} className={`rounded-lg border ${colors.border} ${colors.bg}`}>
              {/* Segment header */}
              <div
                className="flex items-center justify-between px-3 py-2 cursor-pointer select-none"
                onClick={() => toggleSegment(seg.name)}
              >
                <div className="flex items-center gap-2">
                  <div className={`w-2 h-2 rounded-full ${colors.badge}`} />
                  <span className="text-xs font-semibold uppercase tracking-wide" style={{ color: '#1f2937' }}>{seg.name}</span>
                  <span className="text-xs" style={{ color: '#6b7280' }}>
                    {seg.editable ? '(editable)' : `from ${seg.source}`}
                  </span>
                </div>
                <div className="flex items-center gap-2">
                  <span className="text-xs" style={{ color: '#6b7280' }}>
                    {seg.content.length.toLocaleString()} chars
                  </span>
                  {isExpanded ? <ChevronDown className="w-3.5 h-3.5" /> : <ChevronRight className="w-3.5 h-3.5" />}
                </div>
              </div>

              {/* Segment content */}
              {isExpanded && (
                <div className="px-3 pb-3">
                  {seg.editable ? (
                    <textarea
                      value={seg.content}
                      onChange={(e) => {
                        if (seg.name === 'USER' && onSystemPromptChange) onSystemPromptChange(e.target.value);
                        if (seg.name === 'CUSTOM' && onCustomPromptChange) onCustomPromptChange(e.target.value);
                        if (seg.name === 'SUFFIX' && onCustomSuffixChange) onCustomSuffixChange(e.target.value);
                      }}
                      className="w-full text-xs font-mono border rounded p-2 resize-y min-h-[80px] focus:outline-none focus:ring-1 focus:ring-primary"
                      style={{
                        backgroundColor: '#fff',
                        color: '#1f2937',
                        borderColor: 'var(--color-border-dark, #d1d5db)',
                      }}
                      placeholder={`Enter ${seg.name} content...`}
                    />
                  ) : (
                    <pre className="text-xs font-mono whitespace-pre-wrap max-h-[200px] overflow-y-auto p-2 rounded" style={{
                      backgroundColor: '#f0f2f5',
                      color: '#1f2937',
                    }}>
                      {seg.content.slice(0, 500)}{seg.content.length > 500 ? '\n... (truncated)' : ''}
                    </pre>
                  )}
                </div>
              )}
            </div>
          );
        })}

        {/* Connector arrow to assembled */}
        {promptData.segments.length > 1 && (
          <div className="flex justify-center py-1">
            <div className="border-t-2 border-dashed border-gray-300 dark:border-gray-600 w-12" />
            <ChevronDown className="w-4 h-4 text-gray-400 -mt-2.5" />
          </div>
        )}
      </div>

      {/* Assembled prompt (collapsible) */}
      {showAssembled && (
        <div className="border-t" style={{ borderColor: 'var(--color-border-dark, #e5e7eb)' }}>
          <div className="px-4 py-2 bg-gray-100 dark:bg-gray-800/50 border-b" style={{ borderColor: 'var(--color-border-dark, #e5e7eb)' }}>
            <span className="text-xs font-medium uppercase tracking-wide">Assembled Prompt</span>
            <span className="text-xs ml-2" style={{ color: 'var(--color-text-muted)' }}>
              ({promptData.assembled.length.toLocaleString()} chars)
            </span>
          </div>
          <div className="p-3 max-h-[300px] overflow-y-auto">
            <pre className="text-xs font-mono whitespace-pre-wrap" style={{ color: '#1f2937' }}>
              {`--- USER ---\n${promptData.segments.find(s => s.name === 'USER')?.content || '(empty)'}\n\n--- ${promptData.segments.find(s => s.name === 'CUSTOM') ? 'CUSTOM' : 'BASE'} (SDK) ---\n${promptData.segments.find(s => s.name === 'CUSTOM' || s.name === 'BASE')?.content || ''}`}
              {promptData.segments.find(s => s.name === 'SUFFIX') && `\n\n--- SUFFIX ---\n${promptData.segments.find(s => s.name === 'SUFFIX')?.content}`}
            </pre>
          </div>
        </div>
      )}

      {/* Toolbar */}
      <div className="flex items-center justify-between px-4 py-2 border-t" style={{
        borderColor: 'var(--color-border-dark, #e5e7eb)',
        backgroundColor: 'var(--color-panel-header, #f9fafb)',
      }}>
        <div className="flex items-center gap-3 text-xs" style={{ color: 'var(--color-text-muted)' }}>
          <span className="flex items-center gap-1">
            <span className="w-2 h-2 rounded-full bg-blue-500" /> USER
          </span>
          <span className="flex items-center gap-1">
            <span className="w-2 h-2 rounded-full bg-gray-500" /> BASE
          </span>
          <span className="flex items-center gap-1">
            <span className="w-2 h-2 rounded-full bg-purple-500" /> CUSTOM
          </span>
          <span className="flex items-center gap-1">
            <span className="w-2 h-2 rounded-full bg-amber-500" /> SUFFIX
          </span>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => {
              navigator.clipboard.writeText(promptData.assembled);
            }}
            className="text-xs px-2 py-1 rounded hover:bg-gray-200 dark:hover:bg-gray-700"
            style={{ color: 'var(--color-text-muted)' }}
          >
            <Code className="w-3.5 h-3.5 inline mr-1" />
            Copy
          </button>
          <button
            onClick={fetchPreview}
            className="text-xs px-2 py-1 rounded hover:bg-gray-200 dark:hover:bg-gray-700"
            style={{ color: 'var(--color-text-muted)' }}
          >
            Refresh
          </button>
        </div>
      </div>
    </div>
  );
}
