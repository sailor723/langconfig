/**
 * CodeViewerModal — popup that shows a generated agent's Python source
 * (fetched from GET /api/deepagents/{id}/code) with Copy and Download
 * actions. Replaces the old folder-based export flow with a simple
 * view-and-download UX.
 */
import { useState } from 'react';
import { Check, Copy, Download, X } from 'lucide-react';
import { useLayoutTokens } from './tokens';

interface CodeViewerModalProps {
  filename: string;
  code: string;
  onClose: () => void;
}

export default function CodeViewerModal({ filename, code, onClose }: CodeViewerModalProps) {
  const t = useLayoutTokens();
  const [copied, setCopied] = useState(false);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(code);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // Clipboard API can be unavailable (e.g. non-secure context) — ignore.
    }
  };

  const download = () => {
    const blob = new Blob([code], { type: 'text/x-python' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div
      onClick={onClose}
      style={{
        position: 'fixed',
        inset: 0,
        zIndex: 1000,
        background: 'rgba(0, 0, 0, 0.5)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: 32,
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          width: '100%',
          maxWidth: 820,
          maxHeight: '80vh',
          display: 'flex',
          flexDirection: 'column',
          background: t.bgContent,
          border: `1px solid ${t.border}`,
          borderRadius: 10,
          boxShadow: '0 12px 40px rgba(0,0,0,0.35)',
          overflow: 'hidden',
        }}
      >
        {/* Header */}
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 8,
            padding: '10px 14px',
            borderBottom: `1px solid ${t.border}`,
          }}
        >
          <span style={{ fontSize: 13, fontWeight: 600, color: t.textPrimary }}>{filename}</span>
          <span style={{ fontSize: 11, color: t.textMuted }}>({code.split('\n').length} lines)</span>
          <div style={{ flex: 1 }} />
          <button
            onClick={copy}
            title="Copy to clipboard"
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: 5,
              fontSize: 12,
              padding: '4px 10px',
              borderRadius: 6,
              border: `1px solid ${t.border}`,
              background: t.bgContent,
              color: t.textPrimary,
              cursor: 'pointer',
            }}
          >
            {copied ? <Check size={13} style={{ color: '#2e7d32' }} /> : <Copy size={13} />}
            {copied ? 'Copied' : 'Copy'}
          </button>
          <button
            onClick={download}
            title="Download code"
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: 5,
              fontSize: 12,
              padding: '4px 10px',
              borderRadius: 6,
              border: 'none',
              background: '#a855f7',
              color: '#fff',
              cursor: 'pointer',
            }}
          >
            <Download size={13} />
            Download
          </button>
          <button
            onClick={onClose}
            title="Close"
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              padding: 4,
              borderRadius: 6,
              border: 'none',
              background: 'transparent',
              color: t.textMuted,
              cursor: 'pointer',
            }}
          >
            <X size={16} />
          </button>
        </div>

        {/* Code body */}
        <pre
          style={{
            flex: 1,
            overflow: 'auto',
            margin: 0,
            padding: 14,
            fontSize: 12,
            lineHeight: 1.55,
            fontFamily: 'var(--font-mono, ui-monospace, SFMono-Regular, Menlo, monospace)',
            color: t.textPrimary,
            background: t.bgBase,
            whiteSpace: 'pre',
          }}
        >
          {code}
        </pre>
      </div>
    </div>
  );
}
