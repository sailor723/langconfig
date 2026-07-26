/**
 * Theme tokens for the Obsidian-style layout shell.
 *
 * Maps the existing LangConfig ThemeContext colors into Obsidian-style
 * named tokens so the layout components (ActivityBar, Sidebar, Workspace,
 * etc.) use simple property access instead of dealing with the legacy
 * color system directly.
 *
 * Each exported function returns the same shape as agent-workspace's
 * ThemeTokens so we can reuse that pattern without copying its themes.
 */
import { useTheme } from '../../lib/themes';

export interface LayoutTokens {
  bgBase: string;
  bgContent: string;
  bgHover: string;
  bgSelected: string;
  bgInput: string;
  bgDropdown: string;

  textPrimary: string;
  textMuted: string;
  textDim: string;

  border: string;
  borderStrong: string;

  accent: string;
  accentMuted: string;
}

/**
 * Derive layout tokens from the current LangConfig theme.
 * This avoids duplicating theme palettes — we just alias the existing
 * ThemeColors into the shape the new layout components expect.
 */
export function useLayoutTokens(): LayoutTokens {
  const { theme } = useTheme();
  const c = theme.colors;

  return {
    // Backgrounds — map LangConfig theme fields to Obsidian roles
    bgBase: c.panelDark,
    bgContent: theme.name === 'dark' ? '#0e0e0e' : c.backgroundLight,
    bgHover: theme.name === 'dark' ? '#1e1e1e' : c.categoryBackground,
    bgSelected: theme.name === 'dark' ? '#242424' : c.backgroundDark,
    bgInput: c.inputBackground,
    bgDropdown: c.panelDark,

    // Text
    textPrimary: c.textPrimary,
    textMuted: c.textMuted,
    textDim: theme.name === 'dark' ? '#555' : '#9ca3af',

    // Borders
    border: c.borderDark,
    borderStrong: c.primary,

    // Accent — use the theme primary color as the accent
    accent: c.primary,
    accentMuted: c.primary + '88',
  };
}
