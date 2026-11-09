/**
 * Copyright (c) 2025 Cade Russell (Ghost Peony)
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */

/**
 * DownloadContext - Provides workflow context for artifact downloads
 */

import React, { createContext, useContext, useMemo } from 'react';

interface DownloadContextValue {
  /** Workflow name for file naming */
  workflowName: string;
  /** Counter for unique file numbering */
  getNextNumber: () => number;
}

const DownloadContext = createContext<DownloadContextValue | null>(null);

interface DownloadProviderProps {
  workflowName: string;
  children: React.ReactNode;
}

/**
 * Provider that makes workflow name available for download file naming
 */
export function DownloadProvider({ workflowName, children }: DownloadProviderProps) {
  // Use a ref-like counter that persists across renders
  const counterRef = React.useRef(0);

  const value = useMemo(() => ({
    workflowName: workflowName || 'Workflow',
    getNextNumber: () => {
      counterRef.current += 1;
      return counterRef.current;
    },
  }), [workflowName]);

  return (
    <DownloadContext.Provider value={value}>
      {children}
    </DownloadContext.Provider>
  );
}

/**
 * Hook to access download context
 */
/** Shared by every block that renders outside a provider, so numbering does not restart per call. */
let fallbackCounter = 0;

export function useDownloadContext(): DownloadContextValue {
  const context = useContext(DownloadContext);

  // No provider above this block: name the file after what it is, and keep counting across blocks.
  // The previous version declared `let counter = 0` INSIDE the hook, so getNextNumber always returned
  // 1 and every download on the page was called `Generated_1.<ext>` (and "Generated" said nothing
  // about the artifact). DownloadProvider is mounted in WorkflowCanvas with the real workflow name;
  // this path only serves blocks rendered outside a workflow (chat attachments).
  if (!context) {
    return {
      workflowName: 'attachment',
      getNextNumber: () => {
        fallbackCounter += 1;
        return fallbackCounter;
      },
    };
  }

  return context;
}

/**
 * Generate a safe filename from workflow name
 */
export function sanitizeFilename(name: string): string {
  return name
    .replace(/[^a-zA-Z0-9\s-_]/g, '') // Remove special chars
    .replace(/\s+/g, '_') // Replace spaces with underscores
    .substring(0, 50); // Limit length
}
