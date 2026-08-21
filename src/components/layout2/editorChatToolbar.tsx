/**
 * ChatTestToolbar — top action bar (test input + Run/Stop/Save) shared by
 * the agent editors.
 *
 * Extracted from AgentEditor / DeepAgentEditor. The two behavioural
 * differences between the editors are passed as props:
 *   - saveDisabled  : AgentEditor -> saving, DeepAgentEditor -> saving || !id
 *   - statusLabel   : pre-formatted right-hand status line
 *
 * Hosts the agent share actions (Export / Import / View code / Delete).
 * Imports forward the currently-active project so the new agent's
 * workspace is project-scoped. Delete is destructive and requires
 * a two-step confirmation in the caller (see AgentEditor.handleDelete
 * and DeepAgentEditor.handleDelete).
 */
import { useRef } from 'react';
import type { LayoutTokens } from './tokens';
import { Loader, Play, Square, Save, Eye, Download, Upload, Trash2 } from 'lucide-react';
import apiClient from '../../lib/api-client';
import { useProject } from '../../contexts/ProjectContext';

export interface SaveMessage {
  ok: boolean;
  text: string;
}

interface ChatTestToolbarProps {
  testPrompt: string;
  onTestPromptChange: (v: string) => void;
  running: boolean;
  onRun: () => void;
  onStop: () => void;
  saving: boolean;
  onSave: () => void;
  /** Open the code viewer popup (View + Download generated `agent.py`). */
  onViewCode: () => void;
  /** True when an agent id is present (disables Run otherwise). */
  canRun: boolean;
  /** Extra condition that disables the Save button (e.g. missing agent id). */
  saveDisabled: boolean;
  saveMsg: SaveMessage | null;
  statusLabel: string;
  t: LayoutTokens;
  /** Current agent id (enables Export + Delete). */
  agentId: number | null;
  /** Agent display name (used for the export filename + delete confirm). */
  agentName: string;
  /** Called after a .langconfig import succeeds with the imported agent. */
  onImported?: (agent: any) => void;
  /** Called when the user clicks Delete. The caller is responsible for
   *  the two-step confirmation + the actual API call + tab close. */
  onDelete?: () => void;
}

export default function ChatTestToolbar({
  testPrompt,
  onTestPromptChange,
  running,
  onRun,
  onStop,
  saving,
  onSave,
  onViewCode,
  canRun,
  saveDisabled,
  saveMsg,
  statusLabel,
  t,
  agentId,
  agentName,
  onImported,
  onDelete,
}: ChatTestToolbarProps) {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const { activeProjectId } = useProject();

  /** Download the agent as a self-contained .langconfig (v1.1) bundle. */
  const handleExport = async () => {
    if (!agentId) return;
    try {
      const res = await apiClient.exportDeepAgent(agentId);
      const blob = res.data instanceof Blob ? res.data : new Blob([res.data as any]);
      const safeName = (agentName || 'agent').replace(/[^\w\-]+/g, '_');
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `${safeName}.langconfig.json`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch (err: any) {
      console.error('[ChatTestToolbar] Export error:', err);
    }
  };

  /** Import an agent from a .langconfig file (v1.0 / v1.1). Forwards
   *  the active project so the new agent's workspace is project-scoped. */
  const handleImport = async (file: File) => {
    try {
      const text = await file.text();
      const langconfig = JSON.parse(text);
      const res = await apiClient.importDeepAgent(langconfig, {
        projectId: activeProjectId,
      });
      const imported = res?.data ?? res;
      onImported?.(imported);
    } catch (err: any) {
      console.error('[ChatTestToolbar] Import error:', err);
      window.alert(`Import failed: ${err?.response?.data?.detail ?? err?.message ?? 'unknown error'}`);
    } finally {
      if (fileInputRef.current) fileInputRef.current.value = '';
    }
  };

  return (
    <div style={{
      display: 'flex',
      alignItems: 'center',
      gap: 8,
      height: 35,
      minHeight: 35,
      padding: '0 12px',
      background: t.bgTabBar,
      borderBottom: `1px solid ${t.border}`,
      flexShrink: 0,
    }}>
      <span style={{ fontSize: 12, color: t.textMuted }}>Test:</span>
      <input
        value={testPrompt}
        onChange={e => onTestPromptChange(e.target.value)}
        disabled={running}
        placeholder="Type a test message..."
        style={{
          flex: 1,
          maxWidth: 360,
          height: 22,
          padding: '0 8px',
          background: t.bgContent,
          border: `1px solid ${t.border}`,
          borderRadius: 3,
          color: t.textPrimary,
          fontSize: 12,
          outline: 'none',
          opacity: running ? 0.5 : 1,
        }}
      />
      <button
        onClick={onRun}
        disabled={running || !canRun}
        title="Run test"
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 4,
          height: 24,
          padding: '0 10px',
          background: running ? t.bgHover : t.accent,
          color: '#fff',
          border: 'none',
          borderRadius: 3,
          fontSize: 12,
          fontWeight: 500,
          cursor: running || !canRun ? 'not-allowed' : 'pointer',
          opacity: running || !canRun ? 0.6 : 1,
        }}
      >
        {running ? <Loader size={12} style={{ animation: 'spin 1s linear infinite' }} /> : <Play size={12} />}
        {running ? 'Running…' : 'Run'}
      </button>
      {running && (
        <button
          onClick={onStop}
          title="Cancel stream"
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 4,
            height: 24,
            padding: '0 10px',
            background: 'transparent',
            color: t.textPrimary,
            border: `1px solid ${t.border}`,
            borderRadius: 3,
            fontSize: 12,
            cursor: 'pointer',
          }}
        >
          <Square size={10} />
          Stop
        </button>
      )}
      <button
        onClick={onViewCode}
        disabled={!canRun}
        title="View generated agent.py — runnable Python CLI"
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 4,
          height: 24,
          padding: '0 10px',
          background: 'transparent',
          color: t.textPrimary,
          border: `1px solid ${t.border}`,
          borderRadius: 3,
          fontSize: 12,
          cursor: canRun ? 'pointer' : 'not-allowed',
          opacity: canRun ? 1 : 0.6,
        }}
      >
        <Eye size={12} />
        View code
      </button>
      <button
        onClick={handleExport}
        disabled={!agentId}
        title="Download as .langconfig — full config + tools + skills (shareable)"
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 4,
          height: 24,
          padding: '0 10px',
          background: 'transparent',
          color: t.textPrimary,
          border: `1px solid ${t.border}`,
          borderRadius: 3,
          fontSize: 12,
          cursor: agentId ? 'pointer' : 'not-allowed',
          opacity: agentId ? 1 : 0.6,
        }}
      >
        <Download size={12} />
        Export
      </button>
      <button
        onClick={() => fileInputRef.current?.click()}
        title="Import a .langconfig file (agent + tools + skills)"
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 4,
          height: 24,
          padding: '0 10px',
          background: 'transparent',
          color: t.textPrimary,
          border: `1px solid ${t.border}`,
          borderRadius: 3,
          fontSize: 12,
          cursor: 'pointer',
        }}
      >
        <Upload size={12} />
        Import
      </button>
      <input
        ref={fileInputRef}
        type="file"
        accept=".json,.langconfig,application/json"
        style={{ display: 'none' }}
        onChange={e => {
          const file = e.target.files?.[0];
          if (file) handleImport(file);
        }}
      />
      <button
        onClick={onSave}
        disabled={saving || saveDisabled}
        title="Save changes"
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 4,
          height: 24,
          padding: '0 10px',
          background: saving ? t.bgHover : '#2d7d46',
          color: '#fff',
          border: 'none',
          borderRadius: 3,
          fontSize: 12,
          cursor: saving || saveDisabled ? 'not-allowed' : 'pointer',
          opacity: saving || saveDisabled ? 0.6 : 1,
        }}
      >
        <Save size={12} />
        {saving ? 'Saving…' : 'Save'}
      </button>
      {saveMsg && (
        <span style={{
          fontSize: 11,
          color: saveMsg.ok ? '#4caf50' : '#ef5350',
          marginLeft: 4,
        }}>
          {saveMsg.text}
        </span>
      )}

      {/* Destructive action — visually separated from Save so it's not
          clicked by accident. The caller runs the two-step confirm. */}
      {onDelete && (
        <>
          <div style={{ width: 1, height: 16, background: t.border, margin: '0 8px' }} />
          <button
            onClick={onDelete}
            disabled={!agentId}
            title="Delete this agent permanently"
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 4,
              height: 24,
              padding: '0 10px',
              background: 'transparent',
              color: agentId ? '#ef5350' : t.textDim,
              border: `1px solid ${agentId ? '#ef535055' : t.border}`,
              borderRadius: 3,
              fontSize: 12,
              cursor: agentId ? 'pointer' : 'not-allowed',
              opacity: agentId ? 1 : 0.6,
              transition: 'background 0.12s',
            }}
            onMouseEnter={e => { if (agentId) e.currentTarget.style.background = '#ef535018'; }}
            onMouseLeave={e => { e.currentTarget.style.background = 'transparent'; }}
          >
            <Trash2 size={12} />
            Delete
          </button>
        </>
      )}

      <div style={{ flex: 1 }} />
      <span style={{ fontSize: 11, color: t.textDim }}>
        {statusLabel}
      </span>
    </div>
  );
}
