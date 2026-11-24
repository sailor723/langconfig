/**
 * TalentDocView — 中间是文档编辑器，右边是 agent 对话。
 *
 * **文件浏览器不在这里**：它在左轨（features/talent/TalentSidebar.tsx），和 Analysis 列
 * dashboard、Knowledge 列来源、Ontology 列本体是同一个分工 —— 列表在轨上，页面在中间。
 * 这里只管"当前这一份"：编辑器 + 保存即校验 + 问 agent。
 *
 * 当前打开的是哪一份，唯一来源是 **tab.data**（`{ jd, path }`，由 TalentSidebar 写）。
 * 组件自己不存一个"选中的文件"，否则就有两个真相，切 tab 时会互相打架。
 *
 * 为什么"保存即校验"不是可选项：JD 产物是**派生文件**，手改会破坏逐字回查
 * （verbatim 对不上原文）和行号回查。一个只写不验的编辑器就是一台造假的机器 ——
 * 而这条链上已经修过好几次"看起来保存成功、其实是假的"。
 *
 * 只读与可写由**服务端**决定（见 api/talent/routes.py 的 WRITABLE/READONLY），
 * 前端只是照它显示。前端再判断一次等于有两个权威。
 */
import { Component, Suspense, lazy, useCallback, useEffect, useRef, useState, type ReactNode } from 'react';
import CodeMirror from '@uiw/react-codemirror';
import { yaml as yamlLang } from '@codemirror/lang-yaml';
import { markdown as markdownLang } from '@codemirror/lang-markdown';
import { json as jsonLang } from '@codemirror/lang-json';
import {
  AlertTriangle, CheckCircle2, FileText, Lock, Loader, Play, Save, Send, Square, Wrench,
} from 'lucide-react';
import { useLayoutTokens, type LayoutTokens } from '../../components/layout2/tokens';
import { useProject } from '../../contexts/ProjectContext';
import MarkdownBody from '../../components/layout2/MarkdownBody';
import CollapsibleMarkdown from './CollapsibleMarkdown';
import TalentCatalog from './TalentCatalog';
import TalentGap from './TalentGap';
import StructuredBody from '../../components/layout2/StructuredBody';
import type { Tab } from '../../components/layout2/useLayout';
import {
  getTalentDoc, getAgentFile, listTalentAgents, runTalentStep, saveTalentDoc, validateTalentJd,
  type DocPayload, type RunStepResult, type TalentAgent, type ValidationResult,
} from './api';
import { useAgentTurn } from './useAgentTurn';
import { useTalentAgentId } from './currentAgent';
import { extOf, fileKind } from '../../components/layout2/fileKinds';
import PdfViewer from '../../components/layout2/PdfViewer';

// OfficeViewer 拉进 docx-preview + pptxviewjs(~1MB),只在真要打开时加载。
const OfficeViewer = lazy(() => import('../../components/layout2/OfficeViewer'));

/** 对外只有这一个出口：边界包住，保证崩溃可见。`tab` 由 Workspace 注入。 */
export default function TalentDocView(props: { tab?: Tab }) {
  return (
    <TalentErrorBoundary>
      <TalentDocViewInner tab={props.tab} />
    </TalentErrorBoundary>
  );
}

function langFor(path: string) {
  if (path.endsWith('.yaml') || path.endsWith('.yml')) return [yamlLang()];
  if (path.endsWith('.md')) return [markdownLang()];
  if (path.endsWith('.json')) return [jsonLang()];
  return [];
}

/** 哪些产物"能读"：`.md` 是散文，`.yaml/.json` 是结构化数据。两类都默认渲染，源码只在要改时出来。 */
function isMarkdownPath(path: string): boolean {
  return /\.(md|markdown)$/i.test(path);
}

function dataFormat(path: string): 'yaml' | 'json' | null {
  if (/\.json$/i.test(path)) return 'json';
  if (/\.ya?ml$/i.test(path)) return 'yaml';
  return null;
}

type EditorMode = 'preview' | 'source';

// ── 对话栏宽度 ──────────────────────────────────────────────
// 三块之间两条边都要能拖:左轨 ↔ 编辑器那道边由 LeftSidebar 自己提供(它已经有拖拽),
// 这里补中间那道(编辑器 ↔ 对话)。
const CHAT_MIN_WIDTH = 300;
const CHAT_MAX_WIDTH = 760;
const CHAT_DEFAULT_WIDTH = 380;
/** 拖到最宽时也要给编辑器留够:否则窗口一小,编辑器被挤成 0 宽 —— 看起来像"文档没了"。 */
const CHAT_RESERVED_FOR_EDITOR = 360;
const CHAT_WIDTH_KEY = 'talent.chatWidth';

function readStoredChatWidth(): number {
  try {
    const raw = Number(window.localStorage.getItem(CHAT_WIDTH_KEY));
    if (Number.isFinite(raw) && raw >= CHAT_MIN_WIDTH && raw <= CHAT_MAX_WIDTH) return raw;
  } catch {
    /* 隐私模式读不到 localStorage —— 退回默认值,不许因此把整个视图搞崩 */
  }
  return CHAT_DEFAULT_WIDTH;
}

/** 渲染抛错时把错误显示在栏内。没有它，一个 undefined 之类的错会让整块**静默消失**，
 *  而界面上看不出是"崩了"还是"没数据" —— 这正是排查空页面时卡住的原因。 */
class TalentErrorBoundary extends Component<{ children: ReactNode }, { err: Error | null }> {
  constructor(props: { children: ReactNode }) {
    super(props);
    this.state = { err: null };
  }
  static getDerivedStateFromError(err: Error) {
    return { err };
  }
  componentDidCatch(err: Error) {
    // eslint-disable-next-line no-console
    console.error('[talent] 视图渲染失败', err);
  }
  render() {
    if (this.state.err) {
      return (
        <div style={{ padding: 16, fontSize: 12, color: '#e5484d', fontFamily: 'monospace',
                      whiteSpace: 'pre-wrap', overflow: 'auto', height: '100%' }}>
          <div style={{ fontWeight: 700, marginBottom: 8 }}>Talent 视图渲染失败</div>
          {String(this.state.err?.message || this.state.err)}
          {'\n\n'}
          {String(this.state.err?.stack || '').split('\n').slice(0, 8).join('\n')}
        </div>
      );
    }
    return this.props.children;
  }
}

/**
 * AgentAsset — 有格式的文件(pdf/docx/pptx/图片/html)。
 *
 * 为什么不转文本:这些文件的价值就在版式。转成文本等于把它们降级成一堆没对齐的字,
 * 而"我上传的那份职务说明书长什么样"本身就是要看的东西。
 * 用共享的 `fileKinds` 判定,和左轨、Knowledge 是同一套扩展名表 —— 一处改,处处一致。
 */
function AssetView({ asset, tokens: t }: {
  asset: { url: string; name: string; ext: string;
           viewer?: 'pdf' | 'office' | 'image' | 'html' | 'other';
           convertedFrom?: string };
  tokens: LayoutTokens;
}) {
  // 服务端判好的优先 —— 尤其是 `.doc`:它已经被转成 `.docx` 发过来了,
  // 按扩展名猜会猜成 legacy(没有查看器),而它其实能正常渲染。
  const kind = asset.viewer ?? fileKind(asset.name);
  const center: React.CSSProperties = {
    flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center',
    overflow: 'auto', padding: 16, fontSize: 12, color: t.textMuted,
  };

  if (kind === 'pdf') return <PdfViewer url={asset.url} />;

  if (kind === 'office') {
    return (
      <>
        {/* 说清楚这是转换后的样子:老 .doc 的版式由 textutil/soffice 转成 OOXML 再生效,
            和 Word 里打开原文件可能仍有细微差别。不说,读者会以为这就是原样的像素。 */}
        {asset.convertedFrom && (
          <div style={{ padding: '6px 12px', fontSize: 11, color: t.textMuted, flexShrink: 0,
                        borderBottom: `1px solid ${t.border}`, background: t.bgBase }}>
            {asset.convertedFrom} 不是浏览器能直接打开的老格式 —— 已转成 .docx 显示,
            版式可能与原文件有细微差别(原文件未改动)。
          </div>
        )}
        <Suspense fallback={<div style={center}>正在加载 Office 查看器…</div>}>
          <OfficeViewer
            url={asset.url}
            fileName={asset.name}
            ext={asset.convertedFrom ? 'docx' : (extOf(asset.name) as 'docx' | 'pptx')}
          />
        </Suspense>
      </>
    );
  }

  if (kind === 'image') {
    return (
      <div style={center}>
        <img src={asset.url} alt={asset.name}
             style={{ maxWidth: '100%', maxHeight: '100%', objectFit: 'contain' }} />
      </div>
    );
  }

  if (kind === 'html') {
    return <iframe src={asset.url} title={asset.name}
                   style={{ width: '100%', height: '100%', border: 'none', background: '#fff' }} />;
  }

  return (
    <div style={center}>
      这个格式没有内置查看器。
      <a href={asset.url} target="_blank" rel="noreferrer" style={{ color: t.accent, marginLeft: 6 }}>
        在新标签打开
      </a>
    </div>
  );
}

function TalentDocViewInner({ tab }: { tab?: Tab }) {
  const t = useLayoutTokens();
  const { activeProject } = useProject();
  const projectId = (activeProject as any)?.id ?? 1;

  // 选中项来自 tab.data —— 见文件头。没有 tab（或 tab 还没选文件）就是"空编辑器"。
  //
  // 两种来源共用这一个视图,是刻意的:
  //   { jd, path }                    仓库里的产物 work/talent/**,可写,保存要过回检 + 门禁
  //   { agentId, agentPath }          agent 工作区 generated/** 里它自己写的东西,**只读**
  // 分成两个视图的代价实测过:打开 agent 的报告,中间换成另一屏,右边对话栏整个消失 ——
  // 而"一边看它写了什么、一边继续问它"正是这两样东西被放在一起的理由。
  const sel = (tab?.data ?? {}) as {
    jd?: string; path?: string; agentId?: number; agentPath?: string;
  };
  const isAgent = Boolean(sel.agentId && sel.agentPath);
  const jd = isAgent ? '' : (sel.jd ?? '');
  const path = isAgent ? (sel.agentPath ?? '') : (sel.path ?? '');

  const [doc, setDoc] = useState<DocPayload | null>(null);
  const [draft, setDraft] = useState<string>('');
  const [busy, setBusy] = useState(false);
  const [saveMsg, setSaveMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [validation, setValidation] = useState<ValidationResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  // 空着的时候得能看出是"还在读"、"读失败"、还是"真没选文件" —— 否则只能靠猜。
  const [loadingDoc, setLoadingDoc] = useState(false);
  // 有格式的 agent 文件(pdf/docx/pptx/图片/html)没法变成文本,只能把 URL 交给浏览器查看器。
  // 和文本走同一个视图、同一个对话栏 —— 只换中间那块。
  const [agentAsset, setAgentAsset] = useState<{
    url: string; name: string; ext: string;
    viewer?: 'pdf' | 'office' | 'image' | 'html' | 'other';
    convertedFrom?: string;
  } | null>(null);
  // `.md` / `.yaml` / `.json` 默认渲染(和 Knowledge 看文档一样),要改的时候切到源码 ——
  // 不这么做的话,渲染稿是只读的,「保存」永远等不到 dirty,等于把写这条路关掉了。
  const isMd = isMarkdownPath(path);
  const dataFmt = dataFormat(path);
  const readable = isMd || dataFmt != null;
  const [mode, setMode] = useState<EditorMode>('source');

  // CV 弹层。站内链接 `#tal:cv/<candidate id>` 点一下就打开这份人的定稿全文 ——
  // 名单表格只放"要不要点开"的信息,31 个字段的全文放在这里。
  const [cvPanel, setCvPanel] = useState<{
    cid: string; path: string; text: string; loading: boolean; error?: string;
  } | null>(null);

  const openCvLink = useCallback(async (href: string) => {
    const m = /^#tal:cv\/(.+)$/.exec(href);
    if (!m) return;
    const cid = decodeURIComponent(m[1]);
    const rel = `cv_docs/${cid.replace(/^cand_/, '')}.定稿.md`;
    setCvPanel({ cid, path: rel, text: '', loading: true });
    try {
      const d = await getTalentDoc(jd, rel);
      const text = (d as DocPayload)?.text ?? '';
      setCvPanel({ cid, path: rel, text, loading: false });
    } catch (e: any) {
      setCvPanel({ cid, path: rel, text: '', loading: false,
                   error: e?.message || '读不到这份定稿' });
    }
  }, [jd]);

  // Esc 关弹层
  useEffect(() => {
    if (!cvPanel) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setCvPanel(null); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [cvPanel]);

  // 换文件就回到它的默认视图。放在这里而不是渲染时判断,是因为用户可能在上一个文件
  // 里选了源码模式;那个选择不该跟到下一份文件上。
  useEffect(() => {
    setMode(isMarkdownPath(path) || dataFormat(path) ? 'preview' : 'source');
  }, [path]);

  // 用哪一步的 agent 由用户选(对话栏顶部),默认是起草 agent。四个东西共用这一处状态:
  // 对话栏、左轨的 agent 产物段、localStorage、以及刷新后的恢复。
  const [agentId, setAgentId] = useTalentAgentId();
  const [agents, setAgents] = useState<TalentAgent[]>([]);
  useEffect(() => {
    // 清单拉不到就退回只有当前这一个 —— 下拉框不该因为列表接口失败而变成空的。
    listTalentAgents()
      .then((list) => setAgents(list))
      .catch(() => setAgents([]));
  }, []);
  const agent = useAgentTurn(agentId, projectId);
  const [question, setQuestion] = useState('');
  const toolBoxRef = useRef<HTMLDivElement | null>(null);

  // ── 编辑器 ↔ 对话 的拖拽 ──
  // 做法和 LeftSidebar 完全一致(document 级 mousemove,手柄只是起点),这样指针
  // 甩出那条 8px 的细柄也不会断;双击复位默认宽度。
  const rootRef = useRef<HTMLDivElement | null>(null);
  const [chatWidth, setChatWidth] = useState<number>(readStoredChatWidth);
  const [draggingChat, setDraggingChat] = useState(false);
  const chatDragRef = useRef<{ startX: number; startWidth: number } | null>(null);

  useEffect(() => {
    try { window.localStorage.setItem(CHAT_WIDTH_KEY, String(Math.round(chatWidth))); } catch { /* 存不下不是错误 */ }
  }, [chatWidth]);

  const onChatDragStart = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    chatDragRef.current = { startX: e.clientX, startWidth: chatWidth };
    setDraggingChat(true);
    const move = (ev: MouseEvent) => {
      if (!chatDragRef.current) return;
      const dx = ev.clientX - chatDragRef.current.startX;
      // 往**左**拖 = 对话变宽,所以是减 dx
      const room = rootRef.current ? rootRef.current.clientWidth - CHAT_RESERVED_FOR_EDITOR : CHAT_MAX_WIDTH;
      const max = Math.max(CHAT_MIN_WIDTH, Math.min(CHAT_MAX_WIDTH, room));
      setChatWidth(Math.max(CHAT_MIN_WIDTH, Math.min(max, chatDragRef.current.startWidth - dx)));
    };
    const up = () => {
      chatDragRef.current = null;
      setDraggingChat(false);
      document.removeEventListener('mousemove', move);
      document.removeEventListener('mouseup', up);
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
    };
    document.addEventListener('mousemove', move);
    document.addEventListener('mouseup', up);
    document.body.style.cursor = 'ew-resize';
    document.body.style.userSelect = 'none';
  }, [chatWidth]);


  const dirty = doc != null && draft !== doc.text;

  /** `@` 前缀 = 面板型产物（不落盘、不读文件）。目前只有 `@gap`：这份 JD 的 40 格缺口。 */
  const isPanel = Boolean(path && path.startsWith('@'));

  // ── 打开文件：换 tab 就是在换文件，所以依赖只认来源 + 路径 ──
  useEffect(() => {
    if (isPanel) {
      setLoadingDoc(false);
      setDoc(null);
      return;
    }
    if (!path) {
      setDoc(null);
      setDraft('');
      setAgentAsset(null);
      setValidation(null);
      setSaveMsg(null);
      setError(null);
      return;
    }
    let dead = false;
    setLoadingDoc(true);
    setError(null);
    setValidation(null);
    setSaveMsg(null);
    setAgentAsset(null);

    const reading = isAgent
      ? getAgentFile(sel.agentId as number, path, projectId).then((r) => {
          if (r.kind === 'binary') {
            // 有格式的文件:交给查看器,不进 doc(它不是文本)
            setAgentAsset({ url: r.url, name: r.name, ext: r.ext,
                            viewer: r.viewer, convertedFrom: r.converted_from });
            return null;
          }
          setAgentAsset(null);
          return {
            kind: 'text' as const,
            path: r.path,
            jd: '',
            text: r.text,
            bytes: r.bytes,
            mtime: r.mtime,
            writable: false,
            // 老式 .doc 是**抽出来的文本**:版式、图片、表格全没了,必须说清楚,
            // 否则有人会以为这就是原文件的样子。
            readonly_reason: r.kind === 'converted'
              ? `由 ${r.ext} 抽取的纯文本(${r.converter})—— 原格式与版式不保留`
              : 'agent 产物(意见,不是正式产物):要成为产物得由人抬进 jd_docs/',
          };
        })
      : getTalentDoc(jd, path).then((r) => {
          if (r.kind === 'binary') {
            // docx/pdf/图片:和 agent 文件走同一个查看器,不进 doc
            setAgentAsset({ url: r.url, name: r.name, ext: r.ext,
                            viewer: r.viewer, convertedFrom: undefined });
            return null;
          }
          return r;
        });

    reading
      .then((d) => {
        // null = 有格式的文件,已经交给查看器;只有文本才进 doc
        if (dead || d === null || d.kind !== 'text') return;
        setDoc(d);
        setDraft(d.text);
      })
      .catch((e: any) => {
        if (!dead) setError(String(e?.message || e));
      })
      .finally(() => {
        if (!dead) setLoadingDoc(false);
      });
    return () => { dead = true; };
  }, [jd, path, isAgent, projectId, sel.agentId]);

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
        setSaveMsg({ ok: true, text: '已保存（留了 .bak，审计已记录）' });
        if (r.validate) setValidation(r.validate);
      }
      // mtime 变了，重新读一次以拿到新的期望值
      const fresh = await getTalentDoc(doc.jd, doc.path);
      if (fresh.kind === 'text') {
        setDoc(fresh);
        setDraft(fresh.text);
      }
    } catch (e: any) {
      setSaveMsg({ ok: false, text: String(e.message || e) });
    } finally {
      setBusy(false);
    }
  }, [doc, draft]);

  // 跑第 5 步:名单 → 选人 → 判定说明 → CV 清单 → 门禁,一条命令串起来。
  // **跑完必须重读当前文档** —— 产物被覆盖了,不刷新就还在看旧内容。
  const [running, setRunning] = useState<string | null>(null);
  const [runResult, setRunResult] = useState<RunStepResult | null>(null);

  const doRunStep = useCallback(async (step: string) => {
    if (!jd) return;
    setRunning(step);
    setError(null);
    setRunResult(null);
    try {
      const r = await runTalentStep(jd, step);
      setRunResult(r);
      // 重读当前文件:跑完第 5 步后,打开着的名单/选人已经是新内容了
      if (path) {
        try {
          const d = await getTalentDoc(jd, path);
          const text = (d as DocPayload)?.text ?? '';
          setDoc(d as DocPayload);
          setDraft(text);
        } catch { /* 当前文件可能已被这一步删掉/改名,读不到不算失败 */ }
      }
    } catch (e: any) {
      setError(String(e.message || e));
    } finally {
      setRunning(null);
    }
  }, [jd, path]);

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
    /* flex:1 + minHeight:0 而不是 height:100%：后者要求父级有确定高度，
       在 flex 容器里某些组合会解析成 0 —— 表现就是整块空白且不报错。 */
    /* gap 交给中间那道手柄:卡片之间不再靠 gap 分开,而是靠手柄那 8px ——
       这样两条边(左轨 / 中间)的视觉宽度一致,不会出现一边挤一边松。 */
    <div ref={rootRef} style={{ display: 'flex', gap: 0, flex: 1, minHeight: 0, padding: 10, background: t.bgBase }}>

      {/* ── 编辑器 ── */}
      <div style={{ ...card, flex: 1, minWidth: 0 }}>
        <div style={hd}>
          <FileText size={12} />
          <span style={{ textTransform: 'none', letterSpacing: 0, fontSize: 12, minWidth: 0,
                         overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {path || '未选择文件'}
          </span>
          {/* 右侧统一成一组:原先三个元素各自 marginLeft:'auto',谁先谁后靠顺序决定,
              多一个控件就会把它们摊开 —— 一组里放,位置才稳定。 */}
          <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 6, flexShrink: 0 }}>
            {doc && !doc.writable && (
              <span style={{ color: '#e5484d', textTransform: 'none', maxWidth: 320,
                             overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
                    title={doc.readonly_reason}>
                <Lock size={11} /> 只读 —— {doc.readonly_reason}
              </span>
            )}
            {dirty && <span style={{ color: '#f08c00', textTransform: 'none' }}>● 未保存</span>}
            {readable && (
              <div style={{ display: 'flex', border: `1px solid ${t.border}`, borderRadius: 4, overflow: 'hidden' }}>
                {(['preview', 'source'] as const).map((m) => (
                  <button
                    key={m}
                    onClick={() => setMode(m)}
                    title={m === 'preview'
                      ? (dataFmt ? '结构化视图 —— 读的是同一份 draft，改完能直接切回来看'
                                 : '渲染后的文档（和 Knowledge 一样）')
                      : '改内容 —— 保存仍会跑回检 + 门禁'}
                    style={{
                      fontSize: 11, padding: '3px 9px', border: 'none', cursor: 'pointer',
                      background: mode === m ? t.accent : 'transparent',
                      color: mode === m ? '#fff' : t.textMuted,
                    }}
                  >
                    {m === 'preview' ? (dataFmt ? '结构' : '预览') : '源码'}
                  </button>
                ))}
              </div>
            )}
            {/* agent 产物不属于任何 JD 的正式产物,给它一个"跑校验"按钮只会误导 —— 藏起来。 */}
            {!isAgent && (
              <>
                <button
                  style={btn()}
                  onClick={() => doRunStep('5')}
                  disabled={busy || !jd || running !== null}
                  title="短名单 → 最终名单 → 选人 → 判定说明 → CV 清单 → 门禁,一次跑完"
                >
                  {running === '5' ? <Loader size={12} /> : <Wrench size={12} />}
                  {running === '5' ? '跑第 5 步…' : '跑第 5 步'}
                </button>
                <button style={btn()} onClick={doValidate} disabled={busy || !jd}>
                  <Play size={12} /> 跑校验
                </button>
              </>
            )}
            {doc?.writable && (
              <button style={btn(true)} onClick={doSave} disabled={busy || !dirty}>
                {busy ? <Loader size={12} /> : <Save size={12} />} 保存
              </button>
            )}
          </div>
        </div>

        {validation && (
          <div style={{ fontSize: 11, padding: '4px 10px',
                        color: validation.ok ? '#2f9e44' : '#e5484d',
                        borderBottom: `1px solid ${t.border}`,
                        display: 'flex', alignItems: 'center', gap: 4, flexShrink: 0 }}>
            {validation.ok ? <CheckCircle2 size={12} /> : <AlertTriangle size={12} />}
            {validation.ok
              ? `回检 + 门禁通过 · ${validation.gate.summary}`
              : `未通过 · ${validation.gate.summary || '门禁没有汇总行（未跑完）'}`}
          </div>
        )}

        {runResult && (
          <div style={{
            fontSize: 11, padding: '6px 10px', flexShrink: 0,
            borderBottom: `1px solid ${t.border}`,
            background: runResult.ok ? 'rgba(47,158,68,.10)' : 'rgba(229,72,77,.10)',
            maxHeight: 132, overflow: 'auto',
          }}>
            <div style={{ color: runResult.ok ? '#2f9e44' : '#e5484d', marginBottom: 3 }}>
              {runResult.ok ? '✓' : '✗'} 第 {runResult.step} 步跑完 · 用时 {runResult.seconds}s
              {runResult.gate ? ` · ${runResult.gate}` : ''}
            </div>
            {runResult.steps.map((s2, i) => (
              <div key={i} style={{ color: s2.status === 'pass' ? t.textMuted : '#e5484d' }}>
                {s2.status === 'pass' ? '✓' : s2.status === 'skip' ? '⤼' : '✗'} {s2.module}
                {s2.status !== 'pass' && (s2.lines || []).slice(-2).map((ln, j) => (
                  <div key={j} style={{ paddingLeft: 14, color: t.textMuted }}>{ln}</div>
                ))}
              </div>
            ))}
          </div>
        )}

        {saveMsg && (
          <div style={{ fontSize: 11, padding: '4px 10px', flexShrink: 0,
                        color: saveMsg.ok ? '#2f9e44' : '#e5484d',
                        borderBottom: `1px solid ${t.border}` }}>
            {saveMsg.text}
          </div>
        )}

        {error && (
          <div style={{ fontSize: 11, padding: '4px 10px', color: '#e5484d', flexShrink: 0,
                        borderBottom: `1px solid ${t.border}`, whiteSpace: 'pre-wrap' }}>
            {error}
          </div>
        )}

        {validation && !validation.ok && (
          <div style={{ fontSize: 11, padding: '6px 10px', color: '#e5484d', flexShrink: 0,
                        borderBottom: `1px solid ${t.border}`, maxHeight: 96, overflow: 'auto' }}>
            {[...validation.verify.lines, ...validation.gate.lines]
              .filter((l) => l.includes('❌') || l.includes('[FAIL]') || l.includes('不一致'))
              .slice(0, 6)
              .map((l, i) => <div key={i}>{l}</div>)}
          </div>
        )}

        {path === '@gap' ? (
          <div style={{ flex: 1, minHeight: 0, overflow: 'auto', padding: '4px 16px 24px' }}>
            <TalentGap jd={jd} />
          </div>
        ) : agentAsset ? (
          <AssetView asset={agentAsset} tokens={t} />
        ) : doc && isMd && mode === 'preview' ? (
          /* 滚动容器**必须在这里**:之前直接把渲染结果铺在 flex 里,长文档滚不动
             (高度被 flex 吃掉了)。minHeight:0 + overflow:auto 是这条的关键两行。 */
          <div style={{ flex: 1, minHeight: 0, overflow: 'auto', padding: '4px 16px 24px' }}>
            {/* 标准目录是**可查**的东西（反查/筛选），只给 md 等于让人 Ctrl+F。
                这里换成面板；想读原文就切到「源码」页签（保存/回检那条路不变）。 */}
            {path === 'CATALOG.md'
              ? <TalentCatalog />
              : <CollapsibleMarkdown text={draft} tokens={t} onOpenLink={openCvLink} />}
          </div>
        ) : doc && dataFmt && mode === 'preview' ? (
          /* yaml/json:读成树。引文、txt_line、rationale 在这棵树里才看得出关系。 */
          <div style={{ flex: 1, minHeight: 0, overflow: 'auto', padding: '4px 16px 24px' }}>
            <StructuredBody text={draft} tokens={t} format={dataFmt} />
          </div>
        ) : (
          <div style={{ flex: 1, minHeight: 0, overflow: 'auto' }}>
            {loadingDoc && !doc && (
              <div style={{ padding: 20, fontSize: 12, color: t.textMuted }}>正在读取 {path} …</div>
            )}
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
            ) : !loadingDoc && (
              <div style={{ padding: 20, fontSize: 12.5, color: t.textMuted, lineHeight: 1.7 }}>
                <div style={{ marginBottom: 6, color: t.textPrimary }}>从左边浏览区选一个产物。</div>
                一份 JD 的产物是一条链：<br />
                <span style={{ opacity: 0.85 }}>1 客户原文</span>（只读锚点，改它等于把所有引用作废）→{' '}
                <span style={{ opacity: 0.85 }}>2 引用文件</span>（逐字回查的对象）→{' '}
                <span style={{ opacity: 0.85 }}>3 定稿 / 评审 / 短名单</span>
              </div>
            )}
          </div>
        )}
      </div>

      {/* ── 中间那道边:编辑器 ↔ 对话 ──
          8px 命中区里画 1px 可见线(平时淡、hover 亮、拖动时 accent),双击复位。
          和 LeftSidebar 的手柄是同一套视觉与手感 —— 两条边不该有两种行为。 */}
      <div
        onMouseDown={onChatDragStart}
        onDoubleClick={() => setChatWidth(CHAT_DEFAULT_WIDTH)}
        title="拖动调整对话栏宽度 · 双击复位"
        style={{ width: 8, cursor: 'ew-resize', background: 'transparent', flexShrink: 0,
                 display: 'flex', alignItems: 'stretch', justifyContent: 'center' }}
        onMouseEnter={(e) => {
          const line = e.currentTarget.firstElementChild as HTMLElement | null;
          if (line && !draggingChat) line.style.background = t.accent;
        }}
        onMouseLeave={(e) => {
          const line = e.currentTarget.firstElementChild as HTMLElement | null;
          if (line && !draggingChat) line.style.background = t.border;
        }}
      >
        <div style={{ width: 1, background: draggingChat ? t.accent : t.border,
                      transition: 'background 120ms' }} />
      </div>

      {/* ── 对话 ── */}
      {/* maxWidth 是兜底:窗口窄的时候对话栏不许把编辑器挤没了 —— 拖拽仍可到
          CHAT_MAX_WIDTH,但永远不会超过容器的 60%。 */}
      <div style={{ ...card, width: chatWidth, minWidth: chatWidth, maxWidth: '60%', flexShrink: 0 }}>
        <div style={hd}>
          <Wrench size={12} /> 对话
          <select
            value={agentId}
            onChange={(e) => setAgentId(Number(e.target.value))}
            title={agents.find((a) => a.id === agentId)?.description || `agent ${agentId}`}
            style={{ fontSize: 11, padding: '2px 4px', borderRadius: 4, maxWidth: 168,
                     textTransform: 'none', letterSpacing: 0,
                     border: `1px solid ${t.border}`, background: t.bgContent, color: t.textPrimary }}
          >
            {/* 当前 agent **一定**要出现在选项里:清单还没到、拉失败、或者它已经被退休
                (名字不再以 `Talent · ` 开头 → 不在清单里)时,少了这一项 select 就会显示空白,
                看起来就像"agent 没了"。退休的那个也要如实标出来,不能假装你在跟别的 agent 说话。 */}
            {(() => {
              const list: TalentAgent[] = [...agents];
              if (!list.some((a) => a.id === agentId)) {
                list.unshift({
                  id: agentId,
                  label: agents.length ? `agent ${agentId}(已退休)` : `agent ${agentId}`,
                  name: `agent ${agentId}`,
                  description: '',
                  step: -1,
                });
              }
              return list.map((a) => <option key={a.id} value={a.id}>{a.label}</option>);
            })()}
          </select>
          <span style={{ textTransform: 'none', letterSpacing: 0, fontSize: 10.5, opacity: 0.7 }}>
            {agentId}
          </span>
          {agent.running && <Loader size={11} style={{ marginLeft: 'auto' }} />}
        </div>
        <div ref={toolBoxRef} style={{ flex: 1, minHeight: 0, overflow: 'auto', padding: 8, fontSize: 11.5 }}>
          {agent.tools.length === 0 && !agent.answer && (
            <div style={{ color: t.textMuted }}>
              它的工具调用会显示在这里 —— 看它到底跑了哪条命令，而不是只读它的话。
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
            placeholder={jd ? `问 agent 关于「${jd}」的事…` : '先从左边的 JD 列表里选一份 JD'}
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

      {/* CV 弹层:从名单里的「看 CV」打开。铺满右侧、点背景或 Esc 关闭 ——
          不跳转、不丢当前那张表,读完关掉就回到名单原位置。 */}
      {cvPanel && (
        <div
          onClick={() => setCvPanel(null)}
          style={{
            position: 'fixed', inset: 0, zIndex: 60, background: 'rgba(0,0,0,.45)',
            display: 'flex', justifyContent: 'flex-end',
          }}
        >
          <div
            onClick={(e) => e.stopPropagation()}
            style={{
              width: 'min(860px, 92vw)', height: '100%', display: 'flex', flexDirection: 'column',
              background: t.bgContent, borderLeft: `1px solid ${t.border}`,
              boxShadow: '-8px 0 24px rgba(0,0,0,.35)',
            }}
          >
            <div style={{
              display: 'flex', alignItems: 'center', gap: 8, padding: '8px 12px',
              borderBottom: `1px solid ${t.border}`, flexShrink: 0,
            }}>
              <FileText size={13} style={{ color: t.textMuted }} />
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 12.5, color: t.textPrimary, overflow: 'hidden',
                              textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {cvPanel.cid.replace(/^cand_/, '')}
                </div>
                <div style={{ fontSize: 10.5, color: t.textMuted }}>
                  定稿全文 · {cvPanel.path}
                </div>
              </div>
              <button
                onClick={() => setCvPanel(null)}
                style={{
                  cursor: 'pointer', border: `1px solid ${t.border}`, borderRadius: 4,
                  background: t.bgInput, color: t.textPrimary, fontSize: 11,
                  padding: '3px 8px',
                }}
              >
                关闭 (Esc)
              </button>
            </div>
            {cvPanel.loading && (
              <div style={{ padding: 16, fontSize: 12, color: t.textMuted }}>
                <Loader size={12} /> 正在读 {cvPanel.path} …
              </div>
            )}
            {cvPanel.error && (
              <div style={{ padding: 16, fontSize: 12, color: '#e5484d' }}>{cvPanel.error}</div>
            )}
            {!cvPanel.loading && !cvPanel.error && (
              <div style={{ flex: 1, minHeight: 0, overflow: 'auto', padding: '4px 16px 24px' }}>
                <CollapsibleMarkdown text={cvPanel.text} tokens={t} onOpenLink={openCvLink} />
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
