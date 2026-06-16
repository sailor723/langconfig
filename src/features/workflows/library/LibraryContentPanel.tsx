/**
 * Copyright (c) 2025 Cade Russell (Ghost Peony)
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useProject } from '@/contexts/ProjectContext';
import LearnLangChainTab from './LearnLangChainTab';
import BestPracticesTab from './BestPracticesTab';
import FilesLibraryTab from './FilesLibraryTab';
import WorkflowDetailedView from './WorkflowDetailedView';
import type { Project, Workflow } from '@/types/workflow';

interface LibraryContentPanelProps {
  activeProject: Project | null;
  onCreateWorkflow: () => void;
  selectedWorkflow?: Workflow | null;
  onOpenStudio?: () => void;
  onDuplicate?: () => void;
  onDelete?: () => void;
  onExportCode?: () => void;
}

export default function LibraryContentPanel({
  activeProject,
  onCreateWorkflow,
  selectedWorkflow,
  onOpenStudio,
  onDuplicate,
  onDelete,
  onExportCode
}: LibraryContentPanelProps) {
  const [activeTab, setActiveTab] = useState<'workflows' | 'projects' | 'files' | 'learn' | 'best-practices'>('workflows');
  const [searchQuery, setSearchQuery] = useState('');
  const { t } = useTranslation('chat');
  const { updateProject } = useProject();

  return (
    <div className="h-full flex flex-col">
      {/* Tab Navigation */}
      <div className="flex-shrink-0 border-b border-gray-200 dark:border-border-dark bg-white dark:bg-panel-dark">
        <div className="flex items-center justify-between px-6 py-4">
          <div className="flex gap-1">
            <button
              onClick={() => setActiveTab('workflows')}
              className={`px-4 py-2 text-sm font-medium rounded-lg transition-colors ${activeTab === 'workflows'
                ? 'bg-primary/10 text-primary'
                : 'text-gray-600 dark:text-text-muted hover:bg-gray-100 dark:hover:bg-white/5'
                }`}
            >
              <span className="flex items-center gap-2">
                <span className="material-symbols-outlined text-base">account_tree</span>
                {t('library_tab_workflows')}
              </span>
            </button>
            <button
              onClick={() => setActiveTab('projects')}
              className={`px-4 py-2 text-sm font-medium rounded-lg transition-colors ${activeTab === 'projects'
                ? 'bg-primary/10 text-primary'
                : 'text-gray-600 dark:text-text-muted hover:bg-gray-100 dark:hover:bg-white/5'
                }`}
            >
              <span className="flex items-center gap-2">
                <span className="material-symbols-outlined text-base">folder</span>
                {t('library_tab_projects')}
              </span>
            </button>
            <button
              onClick={() => setActiveTab('files')}
              className={`px-4 py-2 text-sm font-medium rounded-lg transition-colors ${activeTab === 'files'
                ? 'bg-primary/10 text-primary'
                : 'text-gray-600 dark:text-text-muted hover:bg-gray-100 dark:hover:bg-white/5'
                }`}
            >
              <span className="flex items-center gap-2">
                <span className="material-symbols-outlined text-base">folder_open</span>
                {t('library_tab_files')}
              </span>
            </button>
            <button
              onClick={() => setActiveTab('learn')}
              className={`px-4 py-2 text-sm font-medium rounded-lg transition-colors ${activeTab === 'learn'
                ? 'bg-primary/10 text-primary'
                : 'text-gray-600 dark:text-text-muted hover:bg-gray-100 dark:hover:bg-white/5'
                }`}
            >
              <span className="flex items-center gap-2">
                <span className="material-symbols-outlined text-base">school</span>
                {t('library_tab_learn')}
              </span>
            </button>
            <button
              onClick={() => setActiveTab('best-practices')}
              className={`px-4 py-2 text-sm font-medium rounded-lg transition-colors ${activeTab === 'best-practices'
                ? 'bg-primary/10 text-primary'
                : 'text-gray-600 dark:text-text-muted hover:bg-gray-100 dark:hover:bg-white/5'
                }`}
            >
              <span className="flex items-center gap-2">
                <span className="material-symbols-outlined text-base">lightbulb</span>
                {t('library_tab_best_practices')}
              </span>
            </button>
          </div>

          {/* Search - only show on learn, best practices, and files tabs */}
          {(activeTab === 'learn' || activeTab === 'best-practices') && (
            <div className="relative">
              <span
                className="material-symbols-outlined absolute left-3 top-1/2 -translate-y-1/2 text-base pointer-events-none"
                style={{ color: 'var(--color-text-muted)' }}
              >
                search
              </span>
              <input
                type="text"
                placeholder={t('library_search_content')}
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="pl-10 pr-4 py-1.5 text-sm border rounded-lg w-64 focus:outline-none focus:ring-2 focus:ring-primary"
                style={{
                  backgroundColor: 'var(--color-input-background)',
                  borderColor: 'var(--color-border-dark)',
                  color: 'var(--color-text-primary)'
                }}
              />
            </div>
          )}
        </div>
      </div>

      {/* Tab Content */}
      <div className="flex-1 overflow-hidden">
        {activeTab === 'workflows' && (
          selectedWorkflow && onOpenStudio && onDuplicate && onDelete && onExportCode ? (
            <WorkflowDetailedView
              workflow={selectedWorkflow}
              onOpenStudio={onOpenStudio}
              onDuplicate={onDuplicate}
              onDelete={onDelete}
              onExportCode={onExportCode}
            />
          ) : (
            <div className="h-full flex items-center justify-center p-6 overflow-y-auto">
              <div className="space-y-8 max-w-6xl w-full">
                {/* Welcome Header */}
                <div className="text-center pt-8 pb-4">
                  <h1 className="text-3xl font-bold mb-2" style={{ color: 'var(--color-text-primary)' }}>
                    {t('library_welcome_title')}
                  </h1>
                  <p className="text-base" style={{ color: 'var(--color-text-muted)' }}>
                    {t('library_welcome_subtitle')}
                  </p>
                </div>

                {/* Four Main Features - Equal Weight Grid */}
                <div className="grid grid-cols-2 gap-5">
                  {/* Projects Card */}
                  <button
                    onClick={() => setActiveTab('projects')}
                    className="group p-6 rounded-lg border border-gray-200 dark:border-border-dark bg-white dark:bg-panel-dark hover:bg-primary/5 hover:border-primary/20 transition-all text-left"
                  >
                    <div className="flex items-start gap-4 mb-4">
                      <div className="w-12 h-12 rounded-lg bg-gray-100 dark:bg-background-dark border border-gray-200 dark:border-border-dark flex items-center justify-center flex-shrink-0">
                        <span className="material-symbols-outlined text-2xl text-primary">folder</span>
                      </div>
                      <div className="flex-1">
                        <h3 className="text-lg font-bold mb-2" style={{ color: 'var(--color-text-primary)' }}>
                          {t('library_feature_projects')}
                        </h3>
                        <p className="text-sm leading-relaxed" style={{ color: 'var(--color-text-muted)' }}>
                          {t('library_feature_projects_desc')}
                        </p>
                      </div>
                    </div>
                    <div className="flex items-center gap-2 text-sm font-medium text-primary">
                      {t('library_feature_projects_cta')}
                      <span className="material-symbols-outlined text-base group-hover:translate-x-1 transition-transform">arrow_forward</span>
                    </div>
                  </button>

                  {/* Workflows Card */}
                  <button
                    onClick={onCreateWorkflow}
                    className="group p-6 rounded-lg border border-gray-200 dark:border-border-dark bg-white dark:bg-panel-dark hover:bg-primary/5 hover:border-primary/20 transition-all text-left"
                  >
                    <div className="flex items-start gap-4 mb-4">
                      <div className="w-12 h-12 rounded-lg bg-gray-100 dark:bg-background-dark border border-gray-200 dark:border-border-dark flex items-center justify-center flex-shrink-0">
                        <span className="material-symbols-outlined text-2xl text-primary">account_tree</span>
                      </div>
                      <div className="flex-1">
                        <h3 className="text-lg font-bold mb-2" style={{ color: 'var(--color-text-primary)' }}>
                          {t('library_feature_workflows')}
                        </h3>
                        <p className="text-sm leading-relaxed" style={{ color: 'var(--color-text-muted)' }}>
                          {t('library_feature_workflows_desc')}
                        </p>
                      </div>
                    </div>
                    <div className="flex items-center gap-2 text-sm font-medium text-primary">
                      {t('library_feature_workflows_cta')}
                      <span className="material-symbols-outlined text-base group-hover:translate-x-1 transition-transform">arrow_forward</span>
                    </div>
                  </button>

                  {/* Learn LangChain Card */}
                  <button
                    onClick={() => setActiveTab('learn')}
                    className="group p-6 rounded-lg border border-gray-200 dark:border-border-dark bg-white dark:bg-panel-dark hover:bg-primary/5 hover:border-primary/20 transition-all text-left"
                  >
                    <div className="flex items-start gap-4 mb-4">
                      <div className="w-12 h-12 rounded-lg bg-gray-100 dark:bg-background-dark border border-gray-200 dark:border-border-dark flex items-center justify-center flex-shrink-0">
                        <span className="material-symbols-outlined text-2xl text-primary">school</span>
                      </div>
                      <div className="flex-1">
                        <h3 className="text-lg font-bold mb-2" style={{ color: 'var(--color-text-primary)' }}>
                          {t('library_feature_learn')}
                        </h3>
                        <p className="text-sm leading-relaxed" style={{ color: 'var(--color-text-muted)' }}>
                          {t('library_feature_learn_desc')}
                        </p>
                      </div>
                    </div>
                    <div className="flex items-center gap-2 text-sm font-medium text-primary">
                      {t('library_feature_learn_cta')}
                      <span className="material-symbols-outlined text-base group-hover:translate-x-1 transition-transform">arrow_forward</span>
                    </div>
                  </button>

                  {/* Best Practices Card */}
                  <button
                    onClick={() => setActiveTab('best-practices')}
                    className="group p-6 rounded-lg border border-gray-200 dark:border-border-dark bg-white dark:bg-panel-dark hover:bg-primary/5 hover:border-primary/20 transition-all text-left"
                  >
                    <div className="flex items-start gap-4 mb-4">
                      <div className="w-12 h-12 rounded-lg bg-gray-100 dark:bg-background-dark border border-gray-200 dark:border-border-dark flex items-center justify-center flex-shrink-0">
                        <span className="material-symbols-outlined text-2xl text-primary">workspace_premium</span>
                      </div>
                      <div className="flex-1">
                        <h3 className="text-lg font-bold mb-2" style={{ color: 'var(--color-text-primary)' }}>
                          {t('library_feature_best')}
                        </h3>
                        <p className="text-sm leading-relaxed" style={{ color: 'var(--color-text-muted)' }}>
                          {t('library_feature_best_desc')}
                        </p>
                      </div>
                    </div>
                    <div className="flex items-center gap-2 text-sm font-medium text-primary">
                      {t('library_feature_best_cta')}
                      <span className="material-symbols-outlined text-base group-hover:translate-x-1 transition-transform">arrow_forward</span>
                    </div>
                  </button>
                </div>

                {/* Active Project Info (if project selected) */}
                {activeProject && (
                  <div className="p-5 rounded-lg border border-gray-200 dark:border-border-dark bg-white dark:bg-panel-dark">
                    <div className="flex items-start gap-4">
                      <div className="w-12 h-12 rounded-lg bg-gray-100 dark:bg-background-dark border border-gray-200 dark:border-border-dark flex items-center justify-center flex-shrink-0">
                        <span className="material-symbols-outlined text-2xl text-primary">folder</span>
                      </div>
                      <div className="flex-1">
                        <div className="flex items-center gap-2 mb-1">
                          <h3 className="text-base font-semibold" style={{ color: 'var(--color-text-primary)' }}>
                            {t('library_active_project', { name: activeProject.name })}
                          </h3>
                          {activeProject.status === 'active' && (
                            <span className="px-2 py-0.5 text-xs font-medium rounded-full bg-green-100 dark:bg-green-500/20 text-green-700 dark:text-green-400">
                              {t('library_active_badge')}
                            </span>
                          )}
                        </div>
                        {activeProject.description && (
                          <p className="text-sm mb-2" style={{ color: 'var(--color-text-muted)' }}>
                            {activeProject.description}
                          </p>
                        )}
                        <div className="flex items-center gap-4 text-xs">
                          <div className="flex items-center gap-1">
                            <span className="material-symbols-outlined text-sm" style={{ color: 'var(--color-text-muted)' }}>
                              description
                            </span>
                            <span style={{ color: 'var(--color-text-muted)' }}>
                              {t('library_indexed_docs', { count: activeProject.indexed_nodes_count || 0 })}
                            </span>
                          </div>
                          {activeProject.project_path && (
                            <div className="flex items-center gap-1">
                              <span className="material-symbols-outlined text-sm" style={{ color: 'var(--color-text-muted)' }}>
                                folder
                              </span>
                              <span style={{ color: 'var(--color-text-muted)' }} className="truncate max-w-[200px]">
                                {activeProject.project_path}
                              </span>
                            </div>
                          )}
                        </div>
                      </div>
                      <button
                        onClick={() => {
                          const newName = prompt('Rename project:', activeProject.name);
                          if (newName && newName.trim() && newName !== activeProject.name) {
                            updateProject(activeProject.id, { name: newName.trim() });
                          }
                        }}
                        className="p-1.5 rounded-lg hover:bg-gray-100 dark:hover:bg-white/10 transition-colors flex-shrink-0 self-start"
                        title="Rename project"
                      >
                        <span className="material-symbols-outlined text-sm" style={{ color: 'var(--color-text-muted)' }}>edit</span>
                      </button>
                    </div>
                  </div>
                )}

                {/* Quick Tip */}
                <div className="p-4 rounded-lg border border-blue-200 dark:border-blue-500/30 bg-blue-50 dark:bg-blue-500/10">
                  <div className="flex gap-3">
                    <span className="material-symbols-outlined text-blue-600 dark:text-blue-400 flex-shrink-0 text-xl">tips_and_updates</span>
                    <div>
                      <h4 className="text-sm font-semibold mb-2 text-blue-800 dark:text-blue-300">
                                                {t('library_tip_title')}
                      </h4>
                      <p className="text-sm text-blue-700 dark:text-blue-400/90 leading-relaxed">
                        Start with the "Learn LangChain" tab to understand core concepts, then check out "Best Practices" for production-ready patterns. When you're ready, create your first workflow and experiment with different agent configurations!
                      </p>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          )
        )}

        {activeTab === 'projects' && (
          <div className="h-full flex items-center justify-center p-6 overflow-y-auto">
            <div className="text-center max-w-2xl">
              <div className="w-16 h-16 mx-auto mb-4 rounded-lg bg-primary/10 flex items-center justify-center">
                <span className="material-symbols-outlined text-3xl text-primary">folder</span>
              </div>
              <h2 className="text-2xl font-bold mb-3" style={{ color: 'var(--color-text-primary)' }}>
                Projects
              </h2>
              <p className="text-base mb-6" style={{ color: 'var(--color-text-muted)' }}>
                Project management features are currently being developed. Soon you'll be able to create projects, organize workflows, manage knowledge bases, and track project-wide metrics.
              </p>
              {activeProject && (
                <div className="inline-block p-4 rounded-lg border" style={{
                  borderColor: 'var(--color-border-dark)',
                  backgroundColor: 'var(--color-panel-dark)'
                }}>
                  <p className="text-sm" style={{ color: 'var(--color-text-muted)' }}>
                    Active Project: <span className="font-semibold" style={{ color: 'var(--color-text-primary)' }}>{activeProject.name}</span>
                  </p>
                </div>
              )}
            </div>
          </div>
        )}

        {activeTab === 'files' && <FilesLibraryTab />}
        {activeTab === 'learn' && <LearnLangChainTab />}
        {activeTab === 'best-practices' && <BestPracticesTab />}
      </div>
    </div>
  );
}
