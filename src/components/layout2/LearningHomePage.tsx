/**
 * LearningHomePage — the right-hand pane of the Learning activity.
 *
 * The activity existed in the ActivityBar, its sidebar (`NotebookSidebar`) listed the course
 * notebooks from `/api/notebooks` and opened them as workspace tabs — but nothing was ever rendered
 * in the main pane for the `learning` view: `ROUTE_TO_VIEW` mapped `/learning → 'learning'` and the
 * `switch` had no `case`, so the activity silently showed the home page. A reader who clicked Learning
 * saw the product tour and concluded the section was empty.
 *
 * So this is not a new feature: it is the landing page that was missing, and it lists exactly what the
 * sidebar lists, from the same endpoint, with the same tab-opening call.
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { BookOpen, ChevronRight, Loader2, RefreshCw } from 'lucide-react';
import { useLayoutTokens } from './tokens';
import { useLayoutState, type Tab } from './useLayout';
import { Btn, Card, Quiet, SUCCESS, WARN } from '../../features/ontology/ui';
import apiClient from '../../lib/api-client';

interface NotebookSummary {
  module: string;
  name: string;
  display_name: string;
  cell_count: number;
  path: string;
}

export default function LearningHomePage() {
  const t = useLayoutTokens();
  const { openTab } = useLayoutState();
  const [notebooks, setNotebooks] = useState<NotebookSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setNotebooks(null); setError(null);
    try {
      const res: any = await apiClient.get('/api/notebooks');
      setNotebooks(Array.isArray(res.data) ? res.data : []);
    } catch (err: any) {
      setNotebooks([]);
      setError(String(err?.response?.data?.detail || err?.message || err));
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  const byModule = useMemo(() => {
    const groups = new Map<string, NotebookSummary[]>();
    for (const nb of notebooks || []) {
      const list = groups.get(nb.module) || [];
      list.push(nb);
      groups.set(nb.module, list);
    }
    return [...groups.entries()].sort((a, b) => a[0].localeCompare(b[0], 'zh-Hans-CN'));
  }, [notebooks]);

  const open = (nb: NotebookSummary) => {
    const tab: Tab = {
      id: `notebook-${nb.module}-${nb.name}`,
      label: nb.display_name || nb.name,
      viewType: 'notebook',
      data: { module: nb.module, name: nb.name, notebook: nb },
    };
    openTab(tab);
  };

  return (
    <div style={{ padding: '18px 20px', maxWidth: 1000, margin: '0 auto', display: 'flex', flexDirection: 'column', gap: 14 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <BookOpen size={16} color={t.accent} />
        <span style={{ fontSize: 16, fontWeight: 600, color: t.textPrimary }}>Learning</span>
        <span style={{ fontSize: 12, color: t.textDim }}>
          {notebooks === null ? '正在读 /api/notebooks…' : `${notebooks.length} 个 notebook · ${byModule.length} 个模块`}
        </span>
        <Btn onClick={() => void load()} title="重新读取 /api/notebooks">
          <RefreshCw size={11} /> 刷新
        </Btn>
      </div>

      <Quiet>
        课程 notebook 由后端 <code style={{ fontFamily: 'ui-monospace, Menlo, monospace' }}>/api/notebooks</code> 提供；
        点一行就在工作区打开成一个页签，左侧栏（Notebook）列的是同一份清单。
      </Quiet>

      {error && (
        <Card style={{ borderColor: `${WARN}66` }}>
          <span style={{ fontSize: 12.5, color: t.textPrimary }}>读不到 notebook 清单：{error}</span>
        </Card>
      )}

      {notebooks === null && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12.5, color: t.textMuted }}>
          <Loader2 size={13} className="animate-spin" /> 读取中…
        </div>
      )}

      {notebooks !== null && notebooks.length === 0 && !error && (
        <Card>
          <span style={{ fontSize: 12.5, color: t.textPrimary }}>
            这个安装里没有 notebook（<code style={{ fontFamily: 'ui-monospace, Menlo, monospace' }}>backend/notebooks/</code> 是空的或被忽略）。
          </span>
        </Card>
      )}

      {byModule.map(([mod, list]) => (
        <Card key={mod} style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <span style={{ fontSize: 13, fontWeight: 600, color: t.textPrimary }}>{mod}</span>
            <span style={{ fontSize: 11, color: t.textDim }}>{list.length} 个</span>
          </div>
          {list.map(nb => (
            <button
              key={`${nb.module}-${nb.name}`}
              onClick={() => open(nb)}
              style={{
                display: 'flex', alignItems: 'center', gap: 8, width: '100%', textAlign: 'left',
                padding: '6px 8px', borderRadius: 8, cursor: 'pointer',
                border: `1px solid ${t.border}`, background: 'transparent', color: t.textPrimary,
              }}
              title={nb.path}
            >
              <BookOpen size={12} color={t.accent} />
              <span style={{ fontSize: 12.5 }}>{nb.display_name || nb.name}</span>
              <span style={{ fontSize: 11, color: t.textDim }}>
                {nb.cell_count ? `${nb.cell_count} cells` : ''}
              </span>
              <ChevronRight size={12} style={{ marginLeft: 'auto', color: SUCCESS }} />
            </button>
          ))}
        </Card>
      ))}
    </div>
  );
}
