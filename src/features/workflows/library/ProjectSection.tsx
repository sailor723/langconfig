/**
 * Copyright (c) 2025 Cade Russell (Ghost Peony)
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import WorkflowContextMenu from './WorkflowContextMenu';
import type { Workflow, Project } from '@/types/workflow';

interface ProjectSectionProps {
  project: Project;
  workflows: Workflow[];
  isExpanded: boolean;
  isActive?: boolean;
  selectedWorkflowId: number | null;
  onToggle: () => void;
  onSelectWorkflow: (workflow: Workflow) => void;
  onRenameWorkflow: (workflow: Workflow) => void;
  onDuplicateWorkflow: (workflow: Workflow) => void;
  onChangeProjectWorkflow: (workflow: Workflow) => void;
  onDeleteWorkflow: (workflow: Workflow) => void;
}

export default function ProjectSection({
  project,
  workflows,
  isExpanded,
  isActive = false,
  selectedWorkflowId,
  onToggle,
  onSelectWorkflow,
  onRenameWorkflow,
  onDuplicateWorkflow,
  onChangeProjectWorkflow,
  onDeleteWorkflow
}: ProjectSectionProps) {
  const { t } = useTranslation('chat');
  const [contextMenu, setContextMenu] = useState<{
    x: number;
    y: number;
    workflow: Workflow;
  } | null>(null);

  const handleContextMenu = (e: React.MouseEvent, workflow: Workflow) => {
    e.preventDefault();
    setContextMenu({
      x: e.clientX,
      y: e.clientY,
      workflow
    });
  };

  return (
    <div className="mb-2">
      {/* Project Header */}
      <button
        onClick={onToggle}
        className={`w-full flex items-center gap-3 px-4 py-3 rounded-lg transition-colors ${isActive
          ? 'bg-primary/10'
          : 'bg-gray-50 dark:bg-white/5 hover:bg-gray-100 dark:hover:bg-white/10'
          }`}
      >
        {/* Expand/Collapse Icon */}
        <span
          className={`material-symbols-outlined text-lg transition-transform ${isExpanded ? 'rotate-90' : ''
            }`}
          style={{ color: 'var(--color-text-muted)' }}
        >
          chevron_right
        </span>

        {/* Project Icon */}
        <div
          className={`w-8 h-8 rounded-lg flex items-center justify-center ${isActive ? 'bg-primary/20' : 'bg-gray-100 dark:bg-white/5'
            }`}
        >
          <span
            className="material-symbols-outlined text-base"
            style={{ color: isActive ? 'var(--color-primary)' : 'var(--color-text-muted)' }}
          >
            folder
          </span>
        </div>

        {/* Project Info */}
        <div className="flex-1 text-left">
          <div className="flex items-center gap-2">
            <h3
              className="text-sm font-semibold"
              style={{ color: isActive ? 'var(--color-primary)' : 'var(--color-text-primary)' }}
            >
              {project.name}
            </h3>
            {project.status === 'active' && (
              <span className="px-2 py-0.5 text-xs font-medium rounded-full bg-green-100 dark:bg-green-500/20 text-green-700 dark:text-green-400">
                {t('library_active_badge')}
              </span>
            )}
          </div>
          {project.description && (
            <p className="text-xs mt-0.5 line-clamp-1" style={{ color: 'var(--color-text-muted)' }}>
              {project.description}
            </p>
          )}
        </div>

        {/* Workflow Count Badge */}
        <div className="flex items-center gap-2">
          <span
            className="px-2 py-1 text-xs font-medium rounded-md bg-gray-100 dark:bg-white/10"
            style={{ color: 'var(--color-text-primary)' }}
          >
            {workflows.length === 1 ? t('library_workflow_count', { count: workflows.length }) : t('library_workflow_count_plural', { count: workflows.length })}
          </span>
        </div>
      </button>

      {/* Workflows List (when expanded) */}
      {isExpanded && (
        <div className="mt-1 ml-8 space-y-1 animate-in fade-in slide-in-from-top-2 duration-200">
          {workflows.length === 0 ? (
            <div className="px-4 py-6 text-center">
              <span
                className="material-symbols-outlined text-3xl mb-2"
                style={{ color: 'var(--color-text-muted)' }}
              >
                account_tree
              </span>
              <p className="text-sm" style={{ color: 'var(--color-text-muted)' }}>
                {t('library_empty_project')}
              </p>
            </div>
          ) : (
            workflows.map((workflow) => {
              // Read from configuration (where Studio saves) first, fallback to blueprint
              const workflowNodeCount = workflow.configuration?.nodes?.length || workflow.blueprint?.nodes?.length || 0;
              const isSelected = selectedWorkflowId === workflow.id;

              return (
                <button
                  key={workflow.id}
                  onClick={() => onSelectWorkflow(workflow)}
                  onContextMenu={(e) => handleContextMenu(e, workflow)}
                  className={`w-full flex items-center gap-3 px-3 py-2 rounded-xl transition-all duration-200 ${isSelected
                    ? 'bg-primary/10 dark:bg-primary/20 shadow-sm'
                    : 'bg-gray-50 dark:bg-white/5 hover:bg-gray-100 dark:hover:bg-white/10'
                    }`}
                >
                  {/* Workflow Icon */}
                  <span
                    className="material-symbols-outlined text-lg flex-shrink-0"
                    style={{ color: isSelected ? 'var(--color-primary)' : 'var(--color-text-muted)' }}
                  >
                    account_tree
                  </span>

                  {/* Workflow Info + Node Count */}
                  <div className="flex-1 text-left min-w-0 flex items-center justify-between gap-2">
                    <p
                      className="text-sm font-medium truncate"
                      style={{ color: isSelected ? 'var(--color-primary)' : 'var(--color-text-primary)' }}
                    >
                      {workflow.name}
                    </p>
                    <span className="text-xs whitespace-nowrap flex-shrink-0" style={{ color: 'var(--color-text-muted)' }}>
                      {workflowNodeCount === 1 ? t('library_node_count', { count: workflowNodeCount }) : t('library_node_count_plural', { count: workflowNodeCount })}
                    </span>
                  </div>
                </button>
              );
            })
          )}
        </div>
      )}

      {/* Context Menu */}
      {contextMenu && (
        <WorkflowContextMenu
          x={contextMenu.x}
          y={contextMenu.y}
          onClose={() => setContextMenu(null)}
          onRename={() => onRenameWorkflow(contextMenu.workflow)}
          onDuplicate={() => onDuplicateWorkflow(contextMenu.workflow)}
          onChangeProject={() => onChangeProjectWorkflow(contextMenu.workflow)}
          onDelete={() => onDeleteWorkflow(contextMenu.workflow)}
        />
      )}
    </div>
  );
}
