/**
 * Copyright (c) 2025 Cade Russell (Ghost Peony)
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */

import { useState, ReactNode } from 'react';
import { useNavigate } from 'react-router-dom';
import SettingsSidebar from './SettingsSidebar';

export type SettingsCategory =
  | 'local-workspace'
  | 'model-defaults'
  | 'model-cards'
  | 'search-providers'
  | 'embedding'
  | 'storage'
  | 'backend'
  | 'workflow'
  | 'general'
  | 'appearance'
  | 'about';
// 'api-keys' and 'local-models' removed 2026-06-23 — consolidated into Model Cards
// 'embedding' restored 2026-06-23 — its own tab
// 'search-providers' added 2026-06-24 — Tavily, Wikipedia, DDG, Exa, Brave, SerpAPI

interface SettingsLayoutProps {
  children: ReactNode;
  currentCategory: SettingsCategory;
  onCategoryChange: (category: SettingsCategory) => void;
}

export default function SettingsLayout({
  children,
  currentCategory,
  onCategoryChange
}: SettingsLayoutProps) {
  const navigate = useNavigate();

  return (
    <div className="flex h-full w-full overflow-hidden bg-background-light dark:bg-background-dark">
      {/* Centered Container for Sidebar + Content */}
      <div className="flex max-w-[1600px] w-full mx-auto h-full overflow-hidden">
        {/* Left Sidebar - 240px fixed */}
        <SettingsSidebar
          currentCategory={currentCategory}
          onCategoryChange={onCategoryChange}
        />

        {/* Main Content Area */}
        <div className="flex-1 flex flex-col overflow-hidden">
          {/* Scrollable Content */}
          <div className="flex-1 overflow-y-auto">
            <div className="px-4 py-4">
              {children}
              {/* Close button at bottom */}
              <div className="flex justify-center pt-4">
                <button
                  onClick={() => navigate('/')}
                  className="flex items-center gap-1.5 px-6 py-2 text-sm font-medium rounded-lg border border-gray-300 dark:border-border-dark hover:bg-gray-100 dark:hover:bg-white/10 transition-colors"
                  style={{ color: 'var(--color-text-primary)' }}
                >
                  <span className="material-symbols-outlined text-base">close</span>
                  Close
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
