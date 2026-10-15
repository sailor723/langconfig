/**
 * The colours the knowledge maintenance panels need, named for what they are rather than for where
 * they came from. Settings and the Knowledge sidebar use different token objects, so a panel that
 * took either one could only live in one place — this is the seam that lets the same panel be
 * hosted by either without knowing which.
 */
export interface SettingsPanelTokens {
  /** Input and row background. */
  bg: string;
  /** Panel background, behind the rows. */
  bgPanel: string;
  border: string;
  textPrimary: string;
  textMuted: string;
  hover: string;
  /** Accent for the primary action. */
  primary: string;
}
