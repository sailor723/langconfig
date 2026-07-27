/**
 * useSidebarData — fetch real sidebar data from the backend API.
 *
 * Replaces the hardcoded placeholder data in LeftSidebar.
 * Loads workflows, agents, etc. from the APIClient.
 */
import { useState, useEffect, useCallback } from 'react';
import apiClient from '../../lib/api-client';
import type { TreeNode } from './TreeView';

export interface SidebarData {
  nodes: TreeNode[];
  loading: boolean;
  error: string | null;
  /** Get content for a specific file node by its id (e.g. workflow id) */
  getNodeContent: (node: TreeNode) => Promise<string>;
  /** Save content for a specific file node */
  saveNodeContent: (node: TreeNode, content: string) => Promise<void>;
}

export function useSidebarData(activity: string): SidebarData {
  const [nodes, setNodes] = useState<TreeNode[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const result: TreeNode[] = [];

      if (activity === 'deepagents') {
        // Wrap deep agents in a folder-like container so the folder row
        // can host a "+ New Agent" action button (VS Code Explorer pattern)
        try {
          const res = await apiClient.listDeepAgents();
          const agents = Array.isArray(res.data) ? res.data : [];
          // Filter: only agents with use_deepagents=true (or missing — default to true)
          const deepAgents = agents.filter((ag: any) => ag.config?.use_deepagents !== false);
          const children: TreeNode[] = deepAgents.map((ag: any) => ({
            id: `deepagent-${ag.id}`,
            label: ag.name || `DeepAgent #${ag.id}`,
            viewType: 'deepagent',
            badge: ag.category || '',
            data: { agentId: ag.id, ...ag },
          }));
          if (children.length === 0) {
            children.push({ id: 'empty-deepagents', label: '(no deep agents yet)', viewType: 'empty' });
          }
          result.push({
            id: 'folder-deepagents',
            label: 'Deep Agents',
            children,
          });
        } catch (err: any) {
          console.error('DeepAgents load failed:', err?.message, err?.response?.status);
          result.push({
            id: 'folder-deepagents',
            label: 'Deep Agents',
            children: [{ id: 'empty-deepagents', label: `Failed: ${err?.message || 'unknown'}`, viewType: 'empty' }],
          });
        }
      } else if (activity === 'workflows') {
        const res = await apiClient.listWorkflows();
        const workflows = Array.isArray(res.data) ? res.data : (res.data?.items || res.data?.workflows || []);
        result.push({
          id: 'folder-workflows',
          label: 'My Workflows',
          children: workflows.map((wf: any) => ({
            id: `wf-${wf.id}`,
            label: wf.name || `Workflow #${wf.id}`,
            viewType: 'workflow',
            badge: wf.status || 'draft',
            data: { workflowId: wf.id, ...wf },
          })),
        });
        if (workflows.length === 0) {
          result.push({ id: 'empty-workflows', label: '(no workflows yet)', viewType: 'empty' });
        }
      } else if (activity === 'agents') {
        try {
          const res = await apiClient.listDeepAgents();
          const agents = Array.isArray(res.data) ? res.data : [];
          // Filter: only agents with use_deepagents=false (normal agents)
          const normalAgents = agents.filter((ag: any) => ag.config?.use_deepagents === false);
          const children: TreeNode[] = normalAgents.map((ag: any) => ({
            id: `agent-${ag.id}`,
            label: ag.name || `Agent #${ag.id}`,
            viewType: 'agent',
            badge: ag.category || '',
            data: { agentId: ag.id, ...ag },
          }));
          if (children.length === 0) {
            children.push({ id: 'empty-agents', label: '(no agents yet)', viewType: 'empty' });
          }
          result.push({
            id: 'folder-agents',
            label: 'Agents',
            children,
          });
        } catch (err: any) {
          console.error('Agents load failed:', err?.message, err?.response?.status);
          result.push({
            id: 'folder-agents',
            label: 'Agents',
            children: [{ id: 'empty-agents', label: `Failed: ${err?.message || 'unknown'}`, viewType: 'empty' }],
          });
        }
      } else if (activity === 'library') {
        result.push({
          id: 'folder-skills',
          label: 'Skills',
          children: [
            { id: 'sk-sql', label: 'sql-analyst', viewType: 'library' },
            { id: 'sk-viz', label: 'data-visualizer', viewType: 'library' },
          ],
        });
        result.push({
          id: 'folder-tools',
          label: 'Tools',
          children: [
            { id: 'tl-sqlite', label: 'sqlite-execute', viewType: 'library' },
            { id: 'tl-python', label: 'python-execute', viewType: 'library' },
          ],
        });
      } else if (activity === 'analysis') {
        result.push({
          id: 'folder-dashboards',
          label: 'Dashboards',
          children: [
            { id: 'db-sunhing', label: 'Sunhing KPI', viewType: 'analysis' },
            { id: 'db-sales', label: 'Sales Overview', viewType: 'analysis' },
          ],
        });
      }

      setNodes(result);
    } catch (err: any) {
      setError(err?.message || 'Failed to load sidebar data');
      setNodes([]);
    } finally {
      setLoading(false);
    }
  }, [activity]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  const getNodeContent = useCallback(async (node: TreeNode): Promise<string> => {
    const data: any = node.data || {};

    if (node.viewType === 'deepagent' && data.agentId) {
      try {
        const res = await apiClient.getDeepAgent(data.agentId);
        // Stash the full agent object on node.data for the structured editor
        node.data = { ...node.data, agent: res.data };
        return JSON.stringify(res.data, null, 2);
      } catch {
        return '// Failed to load DeepAgent config';
      }
    }

    if (node.viewType === 'agent' && data.agentId) {
      try {
        const res = await apiClient.getDeepAgent(data.agentId);
        // Stash the full agent object on node.data for the structured editor
        node.data = { ...node.data, agent: res.data };
        return JSON.stringify(res.data, null, 2);
      } catch {
        return '// Failed to load Agent config';
      }
    }

    if (node.viewType === 'workflow' && data.workflowId) {
      try {
        const res = await apiClient.getWorkflowCode(data.workflowId);
        return typeof res.data === 'string' ? res.data : JSON.stringify(res.data, null, 2);
      } catch {
        const res = await apiClient.getWorkflow(data.workflowId);
        return JSON.stringify(res.data, null, 2);
      }
    }
    return '';
  }, []);

  const saveNodeContent = useCallback(async (node: TreeNode, content: string): Promise<void> => {
    const data: any = node.data || {};
    if (node.viewType === 'workflow' && data.workflowId) {
      try {
        await apiClient.updateWorkflow(data.workflowId, { configuration: content });
      } catch {
        // Silently fail for now
      }
    }
  }, []);

  return { nodes, loading, error, getNodeContent, saveNodeContent };
}
