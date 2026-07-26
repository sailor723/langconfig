/**
 * LayoutPreview — standalone entry for previewing the VS Code-style layout shell.
 *
 * This is served at /layout-preview.html on port 1420, or separately on port 1421.
 * It renders the layout2 components with mock content so you can see the
 * complete VS Code layout without touching the main app.
 */
import React from 'react';
import ReactDOM from 'react-dom/client';
import { ThemeProvider } from './lib/themes';
import { LayoutProvider, useLayoutState, type Tab } from './components/layout2/useLayout';
import ActivityBar from './components/layout2/ActivityBar';
import LeftSidebar from './components/layout2/LeftSidebar';
import Workspace from './components/layout2/Workspace';
import NodeSidebar from './components/layout2/NodeSidebar';
import BottomPanel from './components/layout2/BottomPanel';
import StatusBar from './components/layout2/StatusBar';
import './index.css';

// ── Mock content for the workspace ────────────────────────

function EditorPlaceholder({ label }: { label: string }) {
  return (
    <div style={{ padding: 24, color: '#cccccc', fontFamily: '"SF Mono", "Fira Code", monospace', fontSize: 13 }}>
      <div style={{ marginBottom: 16 }}>
        <span style={{ color: '#6a9955' }}>// {label}</span>
      </div>
      <div style={{ marginBottom: 8 }}>
        <span style={{ color: '#569cd6' }}>import</span> {'{ ' }<span style={{ color: '#dcdcaa' }}>Agent</span>{' } '}<span style={{ color: '#569cd6' }}>from</span> <span style={{ color: '#ce9178' }}>'langchain/agents'</span>;
      </div>
      <div style={{ marginBottom: 8 }}>
        <span style={{ color: '#569cd6' }}>const</span> <span style={{ color: '#dcdcaa' }}>agent</span> = <span style={{ color: '#569cd6' }}>new</span> <span style={{ color: '#dcdcaa' }}>Agent</span>({'{'}
      </div>
      <div style={{ paddingLeft: 20, marginBottom: 8 }}>
        <span style={{ color: '#9cdcfe' }}>model</span>: <span style={{ color: '#ce9178' }}>'gpt-4o'</span>,
      </div>
      <div style={{ paddingLeft: 20, marginBottom: 8 }}>
        <span style={{ color: '#9cdcfe' }}>temperature</span>: <span style={{ color: '#b5cea8' }}>0.7</span>,
      </div>
      <div style={{ marginBottom: 8 }}>
        {'}'});
      </div>
    </div>
  );
}

// ── Layout shell with mock data ──────────────────────────

function LayoutPreviewInner() {
  const { setBottomPanelOpen, setActiveActivity } = useLayoutState();

  // Open bottom panel and default to DeepAgents activity on mount
  React.useEffect(() => {
    setActiveActivity('deepagents');
    setBottomPanelOpen(true);
  }, []);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100vh', width: '100%', overflow: 'hidden' }}>
      {/* Main row */}
      <div style={{ display: 'flex', flex: 1, minHeight: 0 }}>
        <ActivityBar />
        <LeftSidebar />

        {/* Center column: Workspace on top, BottomPanel below */}
        <div style={{ display: 'flex', flexDirection: 'column', flex: 1, minWidth: 0 }}>
          <Workspace
            fallback={
              <div style={{ display: 'flex', flex: 1, minWidth: 0, overflow: 'auto' }}>
                <EditorPlaceholder label="Select a file to edit" />
              </div>
            }
          />
          <BottomPanel />
        </div>

        <NodeSidebar />
      </div>
      <StatusBar model="GPT-4o" tokens={1243} task={null} />
    </div>
  );
}

function LayoutPreview() {
  return (
    <ThemeProvider>
      <LayoutProvider>
        <LayoutPreviewInner />
      </LayoutProvider>
    </ThemeProvider>
  );
}

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <LayoutPreview />
  </React.StrictMode>
);
