/**
 * ChatTestToolbar — top action bar (test input + Run/Stop/Save) shared by
 * the agent editors.
 *
 * Extracted from AgentEditor / DeepAgentEditor. The two behavioural
 * differences between the editors are passed as props:
 *   - saveDisabled  : AgentEditor -> saving, DeepAgentEditor -> saving || !id
 *   - statusLabel   : pre-formatted right-hand status line
 */
import type { LayoutTokens } from './tokens';
import { Loader, Play, Square, Save, FileCode2 } from 'lucide-react';

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
  /** Download the generated runnable Python CLI (`agent.py`). */
  onExport: () => void;
  /** True when an agent id is present (disables Run otherwise). */
  canRun: boolean;
  /** Extra condition that disables the Save button (e.g. missing agent id). */
  saveDisabled: boolean;
  saveMsg: SaveMessage | null;
  statusLabel: string;
  t: LayoutTokens;
}

export default function ChatTestToolbar({
  testPrompt,
  onTestPromptChange,
  running,
  onRun,
  onStop,
  saving,
  onSave,
  onExport,
  canRun,
  saveDisabled,
  saveMsg,
  statusLabel,
  t,
}: ChatTestToolbarProps) {
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
        onClick={onExport}
        disabled={!canRun}
        title="Download agent.py — runnable Python CLI"
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
        <FileCode2 size={12} />
        Export .py
      </button>
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
      <div style={{ flex: 1 }} />
      <span style={{ fontSize: 11, color: t.textDim }}>
        {statusLabel}
      </span>
    </div>
  );
}
