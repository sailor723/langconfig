/**
 * Copyright (c) 2025 Cade Russell (Ghost Peony)
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 *
 * App — root component.
 *
 * VS Code-style layout:
 * ┌──────┬──────────┬───────────────────┬──────────────┐
 * │ Act  │ Side Bar │ Editor            │ Right Panel  │
 * │ Bar  │ (explorer│ (tabs + content)  │ Chat / Props │
 * │      │  /search)├───────────────────┤              │
 * │      │          │ Terminal / Exec / Results         │
 * ├──────┴──────────┴───────────────────┴──────────────┤
 * │ Status Bar (#007acc blue, full width)               │
 * └─────────────────────────────────────────────────────┘
 */
import { useState, useEffect, useRef, useCallback } from 'react';
import { HashRouter, Routes, Route, useNavigate, useLocation } from 'react-router-dom';
import ModernAgentLibrary from './features/agents/ui/ModernAgentLibrary';
import WorkflowCanvas, { WorkflowCanvasRef, WorkflowRecipe } from './features/workflows/canvas/WorkflowCanvas';
import { TaskHistoryEntry } from './features/workflows/canvas/types';
import WorkflowLibraryView from './features/workflows/library/WorkflowLibraryView';
import NodeConfigPanel from './features/workflows/node-config/NodeConfigPanel';
import PlaygroundPage from './pages/PlaygroundPage';
import DeepAgentStudioPage from './features/deepagent-studio-v2/ModernStudioPage';
import KnowledgeBaseView from './features/knowledge/ui/KnowledgeBaseView';

import ToolLibrary from './features/tools/ToolLibrary';
import PromptAssemblyPage from './pages/PromptAssemblyPage';
import { SkillLibrary } from './features/skills';
import HomePage from './pages/HomePage';
import AnalysisPage from './pages/AnalysisPage';
import { ThemeProvider } from './lib/themes';
import { ProjectProvider } from './contexts/ProjectContext';
import { ToastProvider, ToastContainer } from './hooks/useToast';
import { ChatProvider } from './features/chat/state/ChatContext';
import GlobalChatModal from './features/chat/ui/GlobalChatModal';
import ChatPage from './features/chat/ui/ChatPage';
import apiClient from './lib/api-client';

// Layout2 components
import { LayoutProvider, useLayoutState, type ActivityId } from './components/layout2/useLayout';
import ActivityBar from './components/layout2/ActivityBar';
import LeftSidebar from './components/layout2/LeftSidebar';
import Workspace from './components/layout2/Workspace';
import NodeSidebar from './components/layout2/NodeSidebar';
import BottomPanel from './components/layout2/BottomPanel';
import StatusBar from './components/layout2/StatusBar';

type View = 'studio' | 'library' | 'settings' | 'knowledge' | 'agents' | 'deepagents' | 'skills' | 'home' | 'analysis' | 'playground' | 'tools' | 'prompt' | 'deepagent-studio' | 'models' | 'search' | 'chat';
type WorkflowStatus = 'draft' | 'saved' | 'running' | 'completed' | 'failed';

interface Agent {
  id: string;
  name: string;
  description: string;
  icon: string;
  model: string;
  fallback_models?: string[];
  temperature: number;
  max_tokens?: number;
  system_prompt: string;
  native_tools: string[];
  cli_tools?: string[];
  timeout_seconds: number;
  max_retries: number;
  enable_model_routing: boolean;
  enable_parallel_tools: boolean;
  enable_memory: boolean;
  enable_rag?: boolean;
  requires_human_approval?: boolean;
  tags?: string[];
}

interface NodeConfig {
  id: string;
  agentType: string;
  model: string;
  system_prompt: string;
  temperature: number;
  tools: string[];
  native_tools: string[];
  data?: any;
  custom_tools?: string[];
  middleware?: any[];
  subagents?: any[];
  use_deepagents?: boolean;
  condition?: string;
  max_iterations?: number;
  exit_condition?: string;
  tool_type?: string;
  tool_id?: string;
  tool_params?: Record<string, any>;
}

interface SelectedNodeData {
  id: string;
  label: string;
  name?: string;
  agentType: string;
  model: string;
  system_prompt?: string;
  temperature?: number;
  max_tokens?: number;
  max_retries?: number;
  recursion_limit?: number;
  tools?: string[];
  native_tools?: string[];
  custom_tools?: string[];
  middleware?: any[];
  condition?: string;
  max_iterations?: number;
  exit_condition?: string;
  config: {
    model: string;
    fallback_models?: string[];
    temperature: number;
    max_tokens?: number;
    max_retries?: number;
    recursion_limit?: number;
    system_prompt: string;
    tools: string[];
    native_tools: string[];
    cli_tools?: string[];
    custom_tools?: string[];
    middleware?: any[];
    timeout_seconds: number;
    enable_model_routing: boolean;
    enable_parallel_tools: boolean;
    enable_memory: boolean;
    enable_rag?: boolean;
    requires_human_approval?: boolean;
    condition?: string;
    max_iterations?: number;
    exit_condition?: string;
    name?: string;
    subagents?: any[];
    use_deepagents?: boolean;
    tool_type?: string;
    tool_id?: string;
    tool_params?: Record<string, any>;
  };
}

// Map route path → View
const ROUTE_TO_VIEW: Record<string, View> = {
  '/': 'home', '/home': 'home',
  '/studio': 'studio', '/results': 'studio',
  '/library': 'library',
  '/agents': 'agents', '/deepagents': 'deepagents',
  '/knowledge': 'knowledge',
  '/skills': 'skills',
  '/tools': 'tools',
  '/prompt': 'prompt',
  '/analysis': 'analysis',
  // settings → popover only, no route
  '/playground': 'playground',
  '/models': 'models',
  '/search': 'search',
  '/deepagent-studio': 'deepagent-studio',
  '/chat': 'chat',
};

// Map View → route path
const VIEW_ROUTE: Record<View, string> = {
  home: '/home', studio: '/studio', library: '/library',
  agents: '/agents', deepagents: '/deepagents', skills: '/skills',
  knowledge: '/knowledge', analysis: '/analysis', settings: '/settings',
  playground: '/playground', tools: '/tools', prompt: '/prompt',
  'deepagent-studio': '/deepagent-studio',
  models: '/models',
  search: '/search',
  chat: '/chat',
};

// Map View → ActivityId
const VIEW_TO_ACTIVITY: Record<View, ActivityId | null> = {
  home: null,
  studio: 'workflows',
  library: 'workflows',
  agents: 'agents',
  deepagents: 'deepagents',
  skills: 'library',
  tools: 'library',
  prompt: 'library',
  knowledge: 'knowledge',
  analysis: 'analysis',
  settings: 'settings',
  playground: 'workflows',
  'deepagent-studio': 'studio',
  models: 'models',
  search: 'search',
  chat: null,
};

// Map ActivityId → View (for ActivityBar clicks)
const ACTIVITY_TO_VIEW: Record<ActivityId, View> = {
  workflows: 'studio',
  deepagents: 'deepagents',
  agents: 'agents',
  tools: 'tools',
  knowledge: 'knowledge',
  models: 'models',
  search: 'search',
  library: 'library',
  analysis: 'analysis',
  skills: 'skills',
  settings: 'settings',
  studio: 'deepagent-studio',
};

function AppContent() {
  const navigate = useNavigate();
  const location = useLocation();
  const workflowCanvasRef = useRef<WorkflowCanvasRef>(null);
  const saveWorkflowTimeoutRef = useRef<number | null>(null);

  const [selectedAgent, setSelectedAgent] = useState<Agent | null>(null);
  const [selectedRecipe, setSelectedRecipe] = useState<WorkflowRecipe | null>(null);
  const [selectedWorkflowId, setSelectedWorkflowId] = useState<number | null>(null);
  const [workflowName, setWorkflowName] = useState('Untitled Workflow');
  const [workflowStatus, setWorkflowStatus] = useState<WorkflowStatus>('draft');
  const [executing, setExecuting] = useState(false);
  const [workflowTab, setWorkflowTab] = useState<'studio' | 'results'>('studio');
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [selectedNodeData, setSelectedNodeData] = useState<SelectedNodeData | null>(null);

  useEffect(() => {
    const handleChatOpened = () => {
      setSelectedNodeId(null);
      setSelectedNodeData(null);
    };
    window.addEventListener('chat:opened', handleChatOpened);
    return () => window.removeEventListener('chat:opened', handleChatOpened);
  }, []);
  const [nodeConfigs, setNodeConfigs] = useState<Record<string, NodeConfig>>({});
  const [tokenCostInfo, setTokenCostInfo] = useState<{
    totalTokens: number;
    promptTokens: number;
    completionTokens: number;
    costString: string;
  } | null>(null);

  const [taskHistory, setTaskHistory] = useState<TaskHistoryEntry[]>([]);
  const [selectedHistoryTask, setSelectedHistoryTask] = useState<TaskHistoryEntry | null>(null);
  const [loadingHistory, setLoadingHistory] = useState(false);
  const [sidebarPanel, setSidebarPanel] = useState<'agents' | 'history'>('agents');

  // Layout state
  const { setActiveActivity, sidebarView, setSidebarView, openRightPanel, closeRightPanel, rightPanelOpen } = useLayoutState();

  // Sync workflowTab with current route
  useEffect(() => {
    if (location.pathname === '/results') {
      setWorkflowTab('results');
    } else if (location.pathname === '/studio') {
      setWorkflowTab('studio');
    }
  }, [location.pathname]);

  // DeepAgent Studio → navigate to Skill Library
  useEffect(() => {
    const handler = (e: Event) => {
      const ce = e as CustomEvent<{ skillId?: string }>;
      console.log('[App] navigating to /skills', ce.detail);
      navigate('/skills');
      if (ce.detail?.skillId) {
        sessionStorage.setItem('da:pending-skill-select', ce.detail.skillId);
      }
    };
    window.addEventListener('da:navigate-skills', handler);
    return () => window.removeEventListener('da:navigate-skills', handler);
  }, [navigate]);

  // Current view from route
  const currentView: View = ROUTE_TO_VIEW[location.pathname] ?? 'home';

  // Chat is a standalone full-page view — render without layout chrome
  if (currentView === 'chat') {
    return <ChatPage />;
  }

  // Sync ActivityBar with current view
  useEffect(() => {
    const activity = VIEW_TO_ACTIVITY[currentView];
    if (activity) setActiveActivity(activity);
  }, [currentView, setActiveActivity]);

  // Handle tab changes within studio view
  const handleTabChange = useCallback((tab: 'studio' | 'results') => {
    setWorkflowTab(tab);
    navigate(tab === 'results' ? '/results' : '/studio');
    if (tab === 'results') {
      setSidebarPanel('history');
    }
  }, [navigate]);

  // Handle sidebar panel change (Agents/History tabs)
  const handleSidebarPanelChange = useCallback((panel: 'agents' | 'history') => {
    setSidebarPanel(panel);
    if (panel === 'agents') {
      handleTabChange('studio');
    }
  }, [handleTabChange]);

  const handleViewChange = (view: View) => {
    if (currentView === 'studio' && workflowCanvasRef.current) {
      const hasUnsaved = workflowCanvasRef.current.hasUnsavedChanges();
      if (hasUnsaved) {
        const confirmLeave = window.confirm(
          'You have unsaved workflow changes. Do you want to save before leaving?\n\n' +
          'Click OK to stay and save your changes.\n' +
          'Click Cancel to leave without saving.'
        );
        if (confirmLeave) return;
      }
    }
    navigate(VIEW_ROUTE[view]);
  };

  const handleSave = () => {
    if (workflowCanvasRef.current) {
      workflowCanvasRef.current.saveWorkflow(false);
    }
  };

  const handleWorkflowNameChange = (name: string) => {
    setWorkflowName(name);
    if (selectedWorkflowId) {
      apiClient.updateWorkflow(selectedWorkflowId, { name })
        .catch((err: any) => console.error("Failed to save workflow name:", err));
    }
  };

  const handleExecutionStart = () => {
    setExecuting(true);
    setWorkflowStatus('running');
  };

  const handleNodeSelect = (nodeId: string | null, nodeData?: any) => {
    setSelectedNodeId(nodeId);
    if (nodeId && nodeData) {
      let normalizedData;
      if (nodeData.config && typeof nodeData.config === 'object') {
        normalizedData = {
          id: nodeId,
          ...nodeData,
          ...nodeData.config,
          tools: nodeData.config.tools || nodeData.tools || [],
          native_tools: nodeData.config.native_tools || nodeData.config.mcp_tools || nodeData.native_tools || [],
          custom_tools: nodeData.config.custom_tools || nodeData.custom_tools || [],
        };
      } else {
        normalizedData = {
          id: nodeId,
          ...nodeData,
          tools: nodeData.tools || [],
          native_tools: nodeData.native_tools || [],
          custom_tools: nodeData.custom_tools || [],
        };
      }
      setSelectedNodeData(normalizedData);
      // Open right panel to Properties tab when node selected
      openRightPanel('node-config');
    } else {
      setSelectedNodeData(null);
      closeRightPanel();
    }
  };

  const handleAgentAdded = () => {
    setSelectedAgent(null);
  };

  const handleNodeConfigSave = (nodeId: string, fullConfig: any) => {
    setNodeConfigs(prev => ({ ...prev, [nodeId]: fullConfig }));
    if (workflowCanvasRef.current) {
      workflowCanvasRef.current.updateNodeConfig(nodeId, fullConfig);
    }
    if (selectedNodeId === nodeId && selectedNodeData) {
      setSelectedNodeData({
        ...selectedNodeData,
        ...fullConfig,
        config: fullConfig,
        label: fullConfig.label || fullConfig.name || selectedNodeData.label,
        name: fullConfig.name || selectedNodeData.name
      });
    }
    if (saveWorkflowTimeoutRef.current !== null) {
      clearTimeout(saveWorkflowTimeoutRef.current);
    }
    saveWorkflowTimeoutRef.current = window.setTimeout(() => {
      if (workflowCanvasRef.current) {
        workflowCanvasRef.current.saveWorkflow(true);
      }
    }, 800);
  };

  const handleNodeDelete = (nodeId: string) => {
    if (workflowCanvasRef.current) {
      workflowCanvasRef.current.deleteNode(nodeId);
    }
    setSelectedNodeId(null);
    setSelectedNodeData(null);
    setNodeConfigs(prev => { const n = { ...prev }; delete n[nodeId]; return n; });
    closeRightPanel();
  };

  const handleWorkflowOpen = (workflowId: number) => {
    setSelectedWorkflowId(workflowId);
    navigate('/studio');
    setWorkflowName(`Workflow ${workflowId}`);
    setWorkflowStatus('saved');
  };

  const selectedNodeConfig = selectedNodeId ? nodeConfigs[selectedNodeId] : null;

  // ── Render current page for Workspace fallback ──────────
  const renderCurrentPage = () => {
    switch (currentView) {
      case 'home': return <HomePage />;
      case 'studio': return (
        <WorkflowCanvas
          ref={workflowCanvasRef}
          selectedAgent={selectedAgent}
          selectedRecipe={selectedRecipe}
          onWorkflowSelect={setSelectedWorkflowId}
          onNodeSelect={handleNodeSelect}
          onNodeDelete={handleNodeDelete}
          onExecutionStart={handleExecutionStart}
          onAgentAdded={handleAgentAdded}
          onRecipeInserted={() => setSelectedRecipe(null)}
          workflowId={selectedWorkflowId}
          onTabChange={handleTabChange}
          initialTab={workflowTab}
          onTokenCostUpdate={setTokenCostInfo}
          onTaskHistoryUpdate={setTaskHistory}
          onSelectedTaskChange={setSelectedHistoryTask}
          externalSelectedTask={selectedHistoryTask}
        />
      );
      case 'library': return (
        <WorkflowLibraryView
          onWorkflowSelect={setSelectedWorkflowId}
          onWorkflowOpen={handleWorkflowOpen}
        />
      );
      case 'agents': return null; // Handled by layout2 AgentEditor
      case 'skills': return <SkillLibrary />;
      case 'tools': return <ToolLibrary />;
      case 'prompt': return <PromptAssemblyPage />;
      case 'knowledge': return null; // Handled by layout2 KnowledgeSidebar + KnowledgeView
      case 'analysis': return <AnalysisPage />;
      // settings → popover only, no full-page view
      case 'playground': return <PlaygroundPage />;
      case 'deepagent-studio': return <DeepAgentStudioPage />;
      default: return <HomePage />;
    }
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100vh', width: '100%', overflow: 'hidden' }}>
      {/* Main row */}
      <div style={{ display: 'flex', flex: 1, minHeight: 0 }}>
        <ActivityBar onClickActivity={(activity) => {
          const view = ACTIVITY_TO_VIEW[activity];
          if (view) handleViewChange(view);
        }} />

        {/* Sidebar: ModernAgentLibrary in studio, default TreeView otherwise */}
        <LeftSidebar>
          {currentView === 'studio' && (
            <ModernAgentLibrary
              onSelectAgent={(agent) => { setSelectedAgent(agent); handleTabChange('studio'); }}
              onSelectRecipe={(recipe) => { setSelectedRecipe(recipe); handleTabChange('studio'); }}
              taskHistory={taskHistory}
              loadingHistory={loadingHistory}
              selectedHistoryTask={selectedHistoryTask}
              onSelectHistoryTask={(task) => { setSelectedHistoryTask(task); if (task) handleTabChange('results'); }}
              activePanel={sidebarPanel}
              onPanelChange={handleSidebarPanelChange}
            />
          )}
        </LeftSidebar>

        {/* Center column */}
        <div style={{ display: 'flex', flexDirection: 'column', flex: 1, minWidth: 0, minHeight: 0 }}>
          <div style={{ flex: 1, minHeight: 0, display: 'flex' }}>
            <Workspace fallback={renderCurrentPage()} />
          </div>
          <BottomPanel />
        </div>

        {/* Right panel: NodeConfigPanel when node selected, Chat otherwise */}
        {(rightPanelOpen || selectedNodeData) && (
        <NodeSidebar>
          {currentView === 'studio' && selectedNodeId && selectedNodeData && (
            <NodeConfigPanel
              selectedNode={{
                id: selectedNodeId,
                name: selectedNodeData.label || selectedNodeData.name || selectedNodeData.config?.name || selectedNodeId,
                agentType: selectedNodeData.agentType,
                model: selectedNodeData.model || selectedNodeData.config?.model,
                system_prompt: selectedNodeData.system_prompt || selectedNodeData.config?.system_prompt || '',
                temperature: selectedNodeData.temperature ?? selectedNodeData.config?.temperature ?? 0.7,
                max_tokens: selectedNodeData.max_tokens || selectedNodeData.config?.max_tokens || 4000,
                max_retries: selectedNodeData.max_retries || selectedNodeData.config?.max_retries || 3,
                recursion_limit: selectedNodeData.recursion_limit || selectedNodeData.config?.recursion_limit || 300,
                tools: selectedNodeData.tools || selectedNodeData.config?.tools || [],
                native_tools: selectedNodeData.native_tools || selectedNodeData.config?.native_tools || [],
                custom_tools: selectedNodeData.custom_tools || selectedNodeData.config?.custom_tools || [],
                middleware: selectedNodeData.middleware || selectedNodeData.config?.middleware || [],
                condition: selectedNodeData.condition || selectedNodeData.config?.condition,
                max_iterations: selectedNodeData.max_iterations || selectedNodeData.config?.max_iterations,
                exit_condition: selectedNodeData.exit_condition || selectedNodeData.config?.exit_condition,
                data: selectedNodeData,
                tool_type: (selectedNodeData as any).tool_type || selectedNodeData.config?.tool_type,
                tool_id: (selectedNodeData as any).tool_id || selectedNodeData.config?.tool_id,
                tool_params: (selectedNodeData as any).tool_params || selectedNodeData.config?.tool_params,
                subagents: (selectedNodeData as any).subagents || selectedNodeData.config?.subagents || [],
                use_deepagents: (selectedNodeData as any).use_deepagents || selectedNodeData.config?.use_deepagents || false
              }}
              onClose={() => { setSelectedNodeId(null); setSelectedNodeData(null); closeRightPanel(); }}
              onSave={handleNodeConfigSave}
              onDelete={handleNodeDelete}
              tokenCostInfo={tokenCostInfo || undefined}
            />
          )}
        </NodeSidebar>
        )}
      </div>

      <StatusBar
        model={selectedNodeData?.model || 'GPT-4o'}
        tokens={tokenCostInfo?.totalTokens}
        task={workflowStatus === 'running' || executing ? 'Workflow Running' : null}
      />
    </div>
  );
}

function App() {
  return (
    <ThemeProvider>
      <ToastProvider>
        <HashRouter>
          <ProjectProvider>
            <ChatProvider>
              <LayoutProvider>
                <AppContent />
                <GlobalChatModal />
              </LayoutProvider>
            </ChatProvider>
          </ProjectProvider>
        </HashRouter>
        <ToastContainer />
      </ToastProvider>
    </ThemeProvider>
  );
}

export default App;
