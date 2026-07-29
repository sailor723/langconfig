/**
 * Copyright (c) 2025 Cade Russell (Ghost Peony)
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 *
 * Three themes:
 *   langconfig — Signature theme (light blue/cream)
 *   claude     — Warm neutral theme (inspired by Claude.ai)
 *   dark       — Dark gray theme (inspired by OpenAI Codex)
 *
 * Architecture:
 *   - themes.ts: lightweight data-only (no React dependency)
 *   - ThemeProvider.tsx: React context + hook for components to read the
 *     current theme's color hex values at runtime.
 */

import React, { createContext, useContext, useState, useEffect, useCallback } from 'react';

export type ThemeName = 'langconfig' | 'claude' | 'dark' | 'warm' | 'white';

export interface ThemeColors {
  primary: string;
  backgroundLight: string;
  backgroundDark: string;
  panelDark: string;
  borderDark: string;
  textMuted: string;
  textPrimary: string;
  inputBackground: string;
  logoBackground: string;
  nodeBackground: string;
  nodeBackgroundLight: string;
  categoryBackground: string;
  headerBackground: string;
  headerTextColor: string;
}

export interface Theme {
  name: ThemeName;
  displayName: string;
  colors: ThemeColors;
  textured?: boolean;
}

export const themes: Record<ThemeName, Theme> = {
  langconfig: {
    name: 'langconfig',
    displayName: 'LangConfig (Signature)',
    colors: {
      primary: '#2E5C8A',
      backgroundLight: '#F5F9FC',
      backgroundDark: '#D8EDF5',
      panelDark: '#E3F0F5',
      borderDark: '#2E5C8A',
      textMuted: '#4A6B8A',
      textPrimary: '#1a2332',
      inputBackground: '#FFFFFF',
      logoBackground: '#FFFFFF',
      nodeBackground: '#6B9E7E',
      nodeBackgroundLight: '#8AB5A0',
      categoryBackground: '#C5E0E5',
      headerBackground: '#5B9BD5',
      headerTextColor: '#FFFFFF',
    },
    textured: true,
  },

  claude: {
    name: 'claude',
    displayName: 'Claude',
    colors: {
      primary: '#D97706',
      backgroundLight: '#FAF8F5',
      backgroundDark: '#F0EBE3',
      panelDark: '#F5F0E8',
      borderDark: '#E0D6C8',
      textMuted: '#8B7D6B',
      textPrimary: '#2D2416',
      inputBackground: '#FFFFFF',
      logoBackground: '#FFFFFF',
      nodeBackground: '#F0EBE3',
      nodeBackgroundLight: '#E0D6C8',
      categoryBackground: '#E0D6C8',
      headerBackground: '#D97706',
      headerTextColor: '#FFFFFF',
    },
  },

  dark: {
    name: 'dark',
    displayName: 'Dark (VS Code)',
    colors: {
      primary: '#0078d4',
      backgroundLight: '#1e1e1e',
      backgroundDark: '#252526',
      panelDark: '#252526',
      borderDark: '#3c3c3c',
      textMuted: '#858585',
      textPrimary: '#cccccc',
      inputBackground: '#3c3c3c',
      logoBackground: '#252526',
      nodeBackground: '#2d2d2d',
      nodeBackgroundLight: '#37373d',
      categoryBackground: '#2d2d2d',
      headerBackground: '#007acc',
      headerTextColor: '#ffffff',
    },
  },

  warm: {
    name: 'warm',
    displayName: 'Warm Orange',
    colors: {
      primary: '#D97706',
      backgroundLight: '#fff7ed',
      backgroundDark: '#ffedd5',
      panelDark: '#fff7ed',
      borderDark: '#fed7aa',
      textMuted: '#b45309',
      textPrimary: '#431407',
      inputBackground: '#ffffff',
      logoBackground: '#ffffff',
      nodeBackground: '#ffedd5',
      nodeBackgroundLight: '#fed7aa',
      categoryBackground: '#ffedd5',
      headerBackground: '#ea580c',
      headerTextColor: '#ffffff',
    },
  },

  white: {
    name: 'white',
    displayName: 'White Clean',
    colors: {
      primary: '#2563eb',
      backgroundLight: '#ffffff',
      backgroundDark: '#f8fafc',
      panelDark: '#f1f5f9',
      borderDark: '#e2e8f0',
      textMuted: '#64748b',
      textPrimary: '#0f172a',
      inputBackground: '#ffffff',
      logoBackground: '#ffffff',
      nodeBackground: '#f8fafc',
      nodeBackgroundLight: '#f1f5f9',
      categoryBackground: '#f1f5f9',
      headerBackground: '#2563eb',
      headerTextColor: '#ffffff',
    },
  },
};

// ── React Context ────────────────────────────────────────────────

interface ThemeContextValue {
  theme: Theme;
  setTheme: (name: ThemeName) => void;
}

const ThemeContext = createContext<ThemeContextValue | null>(null);

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const [theme, setThemeState] = useState<Theme>(() => {
    const saved = localStorage.getItem('langconfig-theme') as ThemeName;
    return themes[saved] || themes.dark;
  });

  const setTheme = useCallback((name: ThemeName) => {
    const t = themes[name];
    if (!t) return;
    setThemeState(t);
    localStorage.setItem('langconfig-theme', name);
    // Keep DOM attributes in sync for CSS-based overrides
    applyThemeDom(t);
  }, []);

  // Init on mount only
  useEffect(() => {
    applyThemeDom(theme);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <ThemeContext.Provider value={{ theme, setTheme }}>
      {children}
    </ThemeContext.Provider>
  );
}

export function useTheme(): ThemeContextValue {
  const ctx = useContext(ThemeContext);
  if (!ctx) throw new Error('useTheme must be used inside <ThemeProvider>');
  return ctx;
}

// ── DOM helpers (kept for CSS-based overrides & <html> attribute) ─

export function applyThemeDom(theme: Theme) {
  const root = document.documentElement;
  root.classList.remove('theme-langconfig', 'theme-claude', 'theme-dark', 'theme-warm', 'theme-white');
  root.classList.add(`theme-${theme.name}`);
  root.setAttribute('data-theme', theme.name);

  if (theme.name === 'dark') {
    root.classList.add('dark');
  } else {
    root.classList.remove('dark');
  }

  if (theme.textured) {
    root.classList.add('textured-theme');
  } else {
    root.classList.remove('textured-theme');
  }

  // Direct style application — bypasses CSS specificity issues
  // with Tailwind v4 @property rules and cached inline styles.
  root.style.backgroundColor = theme.colors.backgroundLight;
  root.style.color = theme.colors.textPrimary;
  document.body.style.backgroundColor = theme.colors.backgroundLight;
  document.body.style.color = theme.colors.textPrimary;

  // Inject a <style> element into the document head to force all
  // `var(--color-*)` usage to resolve to the current theme colors.
  // This is the most reliable way to bypass Tailwind v4 @property.
  let styleTag = document.getElementById('__theme-force') as HTMLStyleElement | null;
  if (!styleTag) {
    styleTag = document.createElement('style');
    styleTag.id = '__theme-force';
    document.head.appendChild(styleTag);
  }

  const c = theme.colors;
  styleTag.textContent = `
    [data-theme="${theme.name}"] [style*="color-panel-dark"],
    [data-theme="${theme.name}"] [style*="color-background-dark"],
    [data-theme="${theme.name}"] [style*="color-background-light"],
    [data-theme="${theme.name}"] [style*="color-input-background"] {
      background-color: ${c.panelDark} !important;
    }
    [data-theme="${theme.name}"] [style*="color-text-muted"] {
      color: ${c.textMuted} !important;
    }
    [data-theme="${theme.name}"] [style*="color-text-primary"] {
      color: ${c.textPrimary} !important;
    }
    [data-theme="${theme.name}"] [style*="color-primary"] {
      background-color: ${c.primary} !important;
      color: ${c.headerTextColor} !important;
    }
    [data-theme="${theme.name}"] .bg-white,
    [data-theme="${theme.name}"] .bg-gray-50 {
      background-color: ${c.panelDark} !important;
    }
    [data-theme="${theme.name}"] body {
      background-color: ${c.backgroundLight} !important;
    }
    [data-theme="${theme.name}"] header {
      background-color: ${c.headerBackground} !important;
      border-color: ${c.borderDark} !important;
    }
    [data-theme="${theme.name}"] header button {
      color: ${c.headerTextColor} !important;
    }
    [data-theme="${theme.name}"] input,
    [data-theme="${theme.name}"] textarea,
    [data-theme="${theme.name}"] select {
      background-color: ${c.inputBackground} !important;
      border-color: ${c.borderDark} !important;
      color: ${c.textPrimary} !important;
    }
    [data-theme="${theme.name}"] [class*="rounded-xl"],
    [data-theme="${theme.name}"] [class*="rounded-lg"] {
      border-color: ${c.borderDark} !important;
    }
  `;
}
