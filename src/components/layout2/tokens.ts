/**
 * Theme tokens for the VS Code-style layout shell.
 *
 * Maps the existing LangConfig ThemeContext colors into VS Code-style
 * named tokens so layout components use simple property access.
 */
import { useTheme } from '../../lib/themes';

export interface LayoutTokens {
  bgBase: string;
  bgContent: string;
  bgActivityBar: string;
  bgSidebar: string;
  bgTabBar: string;
  bgStatusBar: string;
  bgHover: string;
  bgSelected: string;
  bgInput: string;
  bgDropdown: string;

  textPrimary: string;
  textMuted: string;
  textDim: string;
  textWhite: string;

  border: string;

  accent: string;
  accentMuted: string;
}

/**
 * Derive layout tokens from the current LangConfig theme.
 * Maps to VS Code Dark Modern color palette.
 */
export function useLayoutTokens(): LayoutTokens {
  const { theme } = useTheme();
  const c = theme.colors;
  const isDark = theme.name === 'dark';

  return {
    // Backgrounds — VS Code Dark Modern palette
    bgBase: c.panelDark,                  // sidebar/panel #252526
    bgContent: c.backgroundLight,         // editor #1e1e1e
    bgActivityBar: isDark ? '#181818' : '#2c2c2c',
    bgSidebar: c.panelDark,               // #252526
    bgTabBar: c.panelDark,                // #252526 — same as sidebar
    bgStatusBar: isDark ? '#007acc' : '#007acc', // VS Code blue
    bgHover: isDark ? c.nodeBackground : c.categoryBackground,
    bgSelected: isDark ? c.nodeBackgroundLight : c.backgroundDark,
    bgInput: c.inputBackground,
    bgDropdown: c.panelDark,

    // Text
    textPrimary: c.textPrimary,
    textMuted: c.textMuted,
    textDim: isDark ? '#6e6e6e' : '#9ca3af',
    textWhite: '#ffffff',

    // Borders
    border: c.borderDark,

    // Accent — VS Code blue #0078d4
    accent: c.primary,
    accentMuted: c.primary + '88',
  };
}
