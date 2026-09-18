/**
 * Copyright (c) 2025 Cade Russell (Ghost Peony)
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */

import { memo } from 'react';
import { Plus, Save, History as HistoryIcon, Settings, FolderOpen, Image, Loader, Bot } from 'lucide-react';

interface WorkflowVersion {
  id: number;
  version_number: number;
  created_at: string;
  notes?: string;
  is_current?: boolean;
  created_by?: string;
}

type Tab = 'studio' | 'results' | 'files' | 'artifacts' | 'settings';

interface WorkflowToolbarProps {
  // Workflow name editing
  workflowName: string;
  editedName: string;
  setEditedName: (name: string) => void;
  isEditingName: boolean;
  setIsEditingName: (editing: boolean) => void;
  handleWorkflowNameSave: () => void;
  handleStartEditingName: (e: React.MouseEvent) => void;

  // Agent template dropdown (replaces old workflow switcher dropdown)
  showAgentDropdown: boolean;
  handleToggleAgentDropdown: () => void;
  handleCloseAgentDropdown: () => void;
  agentSearchQuery: string;
  handleAgentSearchChange: (e: React.ChangeEvent<HTMLInputElement>) => void;
  filteredAgentTemplates: any[];
  agentTemplatesLoading: boolean;
  onPickAgentTemplate: (template: any) => void;

  // Save/Version actions
  handleSave: (silent?: boolean) => void;
  handleSaveVersion: () => void;

  // Version dropdown
  showVersionDropdown: boolean;
  setShowVersionDropdown: (show: boolean) => void;
  currentVersion: WorkflowVersion | null;
  versions: WorkflowVersion[];
  loadingVersions: boolean;
  handleLoadVersion: (versionNumber: number) => void;

  // Tabs (merged from TabNavigation)
  activeTab: Tab;
  onTabChange: (tab: Tab) => void;
  taskHistoryCount: number;
  filesCount: number;
  artifactsCount: number;
  hasUnsavedChanges: boolean;
}

/**
 * Main toolbar component for the workflow canvas.
 * Shows workflow name (non-clickable) + Add Agent dropdown + Save + Versions + Tabs.
 */
const WorkflowToolbar = memo(function WorkflowToolbar({
  workflowName,
  editedName,
  setEditedName,
  isEditingName,
  setIsEditingName,
  handleWorkflowNameSave,
  handleStartEditingName,
  // Agent template dropdown
  showAgentDropdown,
  handleToggleAgentDropdown,
  handleCloseAgentDropdown,
  agentSearchQuery,
  handleAgentSearchChange,
  filteredAgentTemplates,
  agentTemplatesLoading,
  onPickAgentTemplate,
  // Save/Version
  handleSave,
  handleSaveVersion,
  showVersionDropdown,
  setShowVersionDropdown,
  currentVersion,
  versions,
  loadingVersions,
  handleLoadVersion,
  // Tabs
  activeTab,
  onTabChange,
  taskHistoryCount,
  filesCount,
  artifactsCount,
  hasUnsavedChanges,
}: WorkflowToolbarProps) {
  const tabClass = (tab: Tab) =>
    `px-4 py-2 text-sm font-semibold border-b-2 transition-all ${
      activeTab === tab
        ? 'border-primary text-primary'
        : 'border-transparent text-gray-600 dark:text-text-muted hover:text-gray-900 dark:hover:text-white'
    }`;

  return (
    <div className="bg-white dark:bg-panel-dark border-b border-gray-200 dark:border-border-dark px-4 py-1.5">
      <div className="flex items-center">
        {/* LEFT SECTION: Workflow Name + Add Agent + Save + Versions + Tabs */}
        <div className="flex items-center gap-2">
          {/* Workflow Name (static label, double-click to rename) */}
          <div className="relative flex items-center">
            {isEditingName ? (
              <input
                type="text"
                value={editedName}
                onChange={(e) => setEditedName(e.target.value)}
                onBlur={handleWorkflowNameSave}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') handleWorkflowNameSave();
                  if (e.key === 'Escape') {
                    setEditedName(workflowName);
                    setIsEditingName(false);
                  }
                }}
                autoFocus
                className="px-2 py-1.5 text-sm font-semibold bg-white dark:bg-background-dark border border-primary rounded-lg focus:outline-none focus:ring-2 focus:ring-primary"
                style={{ color: 'var(--color-text-primary, #1a1a1a)', minWidth: '180px' }}
              />
            ) : (
              <span
                onDoubleClick={handleStartEditingName}
                className="px-2 py-1.5 text-sm font-semibold rounded-lg cursor-text"
                style={{ color: 'var(--color-text-primary)' }}
                title="Double-click to rename"
              >
                {workflowName}
              </span>
            )}
          </div>

          {/* Add Agent dropdown */}
          <div className="relative">
            <button
              onClick={handleToggleAgentDropdown}
              className="inline-flex items-center gap-1 px-2.5 py-1.5 text-sm font-medium bg-primary text-white rounded-lg hover:opacity-90 transition-opacity"
              title="Add agent template to canvas"
            >
              <Plus className="w-3.5 h-3.5" />
              <span>Agent</span>
            </button>

            {/* Agent Template Dropdown */}
            {showAgentDropdown && (
              <>
                <div className="fixed inset-0 z-40" onClick={handleCloseAgentDropdown} />
                <div
                  className="absolute top-full left-0 mt-1 w-72 rounded-lg shadow-xl z-50 max-h-96 overflow-hidden flex flex-col border"
                  style={{ backgroundColor: 'var(--color-panel-dark)', borderColor: 'var(--color-border-dark)' }}
                >
                  <div className="p-3 border-b" style={{ borderColor: 'var(--color-border-dark)' }}>
                    <input
                      type="text"
                      placeholder="Search agents..."
                      value={agentSearchQuery}
                      onChange={handleAgentSearchChange}
                      className="w-full px-3 py-2 text-sm rounded-lg border focus:outline-none focus:ring-2 transition-all"
                      style={{ backgroundColor: 'var(--color-background-light)', borderColor: 'var(--color-border-dark)', color: 'var(--color-text-primary)' }}
                    />
                  </div>
                  <div className="overflow-y-auto flex-1">
                    {agentTemplatesLoading ? (
                      <div className="p-4 text-center text-sm" style={{ color: 'var(--color-text-muted)' }}>
                        <Loader size={14} className="inline animate-spin mr-2" />
                        Loading...
                      </div>
                    ) : filteredAgentTemplates.length === 0 ? (
                      <div className="p-4 text-center text-sm" style={{ color: 'var(--color-text-muted)' }}>
                        No agents found
                      </div>
                    ) : (
                      filteredAgentTemplates.map((template: any) => (
                        <button
                          key={template.id}
                          onClick={() => onPickAgentTemplate(template)}
                          className="w-full px-3 py-2.5 text-left transition-colors border-b last:border-0 flex items-center gap-2"
                          style={{
                            borderColor: 'var(--color-border-dark)',
                          }}
                          onMouseEnter={(e) => { e.currentTarget.style.backgroundColor = 'var(--color-background-light, rgba(255, 255, 255, 0.03))'; }}
                          onMouseLeave={(e) => { e.currentTarget.style.backgroundColor = 'transparent'; }}
                        >
                          <Bot size={14} style={{ flexShrink: 0, opacity: 0.6 }} />
                          <div className="flex-1 min-w-0">
                            <div
                              className="font-semibold text-sm leading-tight"
                              style={{
                                color: 'var(--color-text-primary)',
                                wordBreak: 'break-word', overflowWrap: 'break-word',
                                display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical', overflow: 'hidden'
                              }}
                            >
                              {template.name}
                            </div>
                            {template.description && (
                              <div className="text-xs mt-0.5" style={{ color: 'var(--color-text-muted)' }}>
                                {template.description}
                              </div>
                            )}
                          </div>
                          <Plus size={12} className="flex-shrink-0" style={{ color: 'var(--color-primary)' }} />
                        </button>
                      ))
                    )}
                  </div>
                </div>
              </>
            )}
          </div>

          {/* Save Button */}
          <button
            onClick={() => handleSave(false)}
            className="px-3 py-1.5 rounded-lg transition-all hover:opacity-90 bg-primary text-white flex items-center gap-1.5 text-sm font-medium"
            title="Save workflow"
          >
            <Save className="w-4 h-4" />
            <span>Save</span>
          </button>

          {/* Versions Dropdown - Compact with integrated snapshot */}
          <div className="relative">
            <button
              onClick={() => setShowVersionDropdown(!showVersionDropdown)}
              className="inline-flex items-center gap-1.5 px-2 py-1.5 text-sm font-medium bg-white dark:bg-background-dark border border-gray-300 dark:border-border-dark rounded-lg hover:bg-gray-50 dark:hover:bg-white/5 transition-colors"
              style={{ color: 'var(--color-text-primary)' }}
              title="Versions"
            >
              <HistoryIcon className="w-4 h-4" />
              <span>{currentVersion ? `v${currentVersion.version_number}` : 'v1'}</span>
              <span className="text-xs opacity-60">▼</span>
            </button>

            {showVersionDropdown && (
              <>
                <div className="fixed inset-0 z-40" onClick={() => setShowVersionDropdown(false)} />
                <div className="absolute top-full mt-1 left-0 w-72 bg-white dark:bg-panel-dark border border-gray-200 dark:border-border-dark rounded-lg shadow-xl z-50 max-h-80 overflow-hidden flex flex-col">
                  {/* Create Snapshot at top */}
                  <div className="p-2 border-b border-gray-200 dark:border-border-dark">
                    <button
                      onClick={() => { handleSaveVersion(); setShowVersionDropdown(false); }}
                      className="w-full px-3 py-2 text-sm font-medium text-white bg-primary rounded-lg hover:opacity-90 transition-opacity flex items-center justify-center gap-2"
                    >
                      <CameraIcon />
                      Create Snapshot
                    </button>
                  </div>

                  {/* Version List */}
                  <div className="overflow-y-auto flex-1">
                    {loadingVersions ? (
                      <div className="p-4 text-center text-gray-500 dark:text-gray-400 text-sm">Loading...</div>
                    ) : versions.length === 0 ? (
                      <div className="p-4 text-center text-gray-500 dark:text-gray-400 text-sm">
                        No snapshots yet
                      </div>
                    ) : (
                      versions.map((version) => (
                        <button
                          key={version.id}
                          onClick={() => { handleLoadVersion(version.version_number); setShowVersionDropdown(false); }}
                          className={`w-full px-3 py-2.5 text-left hover:bg-gray-50 dark:hover:bg-white/5 transition-colors border-b last:border-0 border-l-4 ${
                            version.is_current ? 'border-l-green-500 bg-green-50/50 dark:bg-green-900/20' : 'border-l-transparent'
                          }`}
                          style={{ borderBottomColor: 'var(--color-border-dark)' }}
                        >
                          <div className="flex items-center justify-between">
                            <span className="text-sm font-semibold text-gray-900 dark:text-white">
                              v{version.version_number}
                              {version.is_current && (
                                <span className="ml-2 px-1.5 py-0.5 text-xs bg-green-500 text-white rounded">Current</span>
                              )}
                            </span>
                            <span className="text-xs text-gray-500 dark:text-gray-400">
                              {new Date(version.created_at).toLocaleDateString()}
                            </span>
                          </div>
                          {version.notes && (
                            <p className="text-xs text-gray-600 dark:text-gray-400 mt-1 line-clamp-1">{version.notes}</p>
                          )}
                        </button>
                      ))
                    )}
                  </div>
                </div>
              </>
            )}
          </div>

          {/* Tabs */}
          <div className="flex items-center">
            <button onClick={() => onTabChange('studio')} className={tabClass('studio')}>
              Studio
            </button>
            <button onClick={() => onTabChange('results')} className={tabClass('results')}>
              Results {taskHistoryCount > 0 && <span className="ml-1 text-xs opacity-70">({taskHistoryCount})</span>}
            </button>
            <button onClick={() => onTabChange('files')} className={`${tabClass('files')} flex items-center gap-1.5`}>
              <FolderOpen className="w-4 h-4" />
              Files {filesCount > 0 && <span className="text-xs opacity-70">({filesCount})</span>}
            </button>
            <button onClick={() => onTabChange('artifacts')} className={`${tabClass('artifacts')} flex items-center gap-1.5`}>
              <Image className="w-4 h-4" />
              Artifacts {artifactsCount > 0 && <span className="text-xs opacity-70">({artifactsCount})</span>}
            </button>
            <button onClick={() => onTabChange('settings')} className={`${tabClass('settings')} flex items-center gap-1.5`}>
              <Settings className="w-4 h-4" />
              Settings
            </button>
          </div>
        </div>

        {/* SPACER */}
        <div className="flex-1" />

        {/* RIGHT SECTION: Status indicators */}
        <div className="flex items-center gap-3">
          {/* Unsaved Changes Indicator */}
          {hasUnsavedChanges && (
            <div className="flex items-center gap-1.5 text-xs font-medium text-yellow-600 dark:text-yellow-500 animate-pulse">
              <span className="material-symbols-outlined" style={{ fontSize: '14px' }}>warning</span>
              <span>Unsaved</span>
            </div>
          )}
        </div>
      </div>
    </div>
  );
});

export default WorkflowToolbar;

/** Inline Camera icon to avoid extra lucide-react import */
function CameraIcon() {
  return (
    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M3 9a2 2 0 012-2h.93a2 2 0 001.664-.89l.812-1.22A2 2 0 0110.07 4h3.86a2 2 0 011.664.89l.812 1.22A2 2 0 0018.07 7H19a2 2 0 012 2v9a2 2 0 01-2 2H5a2 2 0 01-2-2V9z" />
      <path strokeLinecap="round" strokeLinejoin="round" d="M15 13a3 3 0 11-6 0 3 3 0 016 0z" />
    </svg>
  );
}
