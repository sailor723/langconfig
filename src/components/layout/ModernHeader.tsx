/**
 * Copyright (c) 2025 Cade Russell (Ghost Peony)
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { MessageSquare } from 'lucide-react';
import { useProject } from "../../contexts/ProjectContext";
import { useChat } from '../../features/chat/state/ChatContext';
import AgentsMdEditor from '../../features/projects/AgentsMdEditor';

interface ModernHeaderProps {
  currentView: 'studio' | 'library' | 'settings' | 'knowledge' | 'agents' | 'skills' | 'home' | 'analysis' | 'playground' | 'tools' | 'prompt' | 'deepagent-studio';
  onViewChange: (view: 'studio' | 'library' | 'settings' | 'knowledge' | 'agents' | 'skills' | 'home' | 'analysis' | 'playground' | 'tools' | 'prompt' | 'deepagent-studio') => void;
}

export default function ModernHeader({
  currentView,
  onViewChange
}: ModernHeaderProps) {
  const { activeProject, projects, setActiveProjectId, loading } = useProject();
  const { openChat } = useChat();
  const [showProjectDropdown, setShowProjectDropdown] = useState(false);
  const [showAgentsMdEditor, setShowAgentsMdEditor] = useState(false);
  const [showBuildDropdown, setShowBuildDropdown] = useState(false);
  const { t } = useTranslation('chat');

  return (
    <header className="flex items-center justify-between whitespace-nowrap border-b px-4 py-4 z-20 shrink-0 h-20" style={{ backgroundColor: 'var(--color-header-background)', borderBottomColor: 'var(--color-border-dark)' }}>
      {/* Left: Logo - centered over agent library sidebar */}
      <div className="flex items-center h-full justify-center" style={{ width: '320px', marginLeft: '-16px' }}>

        <button
          onClick={() => onViewChange('home')}
          style={{
            backgroundColor: 'transparent',
            borderRadius: '0',
            padding: '0',
            boxShadow: 'none',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            gap: '16px',
            overflow: 'visible',
            height: '70px',
            maxWidth: '280px',
            border: 'none',
            cursor: 'pointer',
          }}
        >
          {/* GhostPeony Avatar Icon - rotated 45deg right */}
          <img
            src="/GhostPeony.png"
            alt="GhostPeony"
            style={{
              height: '68px',
              width: '68px',
              display: 'block',
              borderRadius: '14px',
              objectFit: 'cover',
              transform: 'rotate(-45deg)', // 45 degrees to the right
            }}
          />
          {/* LangConfig Logo */}
          <img
            src="/langconfignewlogo.png"
            alt="LangConfig"
            style={{
              height: '100px',
              width: 'auto',
              display: 'block',
              filter: 'brightness(0) invert(1)', // Makes the logo white
              margin: '0',
              marginTop: '15px', // Shift logo down slightly
            }}
          />
        </button>
      </div>

      {/* Center: Navigation Tabs */}
      <nav className="flex items-center gap-2 absolute left-1/2 transform -translate-x-1/2">
        <button
          onClick={() => onViewChange('studio')}
          className={`px-4 py-2 text-sm rounded-lg transition-all border ${currentView === 'studio'
            ? 'bg-white/30 text-white font-semibold border-white/40'
            : 'text-white/90 font-medium hover:bg-white/15 hover:text-white border-transparent hover:border-white/20'
            } `}
          style={{
            textShadow: currentView === 'studio' ? '0 1px 2px rgba(0, 0, 0, 0.25)' : '0 1px 2px rgba(0, 0, 0, 0.15)',
            backdropFilter: currentView === 'studio' ? 'blur(8px)' : 'none'
          }}
        >
          <span className="flex items-center gap-2">
            <span className="material-symbols-outlined text-base">account_tree</span>
            {t('nav_studio')}
          </span>
        </button>
        <button
          onClick={() => onViewChange('agents')}
          className={`px-4 py-2 text-sm rounded-lg transition-all border ${currentView === 'agents'
            ? 'bg-white/30 text-white font-semibold border-white/40'
            : 'text-white/90 font-medium hover:bg-white/15 hover:text-white border-transparent hover:border-white/20'
            } `}
          style={{
            textShadow: currentView === 'agents' ? '0 1px 2px rgba(0, 0, 0, 0.25)' : '0 1px 2px rgba(0, 0, 0, 0.15)',
            backdropFilter: currentView === 'agents' ? 'blur(8px)' : 'none'
          }}
        >
          <span className="flex items-center gap-2">
            <span className="material-symbols-outlined text-base">psychology</span>
            {t('nav_agents')}
          </span>
        </button>
        <button
          onClick={() => onViewChange('library')}
          className={`px-4 py-2 text-sm rounded-lg transition-all border ${currentView === 'library'
            ? 'bg-white/30 text-white font-semibold border-white/40'
            : 'text-white/90 font-medium hover:bg-white/15 hover:text-white border-transparent hover:border-white/20'
            } `}
          style={{
            textShadow: currentView === 'library' ? '0 1px 2px rgba(0, 0, 0, 0.25)' : '0 1px 2px rgba(0, 0, 0, 0.15)',
            backdropFilter: currentView === 'library' ? 'blur(8px)' : 'none'
          }}
        >
          <span className="flex items-center gap-2">
            <span className="material-symbols-outlined text-base">folder</span>
            {t('nav_library')}
          </span>
        </button>
        <button
          onClick={() => onViewChange('knowledge')}
          className={`px-4 py-2 text-sm rounded-lg transition-all border ${currentView === 'knowledge'
            ? 'bg-white/30 text-white font-semibold border-white/40'
            : 'text-white/90 font-medium hover:bg-white/15 hover:text-white border-transparent hover:border-white/20'
            }`}
          style={{
            textShadow: currentView === 'knowledge' ? '0 1px 2px rgba(0, 0, 0, 0.25)' : '0 1px 2px rgba(0, 0, 0, 0.15)',
            backdropFilter: currentView === 'knowledge' ? 'blur(8px)' : 'none'
          }}
        >
          <span className="flex items-center gap-2">
            <span className="material-symbols-outlined text-base">database</span>
            {t('nav_knowledge')}
          </span>
        </button>
                {/* Build dropdown */}
        <div className="relative">
          <button
            onClick={() => setShowBuildDropdown(!showBuildDropdown)}
            className={`px-4 py-2 text-sm rounded-lg transition-all border flex items-center gap-2 ${
              ['tools', 'prompt', 'skills'].includes(currentView)
                ? 'bg-white/30 text-white font-semibold border-white/40'
                : 'text-white/90 font-medium hover:bg-white/15 hover:text-white border-transparent hover:border-white/20'
            }`}
            style={{
              textShadow: ['tools', 'prompt', 'skills'].includes(currentView) ? '0 1px 2px rgba(0, 0, 0, 0.25)' : '0 1px 2px rgba(0, 0, 0, 0.15)',
              backdropFilter: ['tools', 'prompt', 'skills'].includes(currentView) ? 'blur(8px)' : 'none'
            }}
          >
            <span className="flex items-center gap-2">
              <span className="material-symbols-outlined text-base">build</span>
              Build
              <span className="material-symbols-outlined text-sm ml-1">{showBuildDropdown ? 'expand_less' : 'expand_more'}</span>
            </span>
          </button>
          {showBuildDropdown && (
            <>
              <div className="fixed inset-0 z-30" onClick={() => setShowBuildDropdown(false)} />
              <div className="absolute left-0 mt-2 w-40 rounded-lg shadow-lg border z-40 overflow-hidden"
                style={{ backgroundColor: 'var(--color-panel-dark)', borderColor: 'var(--color-border-dark)' }}>
                {[
                  { view: 'skills' as const, icon: 'auto_awesome', label: t('nav_skills') },
                  { view: 'tools' as const, icon: 'build', label: t('nav_tools') },
                  { view: 'prompt' as const, icon: 'layers', label: t('nav_prompt') },
                ].map(item => (
                  <button
                    key={item.view}
                    onClick={() => { onViewChange(item.view); setShowBuildDropdown(false); }}
                    className={`w-full flex items-center gap-2 px-4 py-2.5 text-sm text-left transition-all ${
                      currentView === item.view
                        ? 'bg-white/15 text-white font-semibold'
                        : 'text-white/80 hover:bg-white/10 hover:text-white'
                    }`}
                  >
                    <span className="material-symbols-outlined text-base">{item.icon}</span>
                    {item.label}
                  </button>
                ))}
              </div>
            </>
          )}
        </div><button
          onClick={() => onViewChange('analysis')}
          className={`px-4 py-2 text-sm rounded-lg transition-all border ${currentView === 'analysis'
            ? 'bg-white/30 text-white font-semibold border-white/40'
            : 'text-white/90 font-medium hover:bg-white/15 hover:text-white border-transparent hover:border-white/20'
            }`}
          style={{
            textShadow: currentView === 'analysis' ? '0 1px 2px rgba(0, 0, 0, 0.25)' : '0 1px 2px rgba(0, 0, 0, 0.15)',
            backdropFilter: currentView === 'analysis' ? 'blur(8px)' : 'none'
          }}
        >
          <span className="flex items-center gap-2">
            <span className="material-symbols-outlined text-base">monitoring</span>
            Analysis
          </span>
        </button>
        <button
          onClick={() => onViewChange('deepagent-studio')}
          className={`px-4 py-2 text-sm rounded-lg transition-all border ${currentView === 'deepagent-studio'
            ? 'bg-white/30 text-white font-semibold border-white/40'
            : 'text-white/90 font-medium hover:bg-white/15 hover:text-white border-transparent hover:border-white/20'
            }`}
          style={{
            textShadow: currentView === 'deepagent-studio' ? '0 1px 2px rgba(0, 0, 0, 0.25)' : '0 1px 2px rgba(0, 0, 0, 0.15)',
            backdropFilter: currentView === 'deepagent-studio' ? 'blur(8px)' : 'none'
          }}
          title="DeepAgent Studio — visualize any DeepAgent's structure"
        >
          <span className="flex items-center gap-2">
            <span className="material-symbols-outlined text-base">hub</span>
            DeepAgent Studio
          </span>
        </button>
      </nav>

      {/* Right: Project Selector & Action Buttons */}
      <div className="flex items-center gap-2">
        {/* Chat Button */}
        <button
          onClick={() => openChat()}
          className="flex items-center gap-2 px-3 h-10 rounded-lg transition-all bg-white/15 text-white font-semibold hover:bg-white/25 border border-white/20"
          title={t('nav_chat')}
        >
          <MessageSquare className="w-4 h-4" />
          <span className="text-sm">Chat</span>
        </button>

        {/* AGENTS.md Editor (project-level context for DeepAgent MemoryMiddleware) */}
        {activeProject && (
          <button
            onClick={() => setShowAgentsMdEditor(true)}
            className="flex items-center gap-1.5 px-2.5 h-10 rounded-lg hover:bg-white/15 transition-all text-white/90 hover:text-white border border-transparent hover:border-white/20 text-xs"
            title="Edit AGENTS.md — loaded into DeepAgent system prompt via MemoryMiddleware"
            style={{ textShadow: '0 1px 2px rgba(0, 0, 0, 0.15)' }}
          >
            <span className="material-symbols-outlined text-base">description</span>
            <span>AGENTS.md</span>
          </button>
        )}

        {/* Project Selector */}
        <div className="relative">
          <button
            onClick={() => setShowProjectDropdown(!showProjectDropdown)}
            className="flex items-center gap-2 px-3 py-2 rounded-lg hover:bg-white/15 transition-all text-white/90 hover:text-white border border-white/20 hover:border-white/40"
            style={{
              textShadow: '0 1px 2px rgba(0, 0, 0, 0.15)',
              minWidth: '150px'
            }}
          >
            <span className="material-symbols-outlined text-base">folder_open</span>
            <span className="text-sm font-medium truncate">
              {loading ? t('nav_loading') : activeProject?.name || t('nav_no_project')}
            </span>
            <span className="material-symbols-outlined text-base ml-auto">
              {showProjectDropdown ? 'expand_less' : 'expand_more'}
            </span>
          </button>

          {/* Dropdown */}
          {showProjectDropdown && (
            <>
              <div
                className="fixed inset-0 z-30"
                onClick={() => setShowProjectDropdown(false)}
              />
              <div
                className="absolute right-0 mt-2 w-64 rounded-lg shadow-lg border z-40 max-h-96 overflow-auto"
                style={{
                  backgroundColor: 'var(--color-panel-dark)',
                  borderColor: 'var(--color-border-dark)'
                }}
              >
                {projects.length === 0 ? (
                  <div className="px-4 py-3 text-sm" style={{ color: 'var(--color-text-muted)' }}>
                    {t('nav_no_projects')}
                  </div>
                ) : (
                  projects.map(project => (
                    <button
                      key={project.id}
                      onClick={() => {
                        setActiveProjectId(project.id);
                        setShowProjectDropdown(false);
                      }}
                      className="w-full px-4 py-2 text-left hover:bg-white/5 transition-all flex items-center justify-between"
                    >
                      <div className="flex-1 min-w-0">
                        <div
                          className="text-sm font-medium truncate"
                          style={{ color: activeProject?.id === project.id ? 'var(--color-primary)' : 'var(--color-text-primary)' }}
                        >
                          {project.name}
                        </div>
                        {project.description && (
                          <div className="text-xs truncate" style={{ color: 'var(--color-text-muted)' }}>
                            {project.description}
                          </div>
                        )}
                      </div>
                      {activeProject?.id === project.id && (
                        <span className="material-symbols-outlined text-base ml-2" style={{ color: 'var(--color-primary)' }}>
                          check
                        </span>
                      )}
                    </button>
                  ))
                )}
              </div>
            </>
          )}
        </div>

        <button
          onClick={() => onViewChange('settings')}
          className="flex items-center justify-center h-10 w-10 rounded-lg hover:bg-white/15 transition-all text-white/90 hover:text-white border border-transparent hover:border-white/20"
          title="Settings"
          style={{
            textShadow: '0 1px 2px rgba(0, 0, 0, 0.15)'
          }}
        >
          <span className="material-symbols-outlined text-base">settings</span>
        </button>
      </div>

      {/* AGENTS.md Editor Modal (DeepAgent MemoryMiddleware) */}
      {showAgentsMdEditor && activeProject && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/50"
          onClick={() => setShowAgentsMdEditor(false)}
        >
          <div
            className="bg-white dark:bg-gray-900 rounded-lg shadow-2xl w-[800px] max-w-[95vw] h-[700px] max-h-[90vh] flex flex-col overflow-hidden"
            onClick={(e) => e.stopPropagation()}
          >
            <AgentsMdEditor
              projectId={activeProject.id}
              onClose={() => setShowAgentsMdEditor(false)}
            />
          </div>
        </div>
      )}
    </header>
  );
}
