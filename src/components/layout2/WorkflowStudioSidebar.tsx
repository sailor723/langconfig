/**
 * WorkflowStudioSidebar — Left sidebar for LangGraph Workflow Studio.
 *
 * Shows only workflows/recipes — Template / Customer Build categories.
 * Built-in recipes: /api/agents/recipes
 * User workflows:   /api/workflows/
 * Agent picker lives in the editor, not here.
 */
import { useState, useEffect } from 'react';
import { useLayoutTokens } from './tokens';
import apiClient from '../../lib/api-client';
import { Layers, Bot, Loader, GitBranch, AlertTriangle } from 'lucide-react';

// ── Types ────────────────────────────────────────────────

interface WorkflowItem {
  id: string | number;
  name: string;
  description: string;
  category: string;  // 'template' | 'custom'
  type: 'recipe' | 'workflow';
}

const CATEGORY_CONFIG: Record<string, { icon: typeof Layers; color: string; label: string }> = {
  template: { icon: Layers, color: '#8b5cf6', label: 'Template' },
  custom:   { icon: Bot,    color: '#f97316', label: 'Customer Build' },
};

// ── Component ────────────────────────────────────────────

interface WorkflowStudioSidebarProps {
  onLoadWorkflow?: (workflowId: number) => void;
  onLoadRecipe?: (recipeId: string) => void;
}

export default function WorkflowStudioSidebar({ onLoadWorkflow, onLoadRecipe }: WorkflowStudioSidebarProps) {
  const t = useLayoutTokens();
  const [items, setItems] = useState<WorkflowItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeCategory, setActiveCategory] = useState<string>('all');

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);

    Promise.all([
      apiClient.apiFetch(`${apiClient.baseURL}/api/agents/recipes`).catch(() => []),
      apiClient.listWorkflows().catch(() => ({ data: [] })),
    ]).then(([recipesRes, wfRes]: any) => {
      if (cancelled) return;

      const recipes: WorkflowItem[] = (Array.isArray(recipesRes) ? recipesRes : []).map((r: any) => ({
        id: r.recipe_id,
        name: r.name,
        description: r.description || '',
        category: 'template' as const,
        type: 'recipe' as const,
      }));

      const workflowData = wfRes?.data ?? [];
      const workflows: WorkflowItem[] = (Array.isArray(workflowData) ? workflowData : []).map((wf: any) => ({
        id: wf.id,
        name: wf.name || `Workflow #${wf.id}`,
        description: wf.description || '',
        category: 'custom' as const,
        type: 'workflow' as const,
      }));

      const seen = new Set(recipes.map(r => r.name));
      setItems([...recipes, ...workflows.filter(w => !seen.has(w.name))]);
    }).catch((err: any) => {
      if (!cancelled) setError(err?.message || 'Failed to load');
    }).finally(() => {
      if (!cancelled) setLoading(false);
    });

    return () => { cancelled = true; };
  }, []);

  const categories = items.length > 0 ? Array.from(new Set(items.map(i => i.category))) : [];

  const filtered = activeCategory === 'all'
    ? items
    : items.filter(i => i.category === activeCategory);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', padding: '8px 0' }}>
      {/* ── Header ── */}
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        padding: '4px 14px 8px',
      }}>
        <span style={{
          fontSize: 11, fontWeight: 600, color: t.textPrimary,
          textTransform: 'uppercase', letterSpacing: '0.5px',
        }}>
          Workflows
        </span>
        <span style={{ fontSize: 10, color: t.textMuted }}>{items.length}</span>
      </div>

      {/* ── Filter pills ── */}
      <div style={{ padding: '0 12px 8px', borderBottom: `1px solid ${t.border}` }}>
        <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap', marginBottom: 6 }}>
          <FilterPill
            active={activeCategory === 'all'}
            label={`All (${items.length})`}
            color={t.accent}
            tokens={t}
            onClick={() => setActiveCategory('all')}
          />
          {categories.map(cat => {
            const cfg = CATEGORY_CONFIG[cat];
            const count = items.filter(i => i.category === cat).length;
            return (
              <FilterPill
                key={cat}
                active={activeCategory === cat}
                label={`${cfg?.label || cat} (${count})`}
                color={cfg?.color || t.accent}
                tokens={t}
                icon={cfg?.icon}
                onClick={() => setActiveCategory(cat)}
              />
            );
          })}
        </div>
      </div>

      {/* ── Workflow list ── */}
      <div style={{ flex: 1, overflowY: 'auto', minHeight: 0, paddingTop: 4 }}>
        {loading ? (
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '16px', fontSize: 12, color: t.textMuted }}>
            <Loader size={13} style={{ animation: 'spin 1s linear infinite' }} />
            Loading...
          </div>
        ) : error ? (
          <div style={{ padding: '16px', fontSize: 12, color: '#e5484d', display: 'flex', alignItems: 'center', gap: 6 }}>
            <AlertTriangle size={13} />
            {error}
          </div>
        ) : filtered.length === 0 ? (
          <div style={{ padding: '16px', fontSize: 12, color: t.textMuted, fontStyle: 'italic' }}>
            {activeCategory === 'all' ? 'No workflows yet' : 'No items in this category'}
          </div>
        ) : (
          <div>
            {filtered.map(item => (
              <WorkflowRow
                key={item.id}
                item={item}
                tokens={t}
                onClick={() => {
                  if (item.type === 'workflow') onLoadWorkflow?.(item.id as number);
                  else onLoadRecipe?.(item.id as string);
                }}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

// ── Filter Pill ──────────────────────────────────────────

function FilterPill({ active, label, color, tokens: t, icon: Icon, onClick }: {
  active: boolean;
  label: string;
  color: string;
  tokens: ReturnType<typeof useLayoutTokens>;
  icon?: typeof Layers;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      style={{
        padding: '3px 8px', fontSize: 10, fontWeight: 500,
        border: `1px solid ${active ? color : t.border}`,
        borderRadius: 10, cursor: 'pointer',
        background: active ? `${color}15` : 'transparent',
        color: active ? color : t.textPrimary,
        display: 'flex', alignItems: 'center', gap: 3,
      }}
    >
      {Icon && <Icon size={10} />}
      {label}
    </button>
  );
}

// ── Workflow Row ─────────────────────────────────────────

function WorkflowRow({ item, tokens: t, onClick }: {
  item: WorkflowItem;
  tokens: ReturnType<typeof useLayoutTokens>;
  onClick: () => void;
}) {
  const [hover, setHover] = useState(false);
  const cfg = CATEGORY_CONFIG[item.category];
  const Icon = cfg?.icon || GitBranch;

  return (
    <div
      onClick={onClick}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      style={{
        display: 'flex', alignItems: 'center', gap: 8,
        padding: '5px 14px', cursor: 'pointer',
        background: hover ? t.bgHover : 'transparent',
        fontSize: 12, color: t.textPrimary,
        borderLeft: hover ? `2px solid ${cfg?.color || t.accent}` : '2px solid transparent',
        userSelect: 'none',
      }}
    >
      <Icon size={13} color={cfg?.color || t.textMuted} style={{ flexShrink: 0 }} />
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', fontWeight: 500 }}>
          {item.name}
        </div>
        <div style={{ fontSize: 10, color: t.textMuted, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
          {item.description || (item.type === 'recipe' ? 'Built-in template' : 'Your workflow')}
        </div>
      </div>
    </div>
  );
}
