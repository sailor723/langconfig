/**
 * KnowledgeHomePage — landing page for the Knowledge Base activity.
 *
 * The document browser itself lives in the KnowledgeSidebar (left panel).
 * This page renders lightweight intro text in the main browser area so the
 * activity is never blank, and guides the user to upload/select documents.
 * Pure UI — no backend calls.
 */
import { useTranslation } from 'react-i18next';
import { useLayoutTokens } from './tokens';
import { Database, FileUp, FolderUp, FileText, Search, ArrowRight } from 'lucide-react';

function useContent() {
  const { i18n } = useTranslation();
  const isZh = i18n.language.startsWith('zh');

  return isZh ? {
    heroTitle: 'Knowledge Base',
    heroSubtitle: '你的团队文档知识库',
    heroP1: 'Knowledge Base 集中存储和管理项目文档、参考资料与数据文件，为 Agent 提供可检索的知识来源。',
    heroP2: '上传文件或文件夹后，文档会保留原始目录层级，可随时在侧边栏中浏览、预览或下载。',
    step1Title: '上传文档',
    step1Desc: '点击侧边栏顶部的 + 上传单个文件，或使用文件夹按钮批量导入并保留目录结构。',
    step2Title: '浏览检索',
    step2Desc: '文档按层级树展示，点击即可预览内容；搜索功能可快速定位所需资料。',
    step3Title: '供 Agent 使用',
    step3Desc: '已导入的知识库可作为 Agent 的上下文来源，用于回答与项目相关的问题。',
    emptyHint: '侧边栏当前展示项目文档。点击左上角 + 上传你的第一份文档。',
  } : {
    heroTitle: 'Knowledge Base',
    heroSubtitle: 'Project documentation library',
    heroP1: 'The Knowledge Base centrally stores project documents, references and data files, giving agents a searchable source of knowledge.',
    heroP2: 'Upload files or folders and documents keep their original hierarchy — browse, preview and download them anytime from the sidebar.',
    step1Title: 'Upload documents',
    step1Desc: 'Click + at the top of the sidebar to upload files, or use the folder button to import a tree in one go.',
    step2Title: 'Browse & search',
    step2Desc: 'Documents are shown as a hierarchy tree; click to preview. Search locates the exact material you need.',
    step3Title: 'Feed your agents',
    step3Desc: 'Imported documents become context sources agents can use to answer project-related questions.',
    emptyHint: 'The sidebar shows project documents. Click + in the top-left to upload your first document.',
  };
}

function Section({ title, subtitle, children }: { title: string; subtitle?: string; children: React.ReactNode }) {
  const t = useLayoutTokens();
  return (
    <div style={{ marginBottom: 28 }}>
      <div style={{ marginBottom: 10 }}>
        <h2 style={{ fontSize: 15, fontWeight: 700, color: t.textPrimary, margin: 0, letterSpacing: '-0.2px' }}>
          {title}
        </h2>
        {subtitle && <p style={{ fontSize: 12, color: t.textMuted, margin: '4px 0 0' }}>{subtitle}</p>}
      </div>
      {children}
    </div>
  );
}

function StepCard({ icon: Icon, title, desc, accent }: { icon: typeof FileUp; title: string; desc: string; accent: string }) {
  const t = useLayoutTokens();
  return (
    <div style={{ flex: 1, minWidth: 220, padding: 18, borderRadius: 10, background: t.bgContent, border: `1px solid ${t.border}` }}>
      <div style={{ width: 32, height: 32, borderRadius: 8, display: 'flex', alignItems: 'center', justifyContent: 'center', background: `${accent}22`, color: accent, marginBottom: 10 }}>
        <Icon size={16} />
      </div>
      <div style={{ fontSize: 13, fontWeight: 600, color: t.textPrimary, marginBottom: 6 }}>{title}</div>
      <div style={{ fontSize: 12, color: t.textMuted, lineHeight: 1.6 }}>{desc}</div>
    </div>
  );
}

export default function KnowledgeHomePage() {
  const t = useLayoutTokens();
  const c = useContent();

  return (
    <div style={{ height: '100%', overflowY: 'auto', padding: '40px 48px' }}>
      {/* ── Hero ─────────────────────────────────────── */}
      <div style={{ maxWidth: 860, marginBottom: 36 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 12 }}>
          <div style={{ width: 40, height: 40, borderRadius: 10, display: 'flex', alignItems: 'center', justifyContent: 'center', background: `${t.accent}22`, color: t.accent }}>
            <Database size={20} />
          </div>
          <div>
            <h1 style={{ fontSize: 22, fontWeight: 700, margin: 0, color: t.textPrimary }}>{c.heroTitle}</h1>
            <p style={{ fontSize: 12, color: t.textMuted, margin: '2px 0 0' }}>{c.heroSubtitle}</p>
          </div>
        </div>
        <p style={{ fontSize: 14, color: t.textPrimary, lineHeight: 1.8, margin: '0 0 8px', maxWidth: 720 }}>{c.heroP1}</p>
        <p style={{ fontSize: 13, color: t.textMuted, lineHeight: 1.7, margin: 0, maxWidth: 720 }}>{c.heroP2}</p>
      </div>

      {/* ── How it works ─────────────────────────────── */}
      <Section title="How it works">
        <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
          <StepCard icon={FileUp} accent={t.accent} title={c.step1Title} desc={c.step1Desc} />
          <StepCard icon={Search} accent="#8b5cf6" title={c.step2Title} desc={c.step2Desc} />
          <StepCard icon={FileText} accent="#06b6d4" title={c.step3Title} desc={c.step3Desc} />
        </div>
      </Section>

      {/* ── Empty-state hint ─────────────────────────── */}
      <div style={{ maxWidth: 860, padding: 20, borderRadius: 10, border: `1px dashed ${t.border}`, color: t.textMuted, fontSize: 13, display: 'flex', alignItems: 'center', gap: 8 }}>
        <FolderUp size={14} />
        <span>{c.emptyHint}</span>
        <ArrowRight size={14} style={{ marginLeft: 'auto', opacity: 0.6 }} />
      </div>
    </div>
  );
}
