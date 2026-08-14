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
import WorkflowCanvas, { WorkflowCanvasRef, WorkflowRecipe } from './features/workflows/canvas/WorkflowCanvas';
import { TaskHistoryEntry } from './features/workflows/canvas/types';
import NodeConfigPanel from './features/workflows/node-config/NodeConfigPanel';
import PlaygroundPage from './pages/PlaygroundPage';
import DeepAgentStudioPage from './features/deepagent-studio-v2/ModernStudioPage';

import ToolHomePage from './components/layout2/ToolHomePage';
import PromptHomePage from './components/layout2/PromptHomePage';
import SkillHomePage from './components/layout2/SkillHomePage';
import KnowledgeHomePage from './components/layout2/KnowledgeHomePage';
import HomePage from './pages/HomePage';
import ProjectHomePage from './pages/ProjectHomePage';
import DeepAgentHomePage from './components/layout2/DeepAgentHomePage';
import AgentHomePage from './components/layout2/AgentHomePage';
import ModelHomePage from './components/layout2/ModelHomePage';
import AnalysisPage from './pages/AnalysisPage';
import { ThemeProvider } from './lib/themes';
import { ProjectProvider } from './contexts/ProjectContext';
import { ToastProvider, ToastContainer } from './hooks/useToast';
import { ChatProvider } from './features/chat/state/ChatContext';
import GlobalChatModal from './features/chat/ui/GlobalChatModal';
import ChatPage from './features/chat/ui/ChatPage';
import apiClient from './lib/api-client';
import { useProject } from './contexts/ProjectContext';
import SetupWizard from './components/layout2/SetupWizard';

// Layout2 components
import { LayoutProvider, useLayoutState, type ActivityId } from './components/layout2/useLayout';
import ActivityBar from './components/layout2/ActivityBar';
import LeftSidebar from './components/layout2/LeftSidebar';
import Workspace from './components/layout2/Workspace';
import NodeSidebar from './components/layout2/NodeSidebar';
import BottomPanel from './components/layout2/BottomPanel';
import Footer from './components/layout2/Footer';
import WorkflowStudioPage, { type WorkflowStudioRef, type StudioNodeConfig } from './components/layout2/WorkflowStudioPage';
import WorkflowStudioSidebar from './components/layout2/WorkflowStudioSidebar';
import GraphStudioPage from './features/graph-studio/GraphStudioPage';
import GraphStudioSidebar from './features/graph-studio/GraphStudioSidebar';
import GraphHomePage from './features/graph-studio/GraphHomePage';

type View = 'studio' | 'settings' | 'knowledge' | 'agents' | 'deepagents' | 'skills' | 'home' | 'analysis' | 'playground' | 'tools' | 'prompt' | 'deepagent-studio' | 'models' | 'search' | 'chat' | 'learning' | 'graph' | 'project';
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
  '/project': 'project',
  '/studio': 'studio', '/results': 'studio',
  '/graph': 'graph',
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
  '/learning': 'learning',
};

// Map View → route path
const VIEW_ROUTE: Record<View, string> = {
  home: '/home', studio: '/studio',
  project: '/project',
  graph: '/graph',
  agents: '/agents', deepagents: '/deepagents', skills: '/skills',
  knowledge: '/knowledge', analysis: '/analysis', settings: '/settings',
  playground: '/playground', tools: '/tools', prompt: '/prompt',
  'deepagent-studio': '/deepagent-studio',
  models: '/models',
  search: '/search',
  chat: '/chat',
  learning: '/learning',
};

// Map View → ActivityId
const VIEW_TO_ACTIVITY: Record<View, ActivityId | null> = {
  home: null,
  project: null,
  studio: 'workflows',
  graph: 'graph',
  agents: 'agents',
  deepagents: 'deepagents',
  skills: 'skills',
  tools: 'tools',
  prompt: 'prompt',
  knowledge: 'knowledge',
  analysis: 'analysis',
  settings: 'settings',
  playground: 'workflows',
  'deepagent-studio': 'studio',
  models: 'models',
  search: 'search',
  chat: null,
  learning: 'learning',
};

// Map ActivityId → View (for ActivityBar clicks)
const ACTIVITY_TO_VIEW: Partial<Record<ActivityId, View>> = {
  workflows:  'studio',
  graph: 'graph',
  deepagents: 'deepagents',
  agents: 'agents',
  prompt: 'prompt',
  tools: 'tools',
  knowledge: 'knowledge',
  models: 'models',
  search: 'search',
  analysis: 'analysis',
  skills: 'skills',
  settings: 'settings',
  studio: 'deepagent-studio',
  learning: 'learning',
};

function AppContent() {
  const navigate = useNavigate();
  const location = useLocation();
  const { activeProjectId } = useProject();
  const workflowCanvasRef = useRef<WorkflowCanvasRef>(null);
  const saveWorkflowTimeoutRef = useRef<number | null>(null);

  // ── First-run setup wizard ──────────────────────────────
  // While the setup status is unknown we render nothing (avoids a flash of
  // the IDE); if setup is needed, the wizard replaces the whole shell until
  // the user finishes it. Re-openable via the 'setup:open' window event.
  const [setupChecked, setSetupChecked] = useState(false);
  const [setupNeeded, setSetupNeeded] = useState(false);

  useEffect(() => {
    let cancelled = false;
    apiClient.getSetupStatus()
      .then((r: any) => { if (!cancelled) setSetupNeeded(!!r.data?.needs_setup); })
      .catch(() => {})
      .finally(() => { if (!cancelled) setSetupChecked(true); });
    const handler = () => setSetupNeeded(true);
    window.addEventListener('setup:open', handler);
    return () => { cancelled = true; window.removeEventListener('setup:open', handler); };
  }, []);

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

  // Workflow Studio (layout2) state
  const workflowStudioRef = useRef<WorkflowStudioRef>(null);
  const [studioSelectedNode, setStudioSelectedNode] = useState<{ nodeId: string; config: StudioNodeConfig } | null>(null);

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

  // Project home → open a workflow in the Studio (preloaded)
  useEffect(() => {
    const handler = (e: Event) => {
      const ce = e as CustomEvent<{ workflowId: number }>;
      if (ce.detail?.workflowId) handleWorkflowOpen(ce.detail.workflowId);
    };
    window.addEventListener('workflow:open', handler);
    return () => window.removeEventListener('workflow:open', handler);
  }, [navigate]);

  // Graph activity: show the LangGraph landing page until the user enters the
  // studio (via "Open Studio" or picking an assistant on the home page).
  const [graphEntered, setGraphEntered] = useState(false);

  // Current view from route
  const currentView: View = ROUTE_TO_VIEW[location.pathname] ?? 'home';

  // Returning to the Graph activity always starts at the home page.
  useEffect(() => {
    if (currentView !== 'graph') setGraphEntered(false);
  }, [currentView]);

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
    if (currentView === 'studio') {
      const canvas = workflowCanvasRef.current ?? workflowStudioRef.current;
      if (canvas?.hasUnsavedChanges?.()) {
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
    const canvas = workflowCanvasRef.current ?? workflowStudioRef.current;
    canvas?.saveWorkflow?.(false);
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
      case 'project': return <ProjectHomePage />;
      case 'studio': return (
        <WorkflowStudioPage
          ref={workflowStudioRef}
          workflowId={selectedWorkflowId}
          onNodeSelectChange={(nodeId, config) => {
            if (nodeId && config) {
              setStudioSelectedNode({ nodeId, config });
              openRightPanel('node-config');
            } else {
              setStudioSelectedNode(null);
              closeRightPanel();
            }
          }}
          onWorkflowSelect={setSelectedWorkflowId}
        />
      );
      case 'graph': return graphEntered ? <GraphStudioPage /> : <GraphHomePage onEnterStudio={() => setGraphEntered(true)} />;
      case 'deepagents': return <DeepAgentHomePage />;
      case 'agents': return <AgentHomePage />;
      case 'skills': return <SkillHomePage />;
      case 'tools': return <ToolHomePage />;
      case 'prompt': return <PromptHomePage />;
      case 'models': return <ModelHomePage />;
      case 'knowledge': return <KnowledgeHomePage />;
      case 'analysis': return <AnalysisPage />;
      // settings → popover only, no full-page view
      case 'playground': return <PlaygroundPage />;
      case 'deepagent-studio': return <DeepAgentStudioPage />;
      default: return <HomePage />;
    }
  };

  // Chat is a standalone full-page view — render without layout chrome.
  // Returned here, after all hooks, to satisfy the Rules of Hooks.
  if (!setupChecked) {
    // Setup status not known yet — blank screen avoids a flash of the IDE.
    return null;
  }
  if (setupNeeded) {
    return (
      <SetupWizard
        onComplete={() => {
          setSetupNeeded(false);
          navigate(activeProjectId ? '/project' : '/');
        }}
      />
    );
  }
  if (currentView === 'chat') {
    return <ChatPage />;
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100vh', width: '100%', overflow: 'hidden' }}>
      {/* Main row */}
      <div style={{ display: 'flex', flex: 1, minHeight: 0 }}>
        <ActivityBar onClickActivity={(activity) => {
          const view = ACTIVITY_TO_VIEW[activity];
          if (view) handleViewChange(view);
        }} />

        {/* Sidebar: WorkflowStudioSidebar in studio, default TreeView otherwise.
            Hidden on the home launcher (create/select project) and the project
            home page — neither is a browsing context, so no explorer/browser
            chrome should be shown there. */}
        {currentView !== 'home' && currentView !== 'project' && (
        <LeftSidebar>
          {currentView === 'studio' && (
            <WorkflowStudioSidebar
              onLoadWorkflow={(id) => {
                setSelectedWorkflowId(id);
              }}
              onLoadRecipe={(recipeId) => {
                workflowStudioRef.current?.loadRecipe?.(recipeId);
              }}
            />
          )}
          {currentView === 'graph' && graphEntered && <GraphStudioSidebar />}
        </LeftSidebar>
        )}

        {/* Center column */}
        <div style={{ display: 'flex', flexDirection: 'column', flex: 1, minWidth: 0, minHeight: 0 }}>
          <div style={{ flex: 1, minHeight: 0, display: 'flex' }}>
            <Workspace fallback={renderCurrentPage()} />
          </div>
          <BottomPanel />
        </div>

        {/* Right panel: NodeConfigPanel when node selected, Chat otherwise */}
        {(rightPanelOpen || studioSelectedNode) && (
        <NodeSidebar
          onClose={() => { setStudioSelectedNode(null); closeRightPanel(); }}
        >
          {currentView === 'studio' && studioSelectedNode && (
            <NodeConfigPanel
              selectedNode={studioSelectedNode.config as any}
              onClose={() => { setStudioSelectedNode(null); closeRightPanel(); }}
              onSave={(nodeId, config) => {
                // Route through the debounced save so right-panel edits persist
                workflowStudioRef.current?.handleNodeConfigSave?.(nodeId, config);
              }}
              onDelete={(nodeId) => {
                workflowStudioRef.current?.deleteNode?.(nodeId);
                setStudioSelectedNode(null);
                closeRightPanel();
              }}
              tokenCostInfo={tokenCostInfo || undefined}
            />
          )}
        </NodeSidebar>
        )}
      </div>

      <Footer />
    </div>
  );
}

function GlobalChatModalWrapper() {
  const location = useLocation();
  // Don't render GlobalChatModal on the standalone chat page — ChatPage
  // manages its own UI and would otherwise show a duplicate overlay.
  if (location.pathname === '/chat') return null;
  return <GlobalChatModal />;
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
                <GlobalChatModalWrapper />
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
