/**
 * Copyright (c) 2025 Cade Russell (Ghost Peony)
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */

import { useState, useCallback } from 'react';

interface UseUITogglesReturn {
  // Agent template dropdown (replaces old workflow switcher dropdown)
  showAgentDropdown: boolean;
  setShowAgentDropdown: React.Dispatch<React.SetStateAction<boolean>>;
  handleToggleAgentDropdown: () => void;
  handleCloseAgentDropdown: () => void;

  // Thinking stream
  showThinkingStream: boolean;
  setShowThinkingStream: React.Dispatch<React.SetStateAction<boolean>>;
  handleToggleThinkingStream: () => void;

  // Live execution panel
  showLiveExecutionPanel: boolean;
  setShowLiveExecutionPanel: React.Dispatch<React.SetStateAction<boolean>>;
  handleToggleLiveExecutionPanel: () => void;

  // Checkpointer
  checkpointerEnabled: boolean;
  setCheckpointerEnabled: React.Dispatch<React.SetStateAction<boolean>>;
  handleToggleCheckpointer: () => void;

  // Agent template search
  agentSearchQuery: string;
  setAgentSearchQuery: React.Dispatch<React.SetStateAction<string>>;
  handleAgentSearchChange: (e: React.ChangeEvent<HTMLInputElement>) => void;

  // Name editing
  isEditingName: boolean;
  setIsEditingName: React.Dispatch<React.SetStateAction<boolean>>;
  handleStartEditingName: (e: React.MouseEvent) => void;

  // Custom output path
  customOutputPath: string | null;
  setCustomOutputPath: React.Dispatch<React.SetStateAction<string | null>>;
}

/**
 * Hook for managing UI toggle states and handlers
 */
export function useUIToggles(): UseUITogglesReturn {
  // Agent template dropdown
  const [showAgentDropdown, setShowAgentDropdown] = useState(false);
  const handleToggleAgentDropdown = useCallback(() => {
    setShowAgentDropdown(prev => !prev);
  }, []);
  const handleCloseAgentDropdown = useCallback(() => {
    setShowAgentDropdown(false);
  }, []);

  // Thinking stream
  const [showThinkingStream, setShowThinkingStream] = useState(false);
  const handleToggleThinkingStream = useCallback(() => {
    setShowThinkingStream(prev => !prev);
  }, []);

  // Live execution panel
  const [showLiveExecutionPanel, setShowLiveExecutionPanel] = useState(() => {
    // Restore panel visibility if we have an active task
    return localStorage.getItem('langconfig-current-task-id') !== null;
  });
  const handleToggleLiveExecutionPanel = useCallback(() => {
    setShowLiveExecutionPanel(prev => !prev);
  }, []);

  // Checkpointer
  const [checkpointerEnabled, setCheckpointerEnabled] = useState(false);
  const handleToggleCheckpointer = useCallback(() => {
    setCheckpointerEnabled(prev => !prev);
  }, []);

  // Agent template search
  const [agentSearchQuery, setAgentSearchQuery] = useState('');
  const handleAgentSearchChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    setAgentSearchQuery(e.target.value);
  }, []);

  // Name editing
  const [isEditingName, setIsEditingName] = useState(false);
  const handleStartEditingName = useCallback((e: React.MouseEvent) => {
    e.stopPropagation();
    setIsEditingName(true);
  }, []);

  // Custom output path
  const [customOutputPath, setCustomOutputPath] = useState<string | null>(null);

  return {
    showAgentDropdown,
    setShowAgentDropdown,
    handleToggleAgentDropdown,
    handleCloseAgentDropdown,
    showThinkingStream,
    setShowThinkingStream,
    handleToggleThinkingStream,
    showLiveExecutionPanel,
    setShowLiveExecutionPanel,
    handleToggleLiveExecutionPanel,
    checkpointerEnabled,
    setCheckpointerEnabled,
    handleToggleCheckpointer,
    agentSearchQuery,
    setAgentSearchQuery,
    handleAgentSearchChange,
    isEditingName,
    setIsEditingName,
    handleStartEditingName,
    customOutputPath,
    setCustomOutputPath,
  };
}
