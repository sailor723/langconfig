/**
 * Copyright (c) 2025 Cade Russell (Ghost Peony)
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */

import { useTranslation } from 'react-i18next';
import { SettingsCategory } from './SettingsLayout';

interface SettingsSidebarProps {
  currentCategory: SettingsCategory;
  onCategoryChange: (category: SettingsCategory) => void;
}

interface MenuSection {
  id: SettingsCategory;
  labelKey: string;
  icon: string;
}

const menuSections: MenuSection[] = [
  { id: 'general', labelKey: 'settings_general', icon: 'tune' },
  // 'api-keys' removed 2026-06-23 — API keys now edited inline in Model Cards tab
  { id: 'model-cards', labelKey: 'settings_model_cards', icon: 'smart_toy' },
  { id: 'embedding', labelKey: 'settings_embedding', icon: 'database' },
  { id: 'model-defaults', labelKey: 'settings_model_defaults', icon: 'psychology' },
  // 'local-models' removed 2026-06-23 — local models now shown under their provider in Model Cards
  { id: 'local-workspace', labelKey: 'settings_local_workspace', icon: 'folder_open' },
  { id: 'appearance', labelKey: 'settings_appearance', icon: 'palette' },
  { id: 'about', labelKey: 'settings_about', icon: 'info' },
];

export default function SettingsSidebar({
  currentCategory,
  onCategoryChange
}: SettingsSidebarProps) {
  const { t } = useTranslation('chat');
  return (
    <aside className="w-52 border-r border-gray-200 dark:border-border-dark bg-white dark:bg-panel-dark flex flex-col">
      {/* Header */}
      <div className="px-4 py-6 border-b border-gray-200 dark:border-border-dark">
        <h2 className="text-lg font-semibold flex items-center gap-2" style={{ color: 'var(--color-text-primary)' }}>
          <span className="material-symbols-outlined text-xl">settings</span>
          {t('settings_title')}
        </h2>
      </div>

      {/* Navigation Menu */}
      <nav className="flex-1 overflow-y-auto py-2">
        {menuSections.map((section) => {
          const isActive = currentCategory === section.id;

          return (
            <button
              key={section.id}
              onClick={() => onCategoryChange(section.id)}
              className={`w-full flex items-center gap-3 px-4 py-3 text-sm font-medium transition-colors ${
                isActive
                  ? 'bg-primary/10 dark:bg-primary/20'
                  : 'hover:bg-gray-50 dark:hover:bg-white/5'
              }`}
              style={{
                color: isActive ? 'var(--color-primary)' : 'var(--color-text-muted)',
                borderLeft: isActive ? '3px solid var(--color-primary)' : '3px solid transparent'
              }}
            >
              <span className="material-symbols-outlined text-base">
                {section.icon}
              </span>
              <span>{t(section.labelKey)}</span>
            </button>
          );
        })}
      </nav>
    </aside>
  );
}
