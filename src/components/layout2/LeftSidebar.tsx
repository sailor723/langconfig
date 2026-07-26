/**
 * LeftSidebar — contextual panel next to the ActivityBar.
 *
 * Content changes based on the active activity:
 *   Workflows → saved workflow list + templates
 *   Agents    → agent library + loadouts
 *   Library   → skills / tools / prompts tree
 *   Analysis  → data sources / dashboards
 *   Settings  → (no sidebar, full workspace)
 */
import { useLayoutState, ACTIVITIES, type ActivityId } from './useLayout';
import { useLayoutTokens } from './tokens';

interface SidebarSection {
  title: string;
  items: { id: string; label: string; badge?: string }[];
}

// Placeholder sidebar content per activity
const SIDEBAR_DATA: Record<ActivityId, SidebarSection[]> = {
  workflows: [
    { title: 'Workflows', items: [
      { id: 'wf-1', label: 'Sales Bot' },
      { id: 'wf-2', label: 'Support Agent' },
      { id: 'wf-3', label: 'Data Pipeline' },
    ]},
    { title: 'Templates', items: [
      { id: 'tpl-1', label: 'Blank Workflow' },
      { id: 'tpl-2', label: 'Chat Agent' },
      { id: 'tpl-3', label: 'RAG Pipeline' },
    ]},
  ],
  agents: [
    { title: 'My Agents', items: [
      { id: 'ag-1', label: 'SQL Analyst' },
      { id: 'ag-2', label: 'Deep Researcher' },
      { id: 'ag-3', label: 'Code Assistant' },
    ]},
    { title: 'Loadouts', items: [
      { id: 'lo-1', label: 'Default', badge: 'active' },
      { id: 'lo-2', label: 'Fast Mode' },
      { id: 'lo-3', label: 'Full Analysis' },
    ]},
  ],
  library: [
    { title: 'Skills', items: [
      { id: 'sk-1', label: 'sql-analyst' },
      { id: 'sk-2', label: 'data-visualizer' },
      { id: 'sk-3', label: 'web-scraper' },
    ]},
    { title: 'Tools', items: [
      { id: 'tl-1', label: 'sqlite-execute' },
      { id: 'tl-2', label: 'python-execute' },
      { id: 'tl-3', label: 'web-fetch' },
    ]},
    { title: 'Prompts', items: [
      { id: 'pr-1', label: 'System Prompt Base' },
    ]},
  ],
  analysis: [
    { title: 'Dashboards', items: [
      { id: 'db-1', label: 'Sunhing KPI' },
      { id: 'db-2', label: 'Sales Overview' },
    ]},
    { title: 'Data Sources', items: [
      { id: 'ds-1', label: 'sunhing_kpi.db' },
    ]},
  ],
  settings: [], // Settings is full-page, no sidebar
};

export default function LeftSidebar() {
  const { activeActivity, sidebarOpen } = useLayoutState();
  const t = useLayoutTokens();

  if (!sidebarOpen || activeActivity === 'settings') return null;

  const sections = SIDEBAR_DATA[activeActivity];

  return (
    <div
      style={{
        width: 280,
        minWidth: 280,
        background: t.bgBase,
        borderRight: `1px solid ${t.border}`,
        display: 'flex',
        flexDirection: 'column',
        overflowY: 'auto',
        userSelect: 'none',
      }}
    >
      {/* Header */}
      <div
        style={{
          padding: '12px 16px',
          fontSize: 12,
          fontWeight: 600,
          textTransform: 'uppercase',
          letterSpacing: '0.05em',
          color: t.textMuted,
          borderBottom: `1px solid ${t.border}`,
        }}
      >
        {ACTIVITIES.find(a => a.id === activeActivity)?.label}
      </div>

      {/* Sections */}
      {sections.map(section => (
        <div key={section.title}>
          <div
            style={{
              padding: '8px 16px 4px',
              fontSize: 11,
              fontWeight: 600,
              textTransform: 'uppercase',
              letterSpacing: '0.05em',
              color: t.textDim,
            }}
          >
            {section.title}
          </div>
          {section.items.map(item => (
            <div
              key={item.id}
              style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                padding: '4px 16px 4px 20px',
                fontSize: 13,
                color: t.textPrimary,
                cursor: 'pointer',
                borderRadius: 4,
                margin: '0 8px',
              }}
              onMouseEnter={e => { e.currentTarget.style.background = t.bgHover; }}
              onMouseLeave={e => { e.currentTarget.style.background = 'transparent'; }}
            >
              <span>{item.label}</span>
              {item.badge && (
                <span
                  style={{
                    fontSize: 10,
                    padding: '1px 6px',
                    borderRadius: 10,
                    background: t.accentMuted,
                    color: t.accent,
                  }}
                >
                  {item.badge}
                </span>
              )}
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}
