/**
 * Semantic view — the third representation of a Studio run, next to Flow and Schema.
 *
 *   Flow      what the graph does (nodes, edges)
 *   Schema    what the database looks like (tables, columns)
 *   Semantic  what the graph MEANS by those columns (the rules injected into the
 *             SQL prompts)
 *
 * This is the only editable view, and the only one whose content changes the
 * answer rather than the picture: `load_semantics` reads this file on every run,
 * so a save applies to the next run without a restart.
 *
 * The header line that matters most is the block chips. The loader splits the file
 * on `## Section` headings and injects only what it recognises; a file whose
 * headings it cannot classify injects NOTHING and the model silently loses every
 * rule. Measured once: a rewrite using `###` headings emptied all three blocks and
 * nothing anywhere reported it. So the chips show what will actually be injected,
 * and the API refuses to save a file with no recognised section.
 */
import { useEffect } from 'react';
import { Save, ShieldCheck, Loader2, AlertTriangle, FileText, Check, X } from 'lucide-react';
import { useLayoutTokens } from '../../components/layout2/tokens';
import { studio, useStudioState } from './studioStore';

const BLOCK_LABEL: Record<string, string> = {
  schema: 'schema（表名/join）',
  semantic: 'semantic（口径规则）',
  examples: 'examples（示例 SQL）',
};

export default function SemanticsEditor() {
  const t = useLayoutTokens();
  const { semantics, activeSqlDatabase } = useStudioState();

  // Load on first entry, and again when the database target changes — the file is
  // chosen by the active database, so switching DB must switch the document.
  useEffect(() => {
    if (!semantics || semantics.database !== activeSqlDatabase || !semantics.path) {
      void studio.loadSemantics();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeSqlDatabase]);

  const s = semantics;
  if (!s || s.loading) {
    return (
      <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', color: t.textMuted, fontSize: 12 }}>
        <Loader2 size={14} style={{ animation: 'spin 1s linear infinite', marginRight: 6 }} />
        loading SEMANTICS.md…
      </div>
    );
  }

  const gateOk = s.check?.status === 'pass';
  const gateFail = s.check?.status === 'fail';

  return (
    <div style={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column', background: t.bgContent }}>
      {/* Header: which file, how big, which blocks the loader will inject */}
      <div style={{
        display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap',
        padding: '8px 12px', borderBottom: `1px solid ${t.border}`, background: t.bgTabBar,
      }}>
        <FileText size={13} color={t.accent} />
        <span style={{ fontSize: 12, fontWeight: 600, color: t.textPrimary }}>
          SEMANTICS.md · {s.database}
        </span>
        <span style={{ fontSize: 10.5, color: t.textDim, fontFamily: 'monospace' }}>
          {(s.bytes / 1024).toFixed(1)} KB
        </span>

        <span style={{ display: 'flex', gap: 4, marginLeft: 6 }}>
          {['schema', 'semantic', 'examples'].map(b => {
            const on = s.blocks.includes(b);
            return (
              <span
                key={b}
                title={on ? `${BLOCK_LABEL[b]} —— 会被注入` : `${BLOCK_LABEL[b]} —— 缺失，不会被注入`}
                style={{
                  fontSize: 9.5, padding: '1px 6px', borderRadius: 3,
                  border: `1px solid ${on ? t.accent : t.border}`,
                  color: on ? t.accent : t.textDim,
                  background: on ? `${t.accent}12` : 'transparent',
                }}
              >
                {b} {on ? '✓' : '✗'}
              </span>
            );
          })}
        </span>

        <div style={{ marginLeft: 'auto', display: 'flex', gap: 6 }}>
          <button
            onClick={() => void studio.checkSemantics()}
            disabled={s.saving}
            title={s.checker ? `运行 ${s.checker}` : '该库没有校验脚本'}
            style={btn(t, false, s.saving)}
          >
            <ShieldCheck size={11} /> 校验
          </button>
          <button
            onClick={() => void studio.saveSemantics()}
            disabled={s.saving || !s.dirty}
            title={s.dirty ? '保存并对该库运行校验' : '没有改动'}
            style={btn(t, true, s.saving || !s.dirty)}
          >
            {s.saving ? <Loader2 size={11} style={{ animation: 'spin 1s linear infinite' }} /> : <Save size={11} />}
            保存并校验
          </button>
          {/* Close → back to the graph. Only stop the user when there are unsaved
              edits; the toggle can switch back silently anyway. */}
          <button
            onClick={() => {
              if (s.dirty && !window.confirm('有未保存的修改，关闭后丢弃。继续？')) return;
              studio.setViewMode('flow');
            }}
            title="关闭（返回 Flow）"
            style={{
              display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
              width: 24, height: 24, borderRadius: 4, cursor: 'pointer',
              background: 'transparent', color: t.textMuted,
              border: `1px solid ${t.border}`,
            }}
          >
            <X size={12} />
          </button>
        </div>
      </div>

      {/* Status line */}
      {(s.message || s.check) && (
        <div style={{
          padding: '6px 12px', fontSize: 11, borderBottom: `1px solid ${t.border}`,
          background: gateFail ? '#e5484d12' : gateOk ? '#4caf5012' : t.bgSidebar,
          color: gateFail ? '#e5484d' : gateOk ? '#2e7d32' : t.textMuted,
          display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap',
        }}>
          {gateFail ? <AlertTriangle size={11} /> : gateOk ? <Check size={11} /> : null}
          <span>{s.message}</span>
          {s.check?.lines?.length ? (
            <code style={{ fontSize: 10, whiteSpace: 'pre-wrap', color: 'inherit', opacity: 0.85 }}>
              {s.check.lines.slice(-4).join(' · ')}
            </code>
          ) : null}
        </div>
      )}

      {/* The document */}
      <div style={{ flex: 1, minHeight: 0, padding: 10, display: 'flex' }}>
        <textarea
          value={s.text}
          onChange={e => studio.setSemanticsText(e.target.value)}
          spellCheck={false}
          style={{
            flex: 1, width: '100%', resize: 'none', outline: 'none',
            background: t.bgSidebar, color: t.textPrimary,
            border: `1px solid ${t.border}`, borderRadius: 6, padding: 12,
            fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace',
            fontSize: 12, lineHeight: 1.6, tabSize: 2,
          }}
        />
      </div>

      <div style={{ padding: '4px 12px 8px', fontSize: 10, color: t.textDim }}>
        {s.path || '(no file yet)'}
        {s.dirty && <span style={{ color: t.accentMuted }}> · 未保存</span>}
        {s.checker
          ? <> · 保存时会运行 <code>{s.checker.split('/').pop()}</code></>
          : <> · 该库没有校验脚本，保存后不会有数字比对</>}
        {' '}· 保存即生效（下一次运行读取新文件）
      </div>
    </div>
  );
}

function btn(t: ReturnType<typeof useLayoutTokens>, primary: boolean, disabled: boolean): React.CSSProperties {
  return {
    display: 'inline-flex', alignItems: 'center', gap: 4,
    height: 24, padding: '0 9px', borderRadius: 4, fontSize: 11,
    cursor: disabled ? 'not-allowed' : 'pointer', opacity: disabled ? 0.5 : 1,
    background: primary ? t.accent : 'transparent',
    color: primary ? '#fff' : t.textPrimary,
    border: `1px solid ${primary ? t.accent : t.border}`,
  };
}
