/**
 * OntologyHomePage — the Ontology activity lands on the **Data Agent document**, with a
 * right-hand section index (the same shape as the Knowledge document viewer).
 *
 * Why a document: the first question this activity must answer is "what an ontology is, what it is
 * made of, how a number gets from a declaration to a chart, and what it refuses" — which is what
 * `docs/system-architecture/data-agent.md` answers. Rendering the built `data-agent.html` means one
 * source: figures, TOC anchors, version stamp and footer are the ones a reader gets outside the app.
 *
 * Two views, both in-app (never the browser's PDF viewer):
 *   · 文档 — the built HTML in an iframe (inline SVG figures, clickable in-page TOC)
 *   · PDF  — pdf.js via `PdfViewer`. This is not a preference: Safari's PDFKit mis-renders the
 *            subsetted CJK fonts in this document (garbled text), which is exactly why that
 *            component exists in the repo.
 *
 * The right panel lists the document's own `<h1>/<h2>` headings, served by
 * `GET /api/ontology/doc/headings` — parsed from the BUILT html, so a click always lands on an id
 * that exists. The clicked entry is highlighted, and scrolling the document keeps it in sync
 * (same-origin iframe, so its scroll position is readable).
 *
 * The old landing page (concept cards, steps, per-ontology cards) lives on as 第零/第二部分 of this
 * document and as the sidebar's ontology list — keeping both would be two places to update.
 */
import { lazy, Suspense, useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Boxes, ExternalLink, List, ListTree, Loader2, PanelRightClose, PanelRightOpen,
  Printer, RefreshCw, Sparkles,
} from 'lucide-react';
import { useLayoutTokens } from '../components/layout2/tokens';
import { ontology, useOntology } from '../features/ontology/ontologyStore';
import BuildOntologyDialog from '../features/ontology/BuildOntologyDialog';
import { Btn, Chip, Quiet, SUCCESS, WARN, DANGER } from '../features/ontology/ui';
import { API_BASE_URL } from '../config/api';
import apiClient from '../lib/api-client';

// pdf.js + worker is ~1MB; load only when a reader asks for the PDF view.
const PdfViewer = lazy(() => import('../components/layout2/PdfViewer'));

interface DocMeta {
  version: string;
  date: string;
  exists: boolean;
  bytes: number;
  built_at: number | null;
  formats: string[];
}
interface Heading { level: number; anchor: string; text: string }

const DOC_URL = `${API_BASE_URL}/api/ontology/doc`;
const PDF_URL = `${DOC_URL}?format=pdf`;

function kb(bytes: number): string {
  return bytes >= 1024 * 1024
    ? `${(bytes / 1024 / 1024).toFixed(1)} MB`
    : `${Math.max(1, Math.round(bytes / 1024))} KB`;
}

export default function OntologyHomePage() {
  const t = useLayoutTokens();
  const navigate = useNavigate();
  const s = useOntology();
  const [meta, setMeta] = useState<DocMeta | null>(null);
  const [heads, setHeads] = useState<Heading[]>([]);
  const [active, setActive] = useState('');
  const [view, setView] = useState<'html' | 'pdf'>('html');
  const [showToc, setShowToc] = useState(true);
  const [buildOpen, setBuildOpen] = useState(false);
  const frameRef = useRef<HTMLIFrameElement | null>(null);

  useEffect(() => {
    void (async () => {
      await ontology.ensureReady();
      void ontology.probeAll();
    })();
  }, []);

  const loadMeta = useCallback(async () => {
    try {
      const res: any = await apiClient.get('/api/ontology/doc/meta');
      setMeta(res.data as DocMeta);
    } catch {
      setMeta({ version: '', date: '', exists: false, bytes: 0, built_at: null, formats: [] });
    }
  }, []);

  const loadHeads = useCallback(async () => {
    try {
      const res: any = await apiClient.get('/api/ontology/doc/headings', { params: { max_level: 2 } });
      setHeads((res.data?.headings ?? []) as Heading[]);
    } catch {
      setHeads([]);
    }
  }, []);

  useEffect(() => { void loadMeta(); void loadHeads(); }, [loadMeta, loadHeads]);

  /** Click an index entry: scroll inside the iframe (same origin, so this is allowed). */
  const jump = useCallback((anchor: string) => {
    setActive(anchor);
    const doc = frameRef.current?.contentDocument;
    const el = doc?.getElementById(anchor);
    if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }, []);

  /** Keep the highlighted entry in sync with where the reader actually is. */
  const onFrameLoad = useCallback(() => {
    const win = frameRef.current?.contentWindow;
    const doc = frameRef.current?.contentDocument;
    if (!win || !doc) return;
    const sync = () => {
      let current = heads[0]?.anchor ?? '';
      for (const h of heads) {
        const el = doc.getElementById(h.anchor);
        if (el && el.getBoundingClientRect().top <= 96) current = h.anchor;
      }
      setActive(current);
    };
    sync();
    win.addEventListener('scroll', sync, { passive: true });
  }, [heads]);

  const up = s.profiles.filter(p => s.probes[p.key]?.status === 'up').length;
  const total = s.profiles.length;
  const built = Boolean(meta?.exists);

  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column', minHeight: 0, background: t.bgContent }}>
      {buildOpen && (
        <BuildOntologyDialog
          ontologyKey={ontology.get().preset ?? ''}
          onClose={() => setBuildOpen(false)}
          onLanded={() => void ontology.probeAll()}
        />
      )}

      {/* ── header ── */}
      <header style={{
        display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap',
        padding: '10px 18px', borderBottom: `1px solid ${t.border}`, background: t.bgSidebar, flexShrink: 0,
      }}>
        <Boxes size={18} color={t.textPrimary} />
        <div style={{ display: 'flex', flexDirection: 'column', gap: 2, minWidth: 0 }}>
          <div style={{ fontSize: 15, fontWeight: 650, color: t.textPrimary }}>本体 · 数据 Agent 总文档</div>
          <div style={{ fontSize: 11.5, color: t.textMuted }}>
            {meta === null
              ? '读取版本…'
              : built
                ? `${meta.version || '版本未标注'} · ${meta.date || '日期未标注'} · ${kb(meta.bytes)} · 与 .docx / .pdf 同源`
                : '文档还没生成 —— 见页面下方的构建命令'}
          </div>
        </div>

        <div style={{ display: 'flex', gap: 6, marginLeft: 'auto', flexWrap: 'wrap', alignItems: 'center' }}>
          {built && (
            <>
              <Chip active={view === 'html'} onClick={() => setView('html')} title="构建好的 HTML（内联 SVG 图）">文档</Chip>
              <Chip active={view === 'pdf'} onClick={() => setView('pdf')} title="用 pdf.js 渲染——浏览器自带的 PDF 阅读器会把这份文档的中文字体拆坏">PDF</Chip>
            </>
          )}
          {total > 0 && (
            <Chip colour={up === total ? SUCCESS : up > 0 ? WARN : DANGER} title={`${up} 个已声明 / 共 ${total} 个`}>
              {up}/{total} 个本体已声明
            </Chip>
          )}
          <Btn onClick={() => void ontology.probeAll()} title="重新编译每个本体，并报告它声明了什么">
            <RefreshCw size={13} /> 重新编译
          </Btn>
          <Btn onClick={() => setBuildOpen(true)} title="用 agent 生成或重建一个本体（后台任务）">
            <Sparkles size={13} /> 生成…
          </Btn>
          <Btn onClick={() => navigate('/ontology/browse')} title="这个 profile 到底声明了什么">
            <ListTree size={13} /> 看声明
          </Btn>
          <Btn onClick={() => setShowToc(v => !v)} title={showToc ? '收起右侧目录' : '展开右侧目录'}>
            {showToc ? <PanelRightClose size={13} /> : <PanelRightOpen size={13} />}
          </Btn>
          <Btn onClick={() => window.open(view === 'pdf' ? PDF_URL : DOC_URL, '_blank', 'noopener')} title="在新标签页里打开当前视图">
            <ExternalLink size={13} /> 新标签
          </Btn>
        </div>
      </header>

      {/* ── viewer + right-hand section index ── */}
      <div style={{ flex: 1, minHeight: 0, display: 'flex' }}>
        <div style={{ flex: 1, minWidth: 0, position: 'relative' }}>
          {meta === null && (
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: 24, color: t.textMuted }}>
              <Loader2 size={14} className="animate-spin" /> 正在读取文档…
            </div>
          )}

          {built && view === 'html' && (
            <iframe
              ref={frameRef}
              key={`${meta!.bytes}-${meta!.built_at ?? 0}`}
              src={DOC_URL}
              title="数据 Agent 总文档"
              onLoad={onFrameLoad}
              style={{ width: '100%', height: '100%', border: 0, display: 'block', background: '#fbfcfd' }}
              sandbox="allow-scripts allow-same-origin allow-popups"
            />
          )}

          {built && view === 'pdf' && (
            <Suspense fallback={
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: 24, color: t.textMuted }}>
                <Loader2 size={14} className="animate-spin" /> 正在加载 pdf.js…
              </div>
            }>
              <PdfViewer url={PDF_URL} />
            </Suspense>
          )}

          {meta && !built && (
            <div style={{ padding: '40px 24px', maxWidth: 760 }}>
              <div style={{ fontSize: 15, fontWeight: 600, color: t.textPrimary, marginBottom: 8 }}>
                这份文档还没生成
              </div>
              <Quiet>
                首页读的是构建产物 <code>docs/system-architecture/data-agent.html</code>（由{' '}
                <code>data-agent.md</code> 构建）。在仓库根跑下面任一条，然后刷新这一页：
              </Quiet>
              <pre style={{
                marginTop: 12, padding: '12px 14px', borderRadius: 8, background: t.bgInput,
                border: `1px solid ${t.border}`, fontSize: 12.5, overflowX: 'auto', color: t.textPrimary,
              }}>{`python scripts/build_toc.py
python scripts/build_data_agent_docs.py     # data-agent.docx
python scripts/build_data_agent_html.py     # data-agent.html + data-agent.pdf`}</pre>
              <div style={{ marginTop: 14 }}>
                <Btn onClick={() => { void loadMeta(); void loadHeads(); }}>
                  <RefreshCw size={13} /> 已生成，重新检查
                </Btn>
              </div>
            </div>
          )}
        </div>

        {/* Right-hand index — the same shape as the Knowledge viewer's contents panel. */}
        {showToc && built && (
          <aside style={{
            width: 268, flexShrink: 0, display: 'flex', flexDirection: 'column', overflow: 'hidden',
            borderLeft: `1px solid ${t.border}`, background: t.bgSidebar,
          }}>
            <div style={{
              display: 'flex', alignItems: 'center', gap: 6, padding: '8px 12px',
              borderBottom: `1px solid ${t.border}`, flexShrink: 0,
            }}>
              <List size={13} style={{ color: t.accent }} />
              <span style={{
                fontSize: 11, fontWeight: 600, letterSpacing: '.04em',
                textTransform: 'uppercase', color: t.textMuted,
              }}>目录</span>
              <span style={{ fontSize: 11, color: t.textDim, marginLeft: 'auto' }}>{heads.length}</span>
            </div>

            <div style={{ flex: 1, overflowY: 'auto', padding: '6px 4px 12px' }}>
              {heads.length === 0 && (
                <div style={{ padding: '10px 12px', fontSize: 12, color: t.textMuted }}>没有可点的标题</div>
              )}
              {heads.map(h => {
                const isActive = view === 'html' && h.anchor === active;
                return (
                  <button
                    key={h.anchor}
                    title={h.text}
                    disabled={view !== 'html'}
                    onClick={() => jump(h.anchor)}
                    style={{
                      display: 'block', width: '100%', textAlign: 'left', border: 'none',
                      background: isActive ? t.bgHover : 'transparent',
                      color: isActive ? t.accent : t.textMuted,
                      fontSize: 12, fontWeight: isActive ? 600 : 400,
                      cursor: view === 'html' ? 'pointer' : 'not-allowed',
                      opacity: view === 'html' ? 1 : 0.55,
                      borderRadius: 3, padding: '3px 8px',
                      paddingLeft: 8 + (h.level - 1) * 12,
                      whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
                      lineHeight: 1.45,
                    }}
                  >{h.text}</button>
                );
              })}
              {view === 'pdf' && (
                <div style={{ margin: '10px 8px 0', fontSize: 11, color: t.textDim, lineHeight: 1.6 }}>
                  PDF 是按页渲染的，锚点只对「文档」视图有效；切回「文档」即可点目录跳转。
                </div>
              )}
            </div>

            <div style={{
              padding: '8px 12px', borderTop: `1px solid ${t.border}`, flexShrink: 0,
              display: 'flex', gap: 6, justifyContent: 'flex-end',
            }}>
              <Btn onClick={() => window.open(PDF_URL, '_blank', 'noopener')} title="PDF 原文件（打印/归档）">
                <Printer size={12} /> PDF
              </Btn>
            </div>
          </aside>
        )}
      </div>
    </div>
  );
}
