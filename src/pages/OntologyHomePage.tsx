/**
 * OntologyHomePage — the Ontology activity lands on the **Data Agent document**.
 *
 * Why a document instead of another dashboard: the first thing this activity has to answer is
 * "what an ontology is, what it is made of, how a number gets from a declaration to a chart, and
 * what it refuses" — which is exactly what `docs/system-architecture/data-agent.md` answers.
 * Rendering the built `data-agent.html` here means **one source**: the app cannot tell a different
 * story than the document, and the figures, TOC anchors, version stamp and footer travel with it.
 *
 * The rest of the activity is unchanged and stays reachable from the sidebar and the header:
 * `/ontology/browse` (what a profile declares), `/ontology/app` (ask it), `/ontology/dashboard`
 * (the declared boards). The header keeps the live "up/total" count plus the two actions that
 * otherwise require knowing a URL — 重新编译 and 生成…（agent 建本体）.
 *
 * The old landing page (concept cards, steps, per-ontology cards with live counts) is not lost:
 * 第零部分 and 第二部分 of this document are that content, and the sidebar still lists every
 * ontology with its publish state. Keeping both would mean two places to update.
 *
 * If the document is not built, the page says which command builds it — a blank iframe would be
 * the same silent failure this repo keeps digging out of.
 */
import { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Boxes, ExternalLink, ListTree, Loader2, Printer, RefreshCw, Sparkles } from 'lucide-react';
import { useLayoutTokens } from '../components/layout2/tokens';
import { ontology, useOntology } from '../features/ontology/ontologyStore';
import BuildOntologyDialog from '../features/ontology/BuildOntologyDialog';
import { Btn, Chip, Quiet, SUCCESS, WARN, DANGER } from '../features/ontology/ui';
import { API_BASE_URL } from '../config/api';
import apiClient from '../lib/api-client';

interface DocMeta {
  version: string;
  date: string;
  exists: boolean;
  bytes: number;
  built_at: number | null;
  formats: string[];
}

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
  const [buildOpen, setBuildOpen] = useState(false);

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

  useEffect(() => { void loadMeta(); }, [loadMeta]);

  const up = s.profiles.filter(p => s.probes[p.key]?.status === 'up').length;
  const total = s.profiles.length;

  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column', minHeight: 0, background: t.bgContent }}>
      {buildOpen && (
        <BuildOntologyDialog
          ontologyKey={ontology.get().preset ?? ''}
          onClose={() => setBuildOpen(false)}
          onLanded={() => void ontology.probeAll()}
        />
      )}

      {/* ── header: what this is, which version, and the few things you might do next ── */}
      <header style={{
        display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap',
        padding: '12px 20px', borderBottom: `1px solid ${t.border}`, background: t.bgSidebar,
      }}>
        <Boxes size={18} color={t.textPrimary} />
        <div style={{ display: 'flex', flexDirection: 'column', gap: 2, minWidth: 0 }}>
          <div style={{ fontSize: 15, fontWeight: 650, color: t.textPrimary }}>
            本体 · 数据 Agent 总文档
          </div>
          <div style={{ fontSize: 11.5, color: t.textMuted }}>
            {meta === null
              ? '读取版本…'
              : meta.exists
                ? `${meta.version || '版本未标注'} · ${meta.date || '日期未标注'} · ${kb(meta.bytes)} · 与 data-agent.docx / .pdf 同源`
                : '文档还没生成 —— 见页面下方的构建命令'}
          </div>
        </div>

        <div style={{ display: 'flex', gap: 6, marginLeft: 'auto', flexWrap: 'wrap', alignItems: 'center' }}>
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
          <Btn onClick={() => window.open(PDF_URL, '_blank', 'noopener')} title="打印/归档用的 PDF（与本文同源）">
            <Printer size={13} /> PDF
          </Btn>
          <Btn onClick={() => window.open(DOC_URL, '_blank', 'noopener')} title="在新标签页里读（有完整目录）">
            <ExternalLink size={13} /> 新标签
          </Btn>
        </div>
      </header>

      {/* ── the document itself ── */}
      <div style={{ flex: 1, minHeight: 0, position: 'relative' }}>
        {meta === null && (
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: 24, color: t.textMuted }}>
            <Loader2 size={14} className="animate-spin" /> 正在读取文档…
          </div>
        )}

        {meta && meta.exists && (
          <iframe
            key={`${meta.bytes}-${meta.built_at ?? 0}`}
            src={DOC_URL}
            title="数据 Agent 总文档"
            style={{ width: '100%', height: '100%', border: 0, display: 'block', background: '#fbfcfd' }}
            sandbox="allow-scripts allow-same-origin allow-popups"
          />
        )}

        {meta && !meta.exists && (
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
              <Btn onClick={() => void loadMeta()}>
                <RefreshCw size={13} /> 已生成，重新检查
              </Btn>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
