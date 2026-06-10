/**
 * ToolLibrary - Browse all available native tools for deep agents
 *
 * Fetches from /api/tools/registry and displays tools grouped by category.
 * Useful for users to discover what tools are available before creating an agent.
 */

import { useState, useEffect } from 'react';
import {
  Search,
  Globe,
  FolderOpen,
  Brain,
  Share2,
  HardDrive,
  Wrench,
} from 'lucide-react';
import apiClient from '../../lib/api-client';

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
};

const CATEGORY_LABELS: Record<string, string> = {
  web: 'Web & Search',
  filesystem: 'File System',
  memory: 'Memory',
  reasoning: 'Reasoning',
  delegation: 'Delegation',
};

export default function ToolLibrary() {
  const [tools, setTools] = useState<ToolItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState('');

  useEffect(() => {
    apiClient.listToolRegistry()
      .then((res: any) => setTools(Array.isArray(res) ? res : res.data || []))
      .catch(console.error)
      .finally(() => setLoading(false));
  }, []);

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
      <div className="max-w-5xl mx-auto">
        <div className="mb-8">
          <div className="flex items-center gap-3 mb-2">
            <Wrench className="w-8 h-8 text-primary" />
            <h1 className="text-2xl font-bold" style={{ color: 'var(--color-text-primary)' }}>
              Tool Library
            </h1>
          </div>
          <p className="text-sm ml-11" style={{ color: 'var(--color-text-muted)' }}>
            {tools.length} native tools available for deep agents. Tools are grouped by category.
            {searchQuery && ` Showing results for "${searchQuery}"`}
          </p>
        </div>

        {/* Search */}
        <div className="relative mb-6 max-w-md">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4" style={{ color: 'var(--color-text-muted)' }} />
          <input
            type="text"
            placeholder="Search tools by name, ID, or description..."
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

        {/* Categories */}
        {Object.entries(filteredGroups).length === 0 ? (
          <div className="text-center py-16">
            <p className="text-lg" style={{ color: 'var(--color-text-muted)' }}>
              {searchQuery ? `No tools matching "${searchQuery}"` : 'No tools found'}
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

              <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                {items.map(tool => (
                  <div
                    key={tool.id}
                    className="p-4 rounded-lg border transition-shadow hover:shadow-md"
                    style={{
                      backgroundColor: 'var(--color-panel-light, #fff)',
                      borderColor: 'var(--color-border-dark, #e5e7eb)',
                    }}
                  >
                    <div className="flex items-start justify-between mb-2">
                      <h3 className="font-semibold text-sm" style={{ color: 'var(--color-text-primary)' }}>
                        {tool.name}
                      </h3>
                      {tool.requires_api_key && (
                        <span className="text-xs px-2 py-0.5 rounded-full bg-amber-100 dark:bg-amber-900/30 text-amber-700 dark:text-amber-400 font-medium whitespace-nowrap ml-2">
                          API Key
                        </span>
                      )}
                    </div>
                    <p className="text-xs mb-2" style={{ color: 'var(--color-text-muted)' }}>
                      {tool.description}
                    </p>
                    <div className="flex items-center gap-2">
                      <code className="text-xs px-1.5 py-0.5 rounded" style={{
                        backgroundColor: 'var(--color-background-dark, #f3f4f6)',
                        color: 'var(--color-text-secondary, #6b7280)',
                        fontFamily: 'monospace',
                      }}>
                        {tool.id}
                      </code>
                      {tool.requires_api_key && (
                        <code className="text-xs px-1.5 py-0.5 rounded" style={{
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
    </div>
  );
}
