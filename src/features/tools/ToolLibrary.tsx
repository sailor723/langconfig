/**
 * ToolLibrary - Browse all available native tools for deep agents
 *
 * Fetches from /api/tools/registry and displays tools grouped by category.
 * Useful for users to discover what tools are available before creating an agent.
 */

import { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import {
  Search,
  Globe,
  FolderOpen,
  Brain,
  Share2,
  HardDrive,
  Wrench,
  Plus,
  Code,
  Pencil,
  Eye,
  X,
  Copy,
  Check,
  ListTodo,
} from 'lucide-react';
import apiClient from '../../lib/api-client';
import CustomToolBuilder from './ui/CustomToolBuilder';

interface ToolItem {
  id: string;
  name: string;
  description: string;
  category: string;
  requires_api_key: string | null;
}

const CATEGORY_ICONS: Record<string, React.ReactNode> = {
  web: <Globe className="w-5 h-5" />,
  filesystem: <FolderOpen className="w-5 h-5" />,
  memory: <HardDrive className="w-5 h-5" />,
  reasoning: <Brain className="w-5 h-5" />,
  delegation: <Share2 className="w-5 h-5" />,
  todo: <ListTodo className="w-5 h-5" />,
};

// Small avatar-sized versions of category icons
const CATEGORY_AVATAR_ICONS: Record<string, React.ReactNode> = {
  web: <Globe className="w-4 h-4" />,
  filesystem: <FolderOpen className="w-4 h-4" />,
  memory: <HardDrive className="w-4 h-4" />,
  reasoning: <Brain className="w-4 h-4" />,
  delegation: <Share2 className="w-4 h-4" />,
  todo: <ListTodo className="w-4 h-4" />,
};

export default function ToolLibrary() {
  const { t } = useTranslation('chat');

  const CATEGORY_LABELS: Record<string, string> = {
    web: t('tool_library_cat_web'),
    filesystem: t('tool_library_cat_filesystem'),
    memory: t('tool_library_cat_memory'),
    reasoning: t('tool_library_cat_reasoning'),
    delegation: t('tool_library_cat_delegation'),
    todo: t('tool_library_cat_todo', 'TODO Management'),
  };

  const [tools, setTools] = useState<ToolItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState('');
  const [customTools, setCustomTools] = useState<any[]>([]);
  const [showBuilder, setShowBuilder] = useState(false);
  const [editingTool, setEditingTool] = useState<string | null>(null);
  // View-prompt modal state
  const [detailsToolId, setDetailsToolId] = useState<string | null>(null);
  const [detailsTool, setDetailsTool] = useState<any | null>(null);
  const [detailsLoading, setDetailsLoading] = useState(false);
  const [detailsCopied, setDetailsCopied] = useState(false);

  useEffect(() => {
    apiClient.listToolRegistry()
      .then((res: any) => setTools(Array.isArray(res) ? res : res.data || []))
      .catch(console.error)
      .finally(() => setLoading(false));

    // Load custom tools
    apiClient.get('/api/custom-tools')
      .then((res: any) => setCustomTools(Array.isArray(res) ? res : res.data || []))
      .catch(console.error);
  }, []);

  // Fetch LLM-facing prompt + args schema when the user opens the View-Prompt modal
  useEffect(() => {
    if (!detailsToolId) {
      setDetailsTool(null);
      return;
    }
    setDetailsLoading(true);
    setDetailsTool(null);
    setDetailsCopied(false);
    apiClient.getToolDetails(detailsToolId)
      .then((res: any) => setDetailsTool(res?.data || res))
      .catch((err) => {
        console.error('Failed to load tool details:', err);
        setDetailsTool({ error: err?.response?.data?.detail || err?.message || 'Failed to load' });
      })
      .finally(() => setDetailsLoading(false));
  }, [detailsToolId]);

  const openDetails = (toolId: string) => setDetailsToolId(toolId);
  const closeDetails = () => {
    setDetailsToolId(null);
    setDetailsCopied(false);
  };

  const copyToClipboard = async (text: string) => {
    try {
      await navigator.clipboard.writeText(text);
      setDetailsCopied(true);
      setTimeout(() => setDetailsCopied(false), 1500);
    } catch (err) {
      console.error('Copy failed:', err);
    }
  };

  // Group by category
  const grouped = tools.reduce<Record<string, ToolItem[]>>((acc, tool) => {
    const cat = tool.category || 'other';
    if (!acc[cat]) acc[cat] = [];
    acc[cat].push(tool);
    return acc;
  }, {});

  // Filter by search
  const filteredGroups = Object.entries(grouped).reduce<Record<string, ToolItem[]>>((acc, [cat, items]) => {
    const filtered = items.filter(t =>
      !searchQuery ||
      t.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
      t.id.toLowerCase().includes(searchQuery.toLowerCase()) ||
      t.description.toLowerCase().includes(searchQuery.toLowerCase())
    );
    if (filtered.length > 0) acc[cat] = filtered;
    return acc;
  }, {});

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary" />
      </div>
    );
  }

  return (
    <div className="flex-1 overflow-y-auto p-6" style={{ backgroundColor: 'var(--color-background-light, #f8f9fa)' }}>
      {/* Header */}
      <div className="max-w-7xl mx-auto">
        <div className="mb-8">
          <div className="flex items-center gap-3 mb-2">
            <Wrench className="w-8 h-8 text-primary" />
            <h1 className="text-2xl font-bold" style={{ color: 'var(--color-text-primary)' }}>
              {t('tool_library_title')}
            </h1>
          </div>
          <p className="text-sm ml-11" style={{ color: 'var(--color-text-muted)' }}>
            {t('tool_library_desc', { count: tools.length })}{searchQuery && ` ${t('tool_library_showing_results', { query: searchQuery })}`}
          </p>
        </div>

        {/* Search */}
        <div className="relative mb-6 max-w-md">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4" style={{ color: 'var(--color-text-muted)' }} />
          <input
            type="text"
            placeholder={t('tool_library_search_placeholder')}
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="w-full pl-10 pr-4 py-2.5 text-sm border rounded-lg focus:outline-none focus:ring-2 focus:ring-primary"
            style={{
              backgroundColor: 'var(--color-input-background, #fff)',
              color: 'var(--color-text-primary)',
              borderColor: 'var(--color-border-dark, #e5e7eb)',
            }}
          />
        </div>

        {/* Custom Tools Section */}
        {customTools.length > 0 && (
          <section className="mb-8">
            <div className="flex items-center justify-between mb-4">
              <div className="flex items-center gap-2">
                <span className="text-primary">
                  <Code className="w-5 h-5" />
                </span>
                <h2 className="text-lg font-semibold" style={{ color: 'var(--color-text-primary)' }}>
                  {t('tool_library_custom_tools')}
                </h2>
                <span className="text-xs px-2 py-0.5 rounded-full bg-gray-200 dark:bg-gray-700" style={{ color: 'var(--color-text-muted)' }}>
                  {customTools.length}
                </span>
              </div>
              <button
                onClick={() => setShowBuilder(true)}
                className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg transition-colors"
                style={{
                  backgroundColor: 'var(--color-primary)',
                  color: '#fff',
                }}
              >
                <Plus className="w-3.5 h-3.5" />
                {t('tool_library_create_tool')}
              </button>
            </div>
            <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
              {customTools.map((tool: any) => (
                <div
                  key={tool.tool_id || tool.id}
                  className="p-3 rounded-lg border transition-shadow hover:shadow-md group"
                  style={{
                    backgroundColor: 'var(--color-panel-light, #fff)',
                    borderColor: 'var(--color-border-dark, #e5e7eb)',
                  }}
                >
                  <div className="flex items-center gap-2 mb-2">
                    <div className="w-8 h-8 rounded-lg flex items-center justify-center shrink-0" style={{ backgroundColor: 'var(--color-primary-light, rgba(37, 99, 235, 0.1))', color: 'var(--color-primary)' }}>
                      <Code className="w-4 h-4" />
                    </div>
                    <div className="min-w-0 flex-1">
                      <h3 className="font-semibold text-xs truncate" style={{ color: 'var(--color-text-primary)' }}>
                        {tool.name}
                      </h3>
                    </div>
                    <div className="flex items-center gap-1 shrink-0">
                      <button
                        onClick={() => {
                          setEditingTool(tool.tool_id || tool.id);
                          setShowBuilder(true);
                        }}
                        className="p-1 rounded opacity-0 group-hover:opacity-100 transition-opacity hover:bg-gray-200 dark:hover:bg-gray-600"
                        title={t('tool_library_edit_tool')}
                      >
                        <Pencil className="w-3 h-3" style={{ color: 'var(--color-text-muted)' }} />
                      </button>
                    </div>
                  </div>
                  <p className="text-xs mb-2 line-clamp-2" style={{ color: 'var(--color-text-muted)' }}>
                    {tool.description}
                  </p>
                  <div className="flex items-center gap-1.5">
                    <code className="text-xs px-1.5 py-0.5 rounded truncate" style={{
                      backgroundColor: 'var(--color-background-dark, #f3f4f6)',
                      color: 'var(--color-text-secondary, #6b7280)',
                      fontFamily: 'monospace',
                    }}>
                      {tool.tool_id || tool.id}
                    </code>
                    <span className="text-xs px-1.5 py-0.5 rounded-full bg-emerald-100 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-400 font-medium whitespace-nowrap shrink-0 ml-auto">
                      {tool.tool_type || t('tool_library_type_custom')}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          </section>
        )}

        {/* Categories */}
        {Object.entries(filteredGroups).length === 0 && customTools.length === 0 ? (
          <div className="text-center py-16">
            <p className="text-lg" style={{ color: 'var(--color-text-muted)' }}>
              {searchQuery ? t('tool_library_no_match', { query: searchQuery }) : t('tool_library_no_results')}
            </p>
          </div>
        ) : (
          Object.entries(filteredGroups).map(([category, items]) => (
            <section key={category} className="mb-8">
              <div className="flex items-center gap-2 mb-4">
                <span className="text-primary">
                  {CATEGORY_ICONS[category] || <Wrench className="w-5 h-5" />}
                </span>
                <h2 className="text-lg font-semibold" style={{ color: 'var(--color-text-primary)' }}>
                  {CATEGORY_LABELS[category] || category}
                </h2>
                <span className="text-xs px-2 py-0.5 rounded-full bg-gray-200 dark:bg-gray-700" style={{ color: 'var(--color-text-muted)' }}>
                  {items.length}
                </span>
              </div>

              <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
                {items.map(tool => (
                  <div
                    key={tool.id}
                    className="p-3 rounded-lg border transition-shadow hover:shadow-md group"
                    style={{
                      backgroundColor: 'var(--color-panel-light, #fff)',
                      borderColor: 'var(--color-border-dark, #e5e7eb)',
                    }}
                  >
                    <div className="flex items-center gap-2 mb-2">
                      <div className="w-8 h-8 rounded-lg flex items-center justify-center shrink-0" style={{ backgroundColor: 'var(--color-primary-light, rgba(37, 99, 235, 0.1))', color: 'var(--color-primary)' }}>
                        {CATEGORY_AVATAR_ICONS[category] || <Wrench className="w-4 h-4" />}
                      </div>
                      <div className="min-w-0 flex-1">
                        <h3 className="font-semibold text-xs truncate" style={{ color: 'var(--color-text-primary)' }}>
                          {tool.name}
                        </h3>
                      </div>
                      <div className="flex items-center gap-1 shrink-0">
                        {tool.requires_api_key && (
                          <span className="text-xs px-1.5 py-0.5 rounded-full bg-amber-100 dark:bg-amber-900/30 text-amber-700 dark:text-amber-400 font-medium whitespace-nowrap">
                            API
                          </span>
                        )}
                        <button
                          onClick={() => openDetails(tool.id)}
                          className="p-1 rounded opacity-0 group-hover:opacity-100 transition-opacity hover:bg-blue-100 dark:hover:bg-blue-900/30"
                          title="View full LLM-facing prompt and argument schema"
                        >
                          <Eye className="w-3 h-3" style={{ color: 'var(--color-primary)' }} />
                        </button>
                      </div>
                    </div>
                    <p className="text-xs mb-2 line-clamp-2" style={{ color: 'var(--color-text-muted)' }}>
                      {tool.description}
                    </p>
                    <div className="flex items-center gap-1.5 flex-wrap">
                      <code className="text-xs px-1.5 py-0.5 rounded truncate" style={{
                        backgroundColor: 'var(--color-background-dark, #f3f4f6)',
                        color: 'var(--color-text-secondary, #6b7280)',
                        fontFamily: 'monospace',
                      }}>
                        {tool.id}
                      </code>
                      {tool.requires_api_key && (
                        <code className="text-xs px-1.5 py-0.5 rounded truncate shrink-0" style={{
                          backgroundColor: 'var(--color-background-dark, #f3f4f6)',
                          color: 'var(--color-text-secondary, #6b7280)',
                          fontFamily: 'monospace',
                        }}>
                          {tool.requires_api_key}
                        </code>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </section>
          ))
        )}
      </div>

      {/* View-Prompt Modal: shows the full LLM-facing description + args schema */}
      {detailsToolId && (
        <div
          className="fixed inset-0 z-50 flex items-start justify-center pt-10 pb-10 overflow-y-auto"
          style={{ backgroundColor: 'rgba(0,0,0,0.5)' }}
          onClick={closeDetails}
        >
          <div
            className="relative w-full max-w-4xl mx-4 rounded-xl overflow-hidden shadow-2xl"
            style={{ backgroundColor: 'var(--color-background-light, #fff)' }}
            onClick={(e) => e.stopPropagation()}
          >
            {/* Modal header */}
            <div
              className="flex items-center justify-between p-4 border-b"
              style={{ borderColor: 'var(--color-border-dark, #e5e7eb)' }}
            >
              <div className="flex items-center gap-3">
                <Eye className="w-5 h-5" style={{ color: 'var(--color-primary)' }} />
                <div>
                  <h2 className="text-base font-semibold" style={{ color: 'var(--color-text-primary)' }}>
                    {detailsTool?.name || detailsToolId}
                  </h2>
                  <p className="text-xs" style={{ color: 'var(--color-text-muted)' }}>
                    Full LLM-facing prompt · Tool id:{' '}
                    <code style={{ fontFamily: 'monospace' }}>{detailsToolId}</code>
                  </p>
                </div>
              </div>
              <button
                onClick={closeDetails}
                className="p-1.5 rounded hover:bg-gray-200 dark:hover:bg-gray-700"
                title="Close"
              >
                <X className="w-4 h-4" style={{ color: 'var(--color-text-muted)' }} />
              </button>
            </div>

            {/* Modal body */}
            <div className="p-5 max-h-[70vh] overflow-y-auto">
              {detailsLoading && (
                <div className="flex items-center justify-center py-8">
                  <div className="animate-spin rounded-full h-6 w-6 border-b-2 border-primary" />
                </div>
              )}

              {detailsTool?.error && (
                <div className="text-sm p-3 rounded" style={{ backgroundColor: 'rgba(239, 68, 68, 0.1)', color: '#dc2626' }}>
                  {detailsTool.error}
                </div>
              )}

              {detailsTool && !detailsTool.error && (
                <>
                  {/* UI description (short) */}
                  <div className="mb-5">
                    <h3 className="text-xs font-semibold uppercase tracking-wide mb-2" style={{ color: 'var(--color-text-muted)' }}>
                      UI description (human-facing)
                    </h3>
                    <p className="text-sm" style={{ color: 'var(--color-text-primary)' }}>
                      {detailsTool.ui_description}
                    </p>
                  </div>

                  {/* LLM description (long) */}
                  <div className="mb-5">
                    <div className="flex items-center justify-between mb-2">
                      <h3 className="text-xs font-semibold uppercase tracking-wide" style={{ color: 'var(--color-text-muted)' }}>
                        LLM description (sent to model at runtime)
                      </h3>
                      <button
                        onClick={() => copyToClipboard(detailsTool.llm_description || '')}
                        className="flex items-center gap-1.5 px-2 py-1 text-xs rounded hover:bg-gray-200 dark:hover:bg-gray-700"
                        title="Copy to clipboard"
                      >
                        {detailsCopied ? (
                          <>
                            <Check className="w-3.5 h-3.5 text-emerald-600" />
                            <span className="text-emerald-600">Copied</span>
                          </>
                        ) : (
                          <>
                            <Copy className="w-3.5 h-3.5" style={{ color: 'var(--color-text-muted)' }} />
                            <span style={{ color: 'var(--color-text-muted)' }}>Copy</span>
                          </>
                        )}
                      </button>
                    </div>
                    {detailsTool.llm_description ? (
                      <pre
                        className="text-xs whitespace-pre-wrap p-3 rounded"
                        style={{
                          backgroundColor: 'var(--color-background-dark, #f3f4f6)',
                          color: 'var(--color-text-primary)',
                          fontFamily: 'monospace',
                          lineHeight: '1.55',
                        }}
                      >
                        {detailsTool.llm_description}
                      </pre>
                    ) : (
                      <p className="text-xs italic" style={{ color: 'var(--color-text-muted)' }}>
                        (no description — derived from docstring only)
                      </p>
                    )}
                    <p className="text-xs mt-1" style={{ color: 'var(--color-text-muted)' }}>
                      Length: {detailsTool.llm_description?.length || 0} characters
                    </p>
                  </div>

                  {/* Args schema (JSON Schema) */}
                  <div>
                    <h3 className="text-xs font-semibold uppercase tracking-wide mb-2" style={{ color: 'var(--color-text-muted)' }}>
                      Argument schema (what the LLM must produce)
                    </h3>
                    {detailsTool.args_schema && Object.keys(detailsTool.args_schema).length > 0 ? (
                      <pre
                        className="text-xs whitespace-pre-wrap p-3 rounded"
                        style={{
                          backgroundColor: 'var(--color-background-dark, #f3f4f6)',
                          color: 'var(--color-text-primary)',
                          fontFamily: 'monospace',
                          lineHeight: '1.55',
                        }}
                      >
                        {JSON.stringify(detailsTool.args_schema, null, 2)}
                      </pre>
                    ) : (
                      <p className="text-xs italic" style={{ color: 'var(--color-text-muted)' }}>
                        (no arguments — LLM invokes the tool with no payload)
                      </p>
                    )}
                  </div>
                </>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Custom Tool Builder Modal */}
      {showBuilder && (
        <div className="fixed inset-0 z-50 flex items-start justify-center pt-10 pb-10 overflow-y-auto" style={{ backgroundColor: 'rgba(0,0,0,0.5)' }}>
          <div className="relative w-full max-w-3xl mx-4 rounded-xl overflow-hidden shadow-2xl" style={{ backgroundColor: 'var(--color-background-light, #fff)' }}>
            <CustomToolBuilder
              existingToolId={editingTool || undefined}
              onClose={() => {
                setShowBuilder(false);
                setEditingTool(null);
                window.location.reload();
              }}
            />
          </div>
        </div>
      )}
    </div>
  );
}
