/**
 * Copyright (c) 2025 Cade Russell (Ghost Peony)
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in this root directory.
 *
 * App — root component.
 *
 * Layout structure (Obsidian-style shell):
 * ┌─────┬──────────┬──────────────────┬──────────┐
 * │ Act │ Left     │ Workspace        │ Right    │
 * │ Bar │ Sidebar  │ (tabs + content) │ Sidebar  │
 * ├─────┴──────────┴──────────────────┴──────────┤
 * │ Bottom Panel (chat / logs / output)          │
 * ├──────────────────────────────────────────────┤
 * │ Status Bar                                    │
 * └──────────────────────────────────────────────┘
 */
import { useState, useEffect, useRef, useCallback } from 'react';
import { HashRouter, Routes, Route, useNavigate, useLocation } from 'react-router-dom';
import { ThemeProvider } from './lib/themes';
import { ProjectProvider } from './contexts/ProjectContext';
import { ToastProvider, ToastContainer } from './hooks/useToast';
import { ChatProvider } from './features/chat/state/ChatContext';
import GlobalChatModal from './features/chat/ui/GlobalChatModal';
import apiClient from './lib/api-client';

// Pages
import HomePage from './pages/HomePage';
import WorkflowCanvas, { WorkflowCanvasRef, WorkflowRecipe } from './features/workflows/canvas/WorkflowCanvas';
import { TaskHistoryEntry } from './features/workflows/canvas/types';
import NodeConfigPanel from './features/workflows/node-config/NodeConfigPanel';
import WorkflowLibraryView from './features/workflows/library/WorkflowLibraryView';
import ModernAgentLibrary from './features/agents/ui/ModernAgentLibrary';
import AgentLoadouts from './features/agents/ui/AgentLoadouts';
import SkillLibrary from './features/skills/ui/SkillLibrary';
import ToolLibrary from './features/tools/ToolLibrary';
import PromptAssemblyPage from './pages/PromptAssemblyPage';
import KnowledgeBaseView from './features/knowledge/ui/KnowledgeBaseView';
import AnalysisPage from './pages/AnalysisPage';
import SettingsView from './pages/SettingsPage';
import PlaygroundPage from './pages/PlaygroundPage';
import DeepAgentStudioPage from './features/deepagent-studio-v2/ModernStudioPage';

// New layout components
import { LayoutProvider, useLayoutState, ACTIVITIES, type ActivityId } from './components/layout2/useLayout';
import ActivityBar from './components/layout2/ActivityBar';
import LeftSidebar from './components/layout2/LeftSidebar';
import Workspace from './components/layout2/Workspace';
import NodeSidebar from './components/layout2/NodeSidebar';
import BottomPanel from './components/layout2/BottomPanel';
import StatusBar from './components/layout2/StatusBar';
import QuickFilePicker from './components/layout2/QuickFilePicker';

// ── Types ───────────────────────────────────────────────
type View = 'studio' | 'library' | 'settings' | 'knowledge' | 'agents' | 'skills' | 'home' | 'analysis' | 'playground' | 'tools' | 'prompt' | 'deepagent-studio';
type WorkflowStatus = 'draft' | 'saved' | 'running' | 'completed' | 'failed';

// Map route path → View
const ROUTE_TO_VIEW: Record<string, View> = {
  '/': 'home', '/home': 'home',
  '/studio': 'studio', '/results': 'studio',
  '/library': 'library',
  '/agents': 'agents', '/deepagents': 'agents',
  '/knowledge': 'knowledge',
  '/skills': 'skills',
  '/tools': 'tools',
  '/prompt': 'prompt',
  '/analysis': 'analysis',
  '/settings': 'settings',
  '/playground': 'playground',
  '/deepagent-studio': 'deepagent-studio',
};

// Map View → route path
const VIEW_ROUTE: Record<View, string> = {
  home: '/home', studio: '/studio', library: '/library',
  agents: '/agents', skills: '/skills', knowledge: '/knowledge',
  analysis: '/analysis', settings: '/settings', playground: '/playground',
  tools: '/tools', prompt: '/prompt', 'deepagent-studio': '/deepagent-studio',
};

// Map View → ActivityId (for ActivityBar highlighting)
const VIEW_TO_ACTIVITY: Record<View, ActivityId | null> = {
  home: null,
  studio: 'workflows',
  library: 'workflows',
  agents: 'agents',
  skills: 'library',
  tools: 'library',
  prompt: 'library',
  knowledge: 'library',
  analysis: 'analysis',
  settings: 'settings',
  playground: 'workflows',
  'deepagent-studio': 'workflows',
};

// ── Inner AppContent ─────────────────────────────────────
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
  const [nodeConfigs, setNodeConfigs] = useState<Record<string, NodeConfig>>({});
  const [tokenCostInfo, setTokenCostInfo] = useState<{ totalTokens: number; promptTokens: number; completionTokens: number; costString: string; } | null>(null);
  const [taskHistory, setTaskHistory] = useState<TaskHistoryEntry[]>([]);
  const [selectedHistoryTask, setSelectedHistoryTask] = useState<TaskHistoryEntry | null>(null);
  const [loadingHistory, setLoadingHistory] = useState(false);
  const [sidebarPanel, setSidebarPanel] = useState<'agents' | 'history'>('agents');

  // Layout state
  const { setActiveActivity, rightPanelOpen, openRightPanel, closeRightPanel } = useLayoutState();

  // Cmd+P / Ctrl+P quick file picker
  const [quickPickerOpen, setQuickPickerOpen] = useState(false);
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'p') {
        e.preventDefault();
        setQuickPickerOpen(v => !v);
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, []);

  // Current view from route
  const currentView: View = ROUTE_TO_VIEW[location.pathname] ?? 'home';

  // Sync ActivityBar with current view
  useEffect(() => {
    const activity = VIEW_TO_ACTIVITY[currentView];
    if (activity) setActiveActivity(activity);
  }, [currentView, setActiveActivity]);

  // Sync right panel with node selection
  useEffect(() => {
    if (currentView === 'studio' && selectedNodeId && selectedNodeData) {
      openRightPanel('node-config');
    } else if (rightPanelOpen) {
      closeRightPanel();
    }
  }, [currentView, selectedNodeId]);

  const handleViewChange = useCallback((view: View) => {
    // Check for unsaved workflow changes
    if (currentView === 'studio' && workflowCanvasRef.current?.hasUnsavedChanges()) {
      const confirmLeave = window.confirm(
        'You have unsaved workflow changes. Click OK to stay and save, Cancel to leave.'
      );
      if (confirmLeave) return;
    }
    navigate(VIEW_ROUTE[view]);
  }, [currentView, navigate]);

  // Handle node config save
  const handleNodeConfigSave = useCallback((nodeId: string, fullConfig: any) => {
    setNodeConfigs(prev => ({ ...prev, [nodeId]: fullConfig }));
    workflowCanvasRef.current?.updateNodeConfig(nodeId, fullConfig);

    // Update selectedNodeData for real-time sync
    if (selectedNodeId === nodeId && selectedNodeData) {
      setSelectedNodeData({
        ...selectedNodeData,
        ...fullConfig,
        config: fullConfig,
        label: fullConfig.label || fullConfig.name || selectedNodeData.label,
        name: fullConfig.name || selectedNodeData.name,
      });
    }

    // Debounced auto-save (800ms)
    if (saveWorkflowTimeoutRef.current) clearTimeout(saveWorkflowTimeoutRef.current);
    saveWorkflowTimeoutRef.current = window.setTimeout(() => {
      workflowCanvasRef.current?.saveWorkflow(true);
    }, 800);
  }, [selectedNodeId, selectedNodeData]);

  const handleNodeDelete = useCallback((nodeId: string) => {
    workflowCanvasRef.current?.deleteNode(nodeId);
    setSelectedNodeId(null);
    setSelectedNodeData(null);
    setNodeConfigs(prev => { const n = { ...prev }; delete n[nodeId]; return n; });
  }, []);

  // ── Render ─────────────────────────────────────────
  // The layout shell is rendered here inside the route context
  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100vh', width: '100%', overflow: 'hidden' }}>
      {/* Main row: ActivityBar | LeftSidebar | Workspace | NodeSidebar */}
      <div style={{ display: 'flex', flex: 1, minHeight: 0 }}>
        <ActivityBar />

        {/* Left sidebar — contextual, shown for most studio-like views */}
        {currentView === 'studio' && (
          <ModernAgentLibrary
            onSelectAgent={(agent) => {
              setSelectedAgent(agent);
            }}
            onSelectRecipe={(recipe) => {
              setSelectedRecipe(recipe);
            }}
            taskHistory={taskHistory}
            loadingHistory={loadingHistory}
            selectedHistoryTask={selectedHistoryTask}
            onSelectHistoryTask={(task) => {
              setSelectedHistoryTask(task);
            }}
            activePanel={sidebarPanel}
            onPanelChange={(panel) => setSidebarPanel(panel)}
          />
        )}
        {/* Default Obsidian-style LeftSidebar for non-studio views */}
        {currentView !== 'studio' && <LeftSidebar />}

        {/* Center workspace — renders the active page */}
        <Workspace
          fallback={
            <div style={{ display: 'flex', flexDirection: 'column', flex: 1, minWidth: 0, overflow: 'auto' }}>
              {currentView === 'home' && <HomePage />}
              {currentView === 'studio' && (
                <WorkflowCanvas
                  ref={workflowCanvasRef}
                  selectedAgent={selectedAgent}
                  selectedRecipe={selectedRecipe}
                  onWorkflowSelect={setSelectedWorkflowId}
                  onNodeSelect={(nodeId, data) => {
                    setSelectedNodeId(nodeId);
                    if (nodeId && data) {
                      const norm = data.config ? { ...data, ...data.config } : data;
                      setSelectedNodeData({ id: nodeId, ...norm });
                    } else {
                      setSelectedNodeData(null);
                    }
                  }}
                  onNodeDelete={handleNodeDelete}
                  onExecutionStart={() => { setExecuting(true); setWorkflowStatus('running'); }}
                  onAgentAdded={() => setSelectedAgent(null)}
                  onRecipeInserted={() => setSelectedRecipe(null)}
                  workflowId={selectedWorkflowId}
                  onTabChange={(tab) => setWorkflowTab(tab)}
                  initialTab={workflowTab}
                  onTokenCostUpdate={setTokenCostInfo}
                  onTaskHistoryUpdate={setTaskHistory}
                  onSelectedTaskChange={setSelectedHistoryTask}
                  externalSelectedTask={selectedHistoryTask}
                />
              )}
              {currentView === 'library' && (
                <WorkflowLibraryView
                  onWorkflowSelect={setSelectedWorkflowId}
                  onWorkflowOpen={(id) => { setSelectedWorkflowId(id); navigate('/studio'); }}
                />
              )}
              {currentView === 'agents' && <AgentLoadouts />}
              {currentView === 'skills' && <SkillLibrary />}
              {currentView === 'tools' && <ToolLibrary />}
              {currentView === 'prompt' && <PromptAssemblyPage />}
              {currentView === 'knowledge' && <KnowledgeBaseView />}
              {currentView === 'analysis' && <AnalysisPage />}
              {currentView === 'settings' && <SettingsView />}
              {currentView === 'playground' && <PlaygroundPage />}
              {currentView === 'deepagent-studio' && <DeepAgentStudioPage />}
            </div>
          }
        />

        {/* Right panel — node config (when node selected in studio) */}
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
              tool_type: (selectedNodeData as any).tool_type || (selectedNodeData.config as any)?.tool_type,
              tool_id: (selectedNodeData as any).tool_id || (selectedNodeData.config as any)?.tool_id,
              tool_params: (selectedNodeData as any).tool_params || (selectedNodeData.config as any)?.tool_params,
              subagents: (selectedNodeData as any).subagents || selectedNodeData.config?.subagents || [],
              use_deepagents: (selectedNodeData as any).use_deepagents || selectedNodeData.config?.use_deepagents || false,
            }}
            onClose={() => { setSelectedNodeId(null); setSelectedNodeData(null); }}
            onSave={handleNodeConfigSave}
            onDelete={handleNodeDelete}
            tokenCostInfo={tokenCostInfo || undefined}
          />
        )}
        {currentView !== 'studio' && <NodeSidebar />}
      </div>

      {/* Bottom panel */}
      <BottomPanel />
      <StatusBar model="GPT-4o" tokens={1234} />

      {/* Cmd+P quick file picker */}
      {quickPickerOpen && <QuickFilePicker onClose={() => setQuickPickerOpen(false)} />}
    </div>
  );
}

// ── Root App ─────────────────────────────────────────────
function App() {
  return (
    <ThemeProvider>
      <ToastProvider>
        <LayoutProvider>
          <HashRouter>
            <ProjectProvider>
              <ChatProvider>
                <AppContent />
                <GlobalChatModal />
              </ChatProvider>
            </ProjectProvider>
          </HashRouter>
        </LayoutProvider>
        <ToastContainer />
      </ToastProvider>
    </ThemeProvider>
  );
}

export default App;

// ── Type definitions (moved here from the old App.tsx) ──
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
  };
}
