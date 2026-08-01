/**
 * WorkflowStudioPage — LangGraph workflow studio for layout2.
 *
 * Wraps WorkflowCanvas + adds an "Add Agent" dropdown above the canvas.
 * The dropdown fetches agent templates from /api/agents/templates.
 * Selecting an agent adds it as a node on the canvas.
 */
import { useState, useRef, useCallback, useMemo, useEffect, forwardRef, useImperativeHandle } from 'react';
import WorkflowCanvas, { type WorkflowCanvasRef, type WorkflowRecipe } from '../../features/workflows/canvas/WorkflowCanvas';
import apiClient from '../../lib/api-client';
import { Plus, Loader, ChevronDown, Bot, FilePlus2 } from 'lucide-react';
import { useLayoutTokens } from './tokens';

/**
 * NodeConfig shape expected by NodeConfigPanel.
 */
export interface StudioNodeConfig {
  id: string;
  name: string;
  agentType?: string;
  model?: string;
  system_prompt?: string;
  temperature?: number;
  max_tokens?: number;
  max_retries?: number;
  recursion_limit?: number;
  tools?: any[];
  native_tools?: any[];
  custom_tools?: any[];
  middleware?: any[];
  condition?: string;
  max_iterations?: number;
  exit_condition?: string;
  data?: any;
  tool_type?: string;
  tool_id?: string;
  tool_params?: any;
  subagents?: any[];
  use_deepagents?: boolean;
}

/**
 * Methods exposed to parent via ref.
 */
export interface WorkflowStudioRef {
  updateNodeConfig: (nodeId: string, config: any) => void;
  deleteNode: (nodeId: string) => void;
  saveWorkflow: (silent?: boolean) => void;
  hasUnsavedChanges: () => boolean;
  loadWorkflow: (workflowId: number) => void;
  loadRecipe: (recipeId: string) => void;
  openCreateWorkflowModal: () => void;
}

interface AgentTemplate {
  id: string;
  name: string;
  description: string;
  icon: string;
  category: string;
  model: string;
  temperature: number;
  system_prompt: string;
  native_tools: string[];
  cli_tools?: string[];
  custom_tools?: string[];
  timeout_seconds: number;
  max_retries: number;
  enable_model_routing: boolean;
  enable_parallel_tools: boolean;
  enable_memory: boolean;
  capabilities?: string[];
  use_deepagents: boolean;
}

interface WorkflowStudioPageProps {
  onNodeSelectChange?: (nodeId: string | null, config: StudioNodeConfig | null) => void;
  onWorkflowSelect?: (workflowId: number) => void;
  /** External workflow ID from sidebar selection */
  workflowId?: number | null;
}

const WorkflowStudioPage = forwardRef<WorkflowStudioRef, WorkflowStudioPageProps>(
  ({ onNodeSelectChange, onWorkflowSelect, workflowId: externalWorkflowId }, ref) => {
  const t = useLayoutTokens();
  const workflowCanvasRef = useRef<WorkflowCanvasRef>(null);
  const saveWorkflowTimeoutRef = useRef<number | null>(null);

  const [selectedWorkflowId, setSelectedWorkflowId] = useState<number | null>(null);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [selectedNodeData, setSelectedNodeData] = useState<any>(null);
  const [selectedRecipe, setSelectedRecipe] = useState<WorkflowRecipe | null>(null);
  const [nodeConfigs, setNodeConfigs] = useState<Record<string, any>>({});
  const [tokenCostInfo, setTokenCostInfo] = useState<{
    totalTokens: number; promptTokens: number; completionTokens: number; costString: string;
  } | null>(null);
  const [workflowTab, setWorkflowTab] = useState<'studio' | 'results'>('studio');

  // ── Agent selector state ──
  const [agents, setAgents] = useState<AgentTemplate[]>([]);
  const [agentsLoading, setAgentsLoading] = useState(false);
  const [showAgentDropdown, setShowAgentDropdown] = useState(false);
  const [selectedAgent, setSelectedAgent] = useState<any>(null);

  // Fetch agent templates on mount (system + custom)
  useEffect(() => {
    setAgentsLoading(true);
    Promise.all([
      apiClient.apiFetch(`${apiClient.baseURL}/api/agents/templates`),
      apiClient.listDeepAgents({ public_only: false }).catch(() => ({ data: [] })),
    ])
      .then(([tplRes, customRes]: any) => {
        // System templates
        const templates = Array.isArray(tplRes) ? tplRes : tplRes?.data ?? [];

        // Custom normal agents (config.use_deepagents === false)
        const allAgents = Array.isArray(customRes.data) ? customRes.data : [];
        const customAgents = allAgents
          .filter((ag: any) => ag.config?.use_deepagents === false)
          .map((ag: any) => ({
            id: `custom-${ag.id}`,
            name: ag.name,
            description: ag.description || '',
            icon: ag.icon || 'bot',
            category: ag.category || 'custom',
            model: ag.config?.model || 'gpt-4o-mini',
            temperature: ag.config?.temperature ?? 0.7,
            system_prompt: ag.config?.system_prompt || '',
            native_tools: ag.config?.native_tools || ag.config?.mcp_tools || [],
            cli_tools: ag.config?.cli_tools || [],
            custom_tools: ag.config?.custom_tools || [],
            timeout_seconds: ag.config?.timeout_seconds ?? 300,
            max_retries: ag.config?.max_retries ?? 3,
            enable_model_routing: ag.config?.enable_model_routing ?? false,
            enable_parallel_tools: ag.config?.enable_parallel_tools ?? false,
            enable_memory: ag.config?.enable_memory ?? true,
            capabilities: ag.tags || [],
            use_deepagents: false,
          }));

        setAgents([...templates, ...customAgents]);
      })
      .catch(() => {})
      .finally(() => setAgentsLoading(false));
  }, []);

  // Clear selectedAgent after WorkflowCanvas consumes it
  const handleAgentAdded = useCallback(() => {
    setSelectedAgent(null);
  }, []);

  // Handle agent pick from dropdown
  const handlePickAgent = useCallback((template: AgentTemplate) => {
    setSelectedAgent({
      id: template.id,
      name: template.name,
      description: template.description,
      icon: template.icon || 'bot',
      model: template.model,
      temperature: template.temperature,
      system_prompt: template.system_prompt,
      native_tools: template.native_tools || [],
      cli_tools: template.cli_tools || [],
      custom_tools: template.custom_tools || [],
      timeout_seconds: template.timeout_seconds || 300,
      max_retries: template.max_retries || 3,
      enable_model_routing: template.enable_model_routing ?? false,
      enable_parallel_tools: template.enable_parallel_tools ?? false,
      enable_memory: template.enable_memory ?? true,
      tags: template.capabilities || [],
    });
    setShowAgentDropdown(false);
  }, []);

  // Group agents by category
  const agentsByCategory = useMemo(() => {
    return agents.reduce((acc, a) => {
      if (!acc[a.category]) acc[a.category] = [];
      acc[a.category].push(a);
      return acc;
    }, {} as Record<string, AgentTemplate[]>);
  }, [agents]);

  // Normalize selected node data into the shape NodeConfigPanel expects
  const buildNodeConfig = useCallback((nodeId: string, data: any): StudioNodeConfig => {
    const d = data || {};
    const cfg = d.config || {};
    return {
      id: nodeId,
      name: d.label || d.name || cfg.name || nodeId,
      agentType: d.agentType,
      model: d.model || cfg.model,
      system_prompt: d.system_prompt || cfg.system_prompt || '',
      temperature: d.temperature ?? cfg.temperature ?? 0.7,
      max_tokens: d.max_tokens || cfg.max_tokens || 4000,
      max_retries: d.max_retries || cfg.max_retries || 3,
      recursion_limit: d.recursion_limit || cfg.recursion_limit || 300,
      tools: d.tools || cfg.tools || [],
      native_tools: d.native_tools || cfg.native_tools || cfg.mcp_tools || [],
      custom_tools: d.custom_tools || cfg.custom_tools || [],
      middleware: d.middleware || cfg.middleware || [],
      condition: d.condition || cfg.condition,
      max_iterations: d.max_iterations || cfg.max_iterations,
      exit_condition: d.exit_condition || cfg.exit_condition,
      data: d,
      tool_type: d.tool_type || cfg.tool_type,
      tool_id: d.tool_id || cfg.tool_id,
      tool_params: d.tool_params || cfg.tool_params,
      subagents: d.subagents || cfg.subagents || [],
      use_deepagents: d.use_deepagents || cfg.use_deepagents || false,
    };
  }, []);

  const handleNodeSelect = useCallback((nodeId: string | null, nodeData?: any) => {
    setSelectedNodeId(nodeId);
    if (nodeId && nodeData) {
      setSelectedNodeData(nodeData);
      onNodeSelectChange?.(nodeId, buildNodeConfig(nodeId, nodeData));
    } else {
      setSelectedNodeData(null);
      onNodeSelectChange?.(null, null);
    }
  }, [onNodeSelectChange, buildNodeConfig]);

  const handleNodeConfigSave = useCallback((nodeId: string, fullConfig: any) => {
    setNodeConfigs(prev => ({ ...prev, [nodeId]: fullConfig }));
    workflowCanvasRef.current?.updateNodeConfig(nodeId, fullConfig);
    if (selectedNodeId === nodeId && selectedNodeData) {
      const updated = { ...selectedNodeData, ...fullConfig, config: { ...selectedNodeData.config, ...fullConfig } };
      setSelectedNodeData(updated);
      onNodeSelectChange?.(nodeId, buildNodeConfig(nodeId, updated));
    }
    if (saveWorkflowTimeoutRef.current !== null) clearTimeout(saveWorkflowTimeoutRef.current);
    saveWorkflowTimeoutRef.current = window.setTimeout(() => {
      workflowCanvasRef.current?.saveWorkflow(true);
    }, 800);
  }, [selectedNodeId, selectedNodeData, onNodeSelectChange, buildNodeConfig]);

  const handleNodeDelete = useCallback((nodeId: string) => {
    workflowCanvasRef.current?.deleteNode(nodeId);
    setSelectedNodeId(null);
    setSelectedNodeData(null);
    setNodeConfigs(prev => { const n = { ...prev }; delete n[nodeId]; return n; });
    onNodeSelectChange?.(null, null);
  }, [onNodeSelectChange]);

  const loadRecipe = useCallback(async (recipeId: string) => {
    try {
      const res = await apiClient.apiFetch(`${apiClient.baseURL}/api/agents/recipes/${recipeId}`);
      const recipe = Array.isArray(res) ? res[0] : res;
      if (!recipe?.nodes) throw new Error('Invalid recipe payload');
      setSelectedRecipe(recipe as WorkflowRecipe);
    } catch (err) {
      console.error('Failed to load recipe:', err);
    }
  }, []);

  const handleExecutionStart = useCallback(() => {}, []);

  useImperativeHandle(ref, () => ({
    updateNodeConfig: (nodeId: string, config: any) => {
      workflowCanvasRef.current?.updateNodeConfig(nodeId, config);
    },
    deleteNode: handleNodeDelete,
    saveWorkflow: (silent?: boolean) => {
      workflowCanvasRef.current?.saveWorkflow(silent);
    },
    hasUnsavedChanges: () => workflowCanvasRef.current?.hasUnsavedChanges() ?? false,
    loadWorkflow: (id: number) => {
      workflowCanvasRef.current?.loadWorkflowById?.(id);
    },
    loadRecipe,
    openCreateWorkflowModal: () => {
      workflowCanvasRef.current?.openCreateWorkflowModal?.();
    },
  }), [handleNodeDelete, loadRecipe]);

  // Sync external workflowId (from sidebar) into local state
  useEffect(() => {
    if (externalWorkflowId != null) {
      setSelectedWorkflowId(externalWorkflowId);
    }
  }, [externalWorkflowId]);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', width: '100%' }}>
      {/* ── Agent selector bar (inside the editor, above the canvas) ── */}
      <div style={{
        display: 'flex', alignItems: 'center', gap: 8,
        padding: '6px 12px',
        borderBottom: `1px solid ${t.border}`,
        background: 'var(--color-panel)',
        flexShrink: 0,
      }}>
        <button
          onClick={() => workflowCanvasRef.current?.openCreateWorkflowModal?.()}
          title="Create a new workflow"
          style={{
            display: 'inline-flex', alignItems: 'center', gap: 6,
            padding: '4px 10px', fontSize: 12, fontWeight: 500,
            border: `1px solid ${t.border}`, borderRadius: 6, cursor: 'pointer',
            background: 'transparent', color: t.textPrimary,
          }}
        >
          <FilePlus2 size={12} />
          New Workflow
        </button>
        {/* Label */}
        <span style={{ fontSize: 11, fontWeight: 600, color: t.textMuted, whiteSpace: 'nowrap' }}>
          Add Node:
        </span>

        {/* Dropdown button */}
        <div style={{ position: 'relative' }}>
          <button
            onClick={() => setShowAgentDropdown(!showAgentDropdown)}
            style={{
              display: 'flex', alignItems: 'center', gap: 6,
              padding: '4px 10px', fontSize: 12, fontWeight: 500,
              border: `1px solid ${showAgentDropdown ? t.accent : t.border}`,
              borderRadius: 6, cursor: 'pointer',
              background: showAgentDropdown ? `${t.accent}15` : 'transparent',
              color: t.accent,
            }}
          >
            <Plus size={12} />
            <span>Agent</span>
            <ChevronDown size={10} style={{ opacity: 0.6 }} />
          </button>

          {/* Dropdown popover */}
          {showAgentDropdown && (
            <>
              <div style={{ position: 'fixed', inset: 0, zIndex: 49 }} onClick={() => setShowAgentDropdown(false)} />
              <div style={{
                position: 'absolute', top: '100%', left: 0, marginTop: 4,
                width: 260, maxHeight: 360, overflowY: 'auto',
                background: 'var(--color-panel, #1e1e1e)',
                border: `1px solid ${t.border}`,
                borderRadius: 8,
                boxShadow: '0 8px 24px rgba(0,0,0,0.35)',
                zIndex: 50,
              }}>
                {agentsLoading ? (
                  <div style={{ padding: 16, textAlign: 'center', color: t.textMuted, fontSize: 12 }}>
                    <Loader size={14} style={{ animation: 'spin 1s linear infinite' }} />
                  </div>
                ) : agents.length === 0 ? (
                  <div style={{ padding: 16, textAlign: 'center', color: t.textMuted, fontSize: 12 }}>
                    No agents available
                  </div>
                ) : (
                  Object.entries(agentsByCategory).map(([cat, list]) => (
                    <div key={cat}>
                      <div style={{
                        padding: '4px 10px 2px', fontSize: 9, fontWeight: 600,
                        color: t.textMuted, textTransform: 'uppercase', letterSpacing: '0.5px',
                      }}>
                        {cat} ({list.length})
                      </div>
                      {list.map(a => (
                        <div
                          key={a.id}
                          onClick={() => handlePickAgent(a)}
                          style={{
                            display: 'flex', alignItems: 'center', gap: 8,
                            padding: '5px 10px', cursor: 'pointer', fontSize: 11, color: t.textPrimary,
                          }}
                          onMouseEnter={(e) => { e.currentTarget.style.background = t.bgHover; }}
                          onMouseLeave={(e) => { e.currentTarget.style.background = 'transparent'; }}
                        >
                          <Bot size={12} style={{ flexShrink: 0, opacity: 0.6 }} />
                          <div style={{ flex: 1, minWidth: 0 }}>
                            <div style={{ whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', fontWeight: 500 }}>
                              {a.name}
                            </div>
                          </div>
                          <Plus size={10} color={t.accent} style={{ flexShrink: 0 }} />
                        </div>
                      ))}
                    </div>
                  ))
                )}
              </div>
            </>
          )}
        </div>

        <span style={{ fontSize: 10, color: t.textMuted, fontStyle: 'italic' }}>
          Or drag from Node Palette (left)
        </span>
      </div>

      {/* ── Workflow Canvas ── */}
      <WorkflowCanvas
        ref={workflowCanvasRef}
        selectedAgent={selectedAgent}
        selectedRecipe={selectedRecipe}
        onWorkflowSelect={(id) => { setSelectedWorkflowId(id); onWorkflowSelect?.(id); }}
        onNodeSelect={handleNodeSelect}
        onNodeDelete={handleNodeDelete}
        onExecutionStart={handleExecutionStart}
        onAgentAdded={handleAgentAdded}
        onRecipeInserted={() => setSelectedRecipe(null)}
        workflowId={selectedWorkflowId}
        onTabChange={(tab) => setWorkflowTab(tab)}
        initialTab={workflowTab}
        onTokenCostUpdate={setTokenCostInfo}
      />
    </div>
  );
});

export default WorkflowStudioPage;

/** Helper to save a node config change from the right panel */
export function saveNodeConfig(
  nodeId: string,
  fullConfig: any,
  workflowCanvasRef: React.RefObject<WorkflowCanvasRef | null>,
) {
  workflowCanvasRef.current?.updateNodeConfig(nodeId, fullConfig);
}

/** Helper to check unsaved changes */
export function hasUnsavedChanges(workflowCanvasRef: React.RefObject<WorkflowCanvasRef | null>): boolean {
  return workflowCanvasRef.current?.hasUnsavedChanges() ?? false;
}

/** Helper to trigger save */
export function saveWorkflow(workflowCanvasRef: React.RefObject<WorkflowCanvasRef | null>, silent?: boolean) {
  workflowCanvasRef.current?.saveWorkflow(silent);
}
