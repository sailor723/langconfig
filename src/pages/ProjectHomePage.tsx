/**
 * ProjectHomePage — landing page shown after creating or selecting a project.
 *
 * Replaces the old behavior of dumping the user straight into the workflow
 * builder. Shows the project's identity (name, status, description, workspace
 * path), quick stats, entry points to each section, and the project's recent
 * workflows (opening one jumps straight into the Studio with it loaded).
 */
import { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Folder, MessageSquare, Brain, Users, GitBranch, Database,
  ArrowRight, Loader, Calendar, FolderOpen, GitPullRequest, Clock,
} from 'lucide-react';
import { useProject } from '../contexts/ProjectContext';
import { useLayoutTokens } from '../components/layout2/tokens';
import apiClient from '../lib/api-client';

interface WorkflowItem {
  id: number;
  name: string;
  description?: string | null;
  updated_at?: string;
}

const STATUS_COLOR: Record<string, string> = {
  active: '#22c55e',
  idle: '#3b82f6',
  archived: '#6b7280',
  error: '#ef4444',
};

export default function ProjectHomePage() {
  const { activeProject, activeProjectId, loading } = useProject();
  const navigate = useNavigate();
  const t = useLayoutTokens();

  const [workflows, setWorkflows] = useState<WorkflowItem[]>([]);
  const [agentsCount, setAgentsCount] = useState(0);
  const [dataLoading, setDataLoading] = useState(false);

  // No project selected (and initial project list has finished loading) →
  // send the user back to the create/select-project screen.
  useEffect(() => {
    if (!loading && !activeProjectId) navigate('/');
  }, [loading, activeProjectId, navigate]);

  // Fetch this project's workflows + the global agent count.
  useEffect(() => {
    if (!activeProjectId) return;
    let cancelled = false;
    setDataLoading(true);
    (async () => {
      try {
        const [wfRes, agRes] = await Promise.all([
          apiClient.listWorkflows({ project_id: activeProjectId, limit: 6 }),
          apiClient.listDeepAgents(),
        ]);
        if (cancelled) return;
        setWorkflows(Array.isArray(wfRes.data) ? wfRes.data : []);
        setAgentsCount(Array.isArray(agRes.data) ? agRes.data.length : 0);
      } catch (err: any) {
        if (!cancelled) console.error('Project home load failed:', err?.message);
      } finally {
        if (!cancelled) setDataLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [activeProjectId]);

  // Open a workflow in the Studio (AppContent listens and routes to /studio
  // with the workflow preloaded — same pattern as da:navigate-skills).
  const openWorkflow = useCallback((id: number) => {
    window.dispatchEvent(new CustomEvent('workflow:open', { detail: { workflowId: id } }));
  }, []);

  if (loading) {
    return (
      <div style={{ height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center', background: t.bgContent }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, fontSize: 13, color: t.textMuted }}>
          <Loader size={16} style={{ animation: 'spin 1s linear infinite' }} />
          Loading project…
        </div>
      </div>
    );
  }

  if (!activeProject) return null; // redirect effect above handles this

  const status = activeProject.status || 'idle';
  const statusColor = STATUS_COLOR[status] || '#6b7280';
  const createdDate = activeProject.created_at
    ? new Date(activeProject.created_at).toLocaleDateString()
    : '';

  const entries = [
    { icon: MessageSquare, label: 'Chat', desc: 'Talk to this project’s agents', route: '/chat', accent: '#3b82f6' },
    { icon: Brain, label: 'Deep Agents', desc: 'Multi-agent orchestration & harness', route: '/deepagents', accent: '#8b5cf6' },
    { icon: Users, label: 'Agents', desc: 'Simple chat agents', route: '/agents', accent: '#22c55e' },
    { icon: Database, label: 'Knowledge', desc: 'Documents & RAG index', route: '/knowledge', accent: '#06b6d4' },
  ];

  return (
    <div style={{ height: '100%', overflowY: 'auto', background: t.bgContent }}>
      <div style={{ maxWidth: 960, margin: '0 auto', padding: '40px 32px 64px' }}>
        {/* ── Hero: project identity ─────────────────────── */}
        <div
          style={{
            display: 'flex', gap: 20, alignItems: 'flex-start',
            background: `linear-gradient(135deg, ${t.accent}1e 0%, ${t.accent}08 55%, ${t.bgContent} 100%)`,
            border: `1px solid ${t.border}`, borderRadius: 12,
            padding: '28px 28px 24px', marginBottom: 20,
          }}
        >
          <div
            style={{
              width: 52, height: 52, borderRadius: 12, flexShrink: 0,
              background: `linear-gradient(135deg, ${t.accent}, ${t.accent}cc)`,
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              boxShadow: `0 4px 14px ${t.accent}35`,
            }}
          >
            <Folder size={26} color="#fff" />
          </div>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap', marginBottom: 4 }}>
              <h1 style={{ fontSize: 24, fontWeight: 750, color: t.textPrimary, margin: 0, letterSpacing: '-0.3px' }}>
                {activeProject.name}
              </h1>
              <span
                style={{
                  fontSize: 11, fontWeight: 600, textTransform: 'uppercase', letterSpacing: 0.3,
                  color: statusColor, background: `${statusColor}1a`,
                  padding: '2px 10px', borderRadius: 999,
                }}
              >
                {status}
              </span>
            </div>
            {activeProject.description && (
              <p style={{ fontSize: 13, color: t.textMuted, margin: '4px 0 0 0', lineHeight: 1.5, maxWidth: 620 }}>
                {activeProject.description}
              </p>
            )}
            <div style={{ display: 'flex', alignItems: 'center', gap: 16, marginTop: 12, flexWrap: 'wrap' }}>
              {createdDate && (
                <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5, fontSize: 11, color: t.textMuted }}>
                  <Calendar size={12} /> Created {createdDate}
                </span>
              )}
              {activeProject.project_path && (
                <span
                  style={{
                    display: 'inline-flex', alignItems: 'center', gap: 5, fontSize: 11, color: t.textMuted,
                    fontFamily: 'monospace', background: t.bgSidebar, border: `1px solid ${t.border}`,
                    padding: '2px 8px', borderRadius: 4,
                  }}
                  title="Project workspace path"
                >
                  <FolderOpen size={12} /> {activeProject.project_path}
                </span>
              )}
            </div>
          </div>
        </div>

        {/* ── Stats row ──────────────────────────────────── */}
        <div style={{ display: 'flex', gap: 12, marginBottom: 28, flexWrap: 'wrap' }}>
          <StatCard icon={GitPullRequest} label="Workflows in project" value={workflows.length} accent="#f59e0b" t={t} />
          <StatCard icon={Brain} label="Agents (all projects)" value={agentsCount} accent="#8b5cf6" t={t} />
          <StatCard icon={Folder} label="Project ID" value={String(activeProject.id)} accent="#3b82f6" t={t} />
        </div>

        {/* ── Entry points ───────────────────────────────── */}
        <Section title="Get started" t={t}>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(210px, 1fr))', gap: 12 }}>
            {entries.map(e => (
              <button
                key={e.label}
                onClick={() => navigate(e.route)}
                style={{
                  display: 'flex', flexDirection: 'column', gap: 10,
                  padding: 16, borderRadius: 10, textAlign: 'left', cursor: 'pointer',
                  background: t.bgContent, border: `1px solid ${t.border}`,
                  transition: 'border-color 0.15s, box-shadow 0.15s',
                }}
                onMouseEnter={ev => { ev.currentTarget.style.borderColor = e.accent; ev.currentTarget.style.boxShadow = '0 2px 10px rgba(0,0,0,0.08)'; }}
                onMouseLeave={ev => { ev.currentTarget.style.borderColor = t.border; ev.currentTarget.style.boxShadow = 'none'; }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                  <div
                    style={{
                      width: 32, height: 32, borderRadius: 7, flexShrink: 0,
                      background: `${e.accent}18`, display: 'flex', alignItems: 'center', justifyContent: 'center',
                    }}
                  >
                    <e.icon size={16} color={e.accent} />
                  </div>
                  <div style={{ fontSize: 13, fontWeight: 600, color: t.textPrimary }}>{e.label}</div>
                </div>
                <p style={{ fontSize: 11, color: t.textMuted, lineHeight: 1.45, margin: 0 }}>{e.desc}</p>
                <div style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 11, fontWeight: 600, color: e.accent, marginTop: 2 }}>
                  Open <ArrowRight size={12} />
                </div>
              </button>
            ))}
          </div>
        </Section>

        {/* ── Recent workflows ───────────────────────────── */}
        <Section
          title="Recent workflows"
          subtitle={dataLoading ? undefined : `${workflows.length} workflow${workflows.length === 1 ? '' : 's'} in this project`}
          t={t}
        >
          {dataLoading ? (
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '14px 4px', fontSize: 12, color: t.textMuted }}>
              <Loader size={14} style={{ animation: 'spin 1s linear infinite' }} /> Loading workflows…
            </div>
          ) : workflows.length === 0 ? (
            <div
              style={{
                padding: '26px 20px', borderRadius: 10, textAlign: 'center',
                border: `1px dashed ${t.border}`, color: t.textMuted, fontSize: 12,
              }}
            >
              No workflows in this project yet.
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {workflows.map(wf => (
                <button
                  key={wf.id}
                  onClick={() => openWorkflow(wf.id)}
                  style={{
                    display: 'flex', alignItems: 'center', gap: 12,
                    padding: '12px 14px', borderRadius: 8, textAlign: 'left', cursor: 'pointer',
                    background: t.bgContent, border: `1px solid ${t.border}`,
                    transition: 'border-color 0.15s',
                  }}
                  onMouseEnter={ev => { ev.currentTarget.style.borderColor = t.accent; }}
                  onMouseLeave={ev => { ev.currentTarget.style.borderColor = t.border; }}
                >
                  <GitBranch size={15} style={{ color: t.textMuted, flexShrink: 0 }} />
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontSize: 13, fontWeight: 500, color: t.textPrimary, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {wf.name}
                    </div>
                    {wf.description && (
                      <div style={{ fontSize: 11, color: t.textMuted, marginTop: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                        {wf.description}
                      </div>
                    )}
                  </div>
                  {wf.updated_at && (
                    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 11, color: t.textMuted, flexShrink: 0 }}>
                      <Clock size={11} />
                      {new Date(wf.updated_at).toLocaleDateString()}
                    </span>
                  )}
                  <ArrowRight size={14} style={{ color: t.accent, flexShrink: 0 }} />
                </button>
              ))}
            </div>
          )}
        </Section>
      </div>
    </div>
  );
}

// ── Small building blocks ─────────────────────────────────────

function Section({ title, subtitle, children, t }: { title: string; subtitle?: string; children: React.ReactNode; t: ReturnType<typeof useLayoutTokens> }) {
  return (
    <div style={{ marginBottom: 28 }}>
      <div style={{ marginBottom: 12 }}>
        <h2 style={{ fontSize: 15, fontWeight: 700, color: t.textPrimary, margin: 0, letterSpacing: '-0.2px' }}>{title}</h2>
        {subtitle && <p style={{ fontSize: 12, color: t.textMuted, margin: '4px 0 0 0' }}>{subtitle}</p>}
      </div>
      {children}
    </div>
  );
}

function StatCard({ icon: Icon, label, value, accent, t }: {
  icon: typeof Folder; label: string; value: string | number; accent: string;
  t: ReturnType<typeof useLayoutTokens>;
}) {
  return (
    <div
      style={{
        flex: 1, minWidth: 160, display: 'flex', alignItems: 'center', gap: 12,
        padding: '14px 16px', borderRadius: 10,
        background: t.bgContent, border: `1px solid ${t.border}`,
      }}
    >
      <div style={{ width: 34, height: 34, borderRadius: 8, background: `${accent}18`, display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
        <Icon size={16} color={accent} />
      </div>
      <div style={{ minWidth: 0 }}>
        <div style={{ fontSize: 18, fontWeight: 700, color: t.textPrimary, lineHeight: 1.1 }}>{value}</div>
        <div style={{ fontSize: 11, color: t.textMuted, marginTop: 2, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{label}</div>
      </div>
    </div>
  );
}
