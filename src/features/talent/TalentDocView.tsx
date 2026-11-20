/**
 * TalentDocView — 左边文件树、中间文档编辑器、右边 agent 对话。
 *
 * 形态参照 Knowledge(文档在左、对话在右),但**这一份的三栏是有因果关系的**:
 *
 *   文件树        哪些是客户原文(只读锚点)、哪些是我们派生的(可改)
 *   编辑器        CodeMirror;只读文件连光标都进不去
 *   [保存]        服务端白名单 → 原子写 → 审计 → **立刻跑回检 + 门禁**
 *   校验横幅      `[PASS]` 绿 / `[FAIL]` 红,红的时候把第一条不符的说出来
 *   对话          绑定 Talent · 1 JD 起草(agent 386),显示工具轨迹
 *
 * 为什么"保存即校验"不是可选项:JD 产物是**派生文件**,手改会破坏逐字回查
 * (verbatim 对不上原文)和行号回查。一个只写不验的编辑器就是一台造假的机器 ——
 * 而这条链上已经修过好几次"看起来保存成功、其实是假的"。
 *
 * 只读与可写由**服务端**决定(见 api/talent/routes.py 的 WRITABLE/READONLY),
 * 前端只是照它显示。前端再判断一次等于有两个权威。
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import CodeMirror from '@uiw/react-codemirror';
import { yaml as yamlLang } from '@codemirror/lang-yaml';
import { markdown as markdownLang } from '@codemirror/lang-markdown';
import { json as jsonLang } from '@codemirror/lang-json';
import {
  AlertTriangle, CheckCircle2, FileText, Lock, Loader, Play, Save, Send, Square, Wrench,
} from 'lucide-react';
import { useLayoutTokens } from '../../components/layout2/tokens';
import { useProject } from '../../contexts/ProjectContext';
import {
  getTalentDoc, listTalentDocs, saveTalentDoc, validateTalentJd,
  type DocPayload, type TalentFile, type TalentJd, type ValidationResult,
} from './api';
import { useAgentTurn } from './useAgentTurn';

/** 起草 agent。它的技能就是 talent-jd-draft —— 与文件树里"引用文件"那一层对应。 */
const TALENT_AGENT_ID = 386;

function langFor(path: string) {
  if (path.endsWith('.yaml') || path.endsWith('.yml')) return [yamlLang()];
  if (path.endsWith('.md')) return [markdownLang()];
  if (path.endsWith('.json')) return [jsonLang()];
  return [];
}

export default function TalentDocView() {
  const t = useLayoutTokens();
  const { activeProject } = useProject();
  const projectId = (activeProject as any)?.id ?? 1;

  const [jds, setJds] = useState<TalentJd[]>([]);
  const [jd, setJd] = useState<string>('');
  const [doc, setDoc] = useState<DocPayload | null>(null);
  const [draft, setDraft] = useState<string>('');
  const [busy, setBusy] = useState(false);
  const [saveMsg, setSaveMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [validation, setValidation] = useState<ValidationResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const agent = useAgentTurn(TALENT_AGENT_ID, projectId);
  const [question, setQuestion] = useState('');
  const toolBoxRef = useRef<HTMLDivElement | null>(null);

  const dirty = doc != null && draft !== doc.text;

  // ── 载入 JD 清单 ──
  useEffect(() => {
    listTalentDocs()
      .then((d) => {
        setJds(d.jds || []);
        if (!jd && d.jds?.length) setJd(d.jds[0].jd);
      })
      .catch((e) => setError(String(e.message || e)));
    // 只在挂载时拉一次;jd 由用户切换
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const current = useMemo(() => jds.find((x) => x.jd === jd) || null, [jds, jd]);

  const openFile = useCallback(async (f: TalentFile) => {
    if (!jd) return;
    setError(null);
    setSaveMsg(null);
    try {
      const d = await getTalentDoc(jd, f.path);
      setDoc(d);
      setDraft(d.text);
    } catch (e: any) {
      setError(String(e.message || e));
    }
  }, [jd]);

  // 切 JD 时自动打开第一个存在且可编辑的文件(没有就开第一个存在的)
  useEffect(() => {
    if (!current || doc?.jd === jd) return;
    const first =
      current.files.find((f) => f.exists && f.writable) ||
      current.files.find((f) => f.exists);
    if (first) void openFile(first);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [current]);

  const doSave = useCallback(async () => {
    if (!doc) return;
    setBusy(true);
    setSaveMsg(null);
    try {
      const r = await saveTalentDoc(doc.jd, doc.path, draft, doc.mtime);
      if (!r.saved) {
        setSaveMsg({ ok: true, text: r.reason || '内容没变化' });
      } else {
        setDoc({ ...doc, text: draft });
        setSaveMsg({ ok: true, text: '已保存(留了 .bak,审计已记录)' });
        if (r.validate) setValidation(r.validate);
      }
      // mtime 变了,重新读一次以拿到新的期望值
      const fresh = await getTalentDoc(doc.jd, doc.path);
      setDoc(fresh);
      setDraft(fresh.text);
    } catch (e: any) {
      setSaveMsg({ ok: false, text: String(e.message || e) });
    } finally {
      setBusy(false);
    }
  }, [doc, draft]);

  const doValidate = useCallback(async () => {
    if (!jd) return;
    setBusy(true);
    setError(null);
    try {
      setValidation(await validateTalentJd(jd));
    } catch (e: any) {
      setError(String(e.message || e));
    } finally {
      setBusy(false);
    }
  }, [jd]);

  const ask = useCallback(() => {
    const q = question.trim();
    if (!q) return;
    setQuestion('');
    void agent.ask(q);
  }, [question, agent]);

  useEffect(() => {
    toolBoxRef.current?.scrollTo({ top: toolBoxRef.current.scrollHeight });
  }, [agent.tools.length, agent.answer]);

  const card: React.CSSProperties = {
    background: t.bgContent, border: `1px solid ${t.border}`,
    borderRadius: 6, display: 'flex', flexDirection: 'column', minHeight: 0, overflow: 'hidden',
  };
  const hd: React.CSSProperties = {
    fontSize: 11, fontWeight: 600, letterSpacing: 0.4, textTransform: 'uppercase',
    color: t.textMuted, padding: '8px 10px', borderBottom: `1px solid ${t.border}`,
    display: 'flex', alignItems: 'center', gap: 6, flexShrink: 0,
  };
  const btn = (primary = false): React.CSSProperties => ({
    display: 'inline-flex', alignItems: 'center', gap: 5, fontSize: 12,
    padding: '4px 10px', borderRadius: 4, cursor: busy ? 'not-allowed' : 'pointer',
    border: `1px solid ${primary ? t.accent : t.border}`,
    background: primary ? t.accent : 'transparent',
    color: primary ? '#fff' : t.textPrimary,
    opacity: busy ? 0.6 : 1,
  });

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', minHeight: 0,
                  padding: 10, gap: 8, background: t.bgBase }}>
      {/* 顶部:选 JD + 全局校验 */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexShrink: 0 }}>
        <FileText size={14} style={{ color: t.accent }} />
        <span style={{ fontSize: 13, fontWeight: 600, color: t.textPrimary }}>Talent 文档</span>
        <select
          value={jd}
          onChange={(e) => { setJd(e.target.value); setDoc(null); setDraft(''); setValidation(null); }}
          style={{ fontSize: 12, padding: '3px 6px', borderRadius: 4,
                   border: `1px solid ${t.border}`, background: t.bgContent, color: t.textPrimary }}
        >
          {jds.map((x) => (
            <option key={x.jd} value={x.jd}>{x.jd}({x.existing} 个产物)</option>
          ))}
        </select>
        <button style={btn()} onClick={doValidate} disabled={busy || !jd}>
          <Play size={12} /> 跑校验
        </button>
        {validation && (
          <span style={{ fontSize: 11, color: validation.ok ? '#2f9e44' : '#e5484d',
                         display: 'inline-flex', alignItems: 'center', gap: 4 }}>
            {validation.ok ? <CheckCircle2 size={12} /> : <AlertTriangle size={12} />}
            {validation.ok
              ? `回检 + 门禁通过 · ${validation.gate.summary}`
              : `未通过 · ${validation.gate.summary || '门禁没有汇总行(未跑完)'}`}
          </span>
        )}
        {error && <span style={{ fontSize: 11, color: '#e5484d' }}>{error}</span>}
      </div>

      <div style={{ display: 'flex', gap: 8, flex: 1, minHeight: 0 }}>
        {/* ── 左:文件树 ── */}
        <div style={{ ...card, width: 240, flexShrink: 0 }}>
          <div style={hd}><FileText size={12} /> 产物</div>
          <div style={{ overflow: 'auto', flex: 1, padding: 4 }}>
            {current?.files.filter((f) => f.exists).map((f) => {
              const active = doc?.path === f.path;
              return (
                <button
                  key={f.path}
                  onClick={() => openFile(f)}
                  title={f.writable ? f.note : f.readonly_reason}
                  style={{
                    display: 'block', width: '100%', textAlign: 'left', cursor: 'pointer',
                    padding: '5px 7px', borderRadius: 4, marginBottom: 2,
                    border: `1px solid ${active ? t.accent : 'transparent'}`,
                    background: active ? `${t.accent}18` : 'transparent',
                    color: t.textPrimary, fontSize: 11.5, lineHeight: 1.35,
                  }}
                >
                  <span style={{ opacity: 0.6 }}>{f.layer}</span>
                  <br />
                  <span style={{ wordBreak: 'break-all' }}>{f.path.split('/').pop()}</span>
                  {!f.writable && <Lock size={10} style={{ marginLeft: 4, opacity: 0.7 }} />}
                </button>
              );
            })}
            {current && current.files.every((f) => !f.exists) && (
              <div style={{ fontSize: 11, color: t.textMuted, padding: 8 }}>
                这份 JD 还没有任何产物。
              </div>
            )}
          </div>
        </div>

        {/* ── 中:编辑器 ── */}
        <div style={{ ...card, flex: 1, minWidth: 0 }}>
          <div style={hd}>
            <FileText size={12} />
            <span style={{ textTransform: 'none', letterSpacing: 0, fontSize: 12 }}>
              {doc?.path || '未选择文件'}
            </span>
            {doc && !doc.writable && (
              <span style={{ marginLeft: 'auto', color: '#e5484d', textTransform: 'none' }}>
                <Lock size={11} /> 只读 —— {doc.readonly_reason}
              </span>
            )}
            {dirty && <span style={{ marginLeft: 'auto', color: '#f08c00' }}>● 未保存</span>}
            {doc?.writable && (
              <button
                style={{ ...btn(true), marginLeft: dirty ? 8 : 'auto' }}
                onClick={doSave}
                disabled={busy || !dirty}
              >
                {busy ? <Loader size={12} /> : <Save size={12} />} 保存
              </button>
            )}
          </div>
          {saveMsg && (
            <div style={{ fontSize: 11, padding: '4px 10px',
                          color: saveMsg.ok ? '#2f9e44' : '#e5484d',
                          borderBottom: `1px solid ${t.border}` }}>
              {saveMsg.text}
            </div>
          )}
          {validation && !validation.ok && (
            <div style={{ fontSize: 11, padding: '6px 10px', color: '#e5484d',
                          borderBottom: `1px solid ${t.border}`, maxHeight: 96, overflow: 'auto' }}>
              {[...validation.verify.lines, ...validation.gate.lines]
                .filter((l) => l.includes('❌') || l.includes('[FAIL]') || l.includes('不一致'))
                .slice(0, 6)
                .map((l, i) => <div key={i}>{l}</div>)}
            </div>
          )}
          <div style={{ flex: 1, minHeight: 0, overflow: 'auto' }}>
            {doc ? (
              <CodeMirror
                value={draft}
                height="100%"
                theme="dark"
                extensions={langFor(doc.path)}
                editable={doc.writable}
                onChange={(v) => setDraft(v)}
                basicSetup={{ lineNumbers: true, foldGutter: false, highlightActiveLine: true }}
              />
            ) : (
              <div style={{ padding: 20, fontSize: 12, color: t.textMuted }}>
                从左边选一个文件。
              </div>
            )}
          </div>
        </div>

        {/* ── 右:对话 ── */}
        <div style={{ ...card, width: 380, flexShrink: 0 }}>
          <div style={hd}>
            <Wrench size={12} /> 对话 · agent {TALENT_AGENT_ID}
            {agent.running && <Loader size={11} style={{ marginLeft: 'auto' }} />}
          </div>
          <div ref={toolBoxRef} style={{ flex: 1, minHeight: 0, overflow: 'auto', padding: 8, fontSize: 11.5 }}>
            {agent.tools.length === 0 && !agent.answer && (
              <div style={{ color: t.textMuted }}>
                它的工具调用会显示在这里 —— 看它到底跑了哪条命令,而不是只读它的话。
              </div>
            )}
            {agent.tools.map((tool, i) => (
              <div key={i} style={{ marginBottom: 6, borderLeft: `2px solid ${t.accent}55`, paddingLeft: 6 }}>
                <div style={{ fontSize: 10.5, color: t.accent, fontFamily: 'monospace' }}>{tool.name}</div>
                <div style={{ color: t.textMuted, fontFamily: 'monospace', fontSize: 10.5,
                              whiteSpace: 'pre-wrap', wordBreak: 'break-all' }}>
                  {JSON.stringify(tool.input).slice(0, 240)}
                </div>
                {tool.output && (
                  <div style={{ color: t.textPrimary, opacity: 0.75, fontFamily: 'monospace',
                                fontSize: 10.5, whiteSpace: 'pre-wrap', maxHeight: 90, overflow: 'auto' }}>
                    {tool.output.slice(0, 400)}
                  </div>
                )}
              </div>
            ))}
            {agent.answer && (
              <div style={{ marginTop: 8, paddingTop: 8, borderTop: `1px solid ${t.border}`,
                            whiteSpace: 'pre-wrap', color: t.textPrimary }}>
                {agent.answer}
              </div>
            )}
            {agent.error && (
              <div style={{ color: '#e5484d', marginTop: 8 }}>{agent.error}</div>
            )}
          </div>
          <div style={{ borderTop: `1px solid ${t.border}`, padding: 6, display: 'flex', gap: 6 }}>
            <textarea
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); ask(); }
              }}
              placeholder={jd ? `问 agent 关于「${jd}」的事…` : '先选一份 JD'}
              rows={2}
              style={{ flex: 1, resize: 'none', fontSize: 12, padding: 6, borderRadius: 4,
                       border: `1px solid ${t.border}`, background: t.bgInput,
                       color: t.textPrimary }}
            />
            {agent.running ? (
              <button style={btn()} onClick={agent.cancel}><Square size={12} /></button>
            ) : (
              <button style={btn(true)} onClick={ask} disabled={!question.trim()}>
                <Send size={12} />
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
