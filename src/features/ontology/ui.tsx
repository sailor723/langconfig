/**
 * ui.tsx — the small pieces the Ontology pages share, in LangConfig's house style.
 *
 * The house style is already set by the other activity home pages (Knowledge, Analysis,
 * Agents): a 40px rounded icon tile with an `${accent}22` wash, a 22px/700 title, a 12px
 * muted subtitle, cards with `padding: 18`, `radius: 10`, `background: bgContent` and a
 * 1px border, section headings at 15px/700, body copy at 13–14px with 1.6–1.7 line-height,
 * and primary buttons at `padding: 7px 14px`, `radius: 8`, `13px/600` on the accent.
 *
 * These wrappers exist so the Ontology activity cannot drift from that: every page renders
 * through them instead of hand-rolling font sizes. Status colours are always
 * `${colour}22` background + the colour at full strength, which reads correctly in the light
 * and dark themes alike (a fixed `#e9f7f0` pill turned into a light blob on dark).
 */
import type { CSSProperties, ReactNode } from 'react';
import { useLayoutTokens } from '../../components/layout2/tokens';

export const SUCCESS = '#1a7f5a';
export const DANGER = '#b3261e';
export const WARN = '#8a6d3b';
export const INFO = '#0b6bcb';
export const VIOLET = '#8b5cf6';
export const CYAN = '#0891b2';

/** The page shell used by every activity home page in this app. */
export function PageShell({ children }: { children: ReactNode }) {
  return <div style={{ height: '100%', overflowY: 'auto', padding: '40px 48px 64px' }}>{children}</div>;
}

export function Hero({
  icon: Icon,
  title,
  subtitle,
  children,
  actions,
}: {
  icon: typeof import('lucide-react').Boxes;
  title: string;
  subtitle?: string;
  children?: ReactNode;
  actions?: ReactNode;
}) {
  const t = useLayoutTokens();
  return (
    <div style={{ maxWidth: 880, marginBottom: 30 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 12 }}>
        <div
          style={{
            width: 40, height: 40, borderRadius: 10, display: 'flex', alignItems: 'center',
            justifyContent: 'center', background: `${t.accent}22`, color: t.accent, flex: 'none',
          }}
        >
          <Icon size={20} />
        </div>
        <div style={{ minWidth: 0 }}>
          <h1 style={{ fontSize: 22, fontWeight: 700, margin: 0, color: t.textPrimary }}>{title}</h1>
          {subtitle && <p style={{ fontSize: 12, color: t.textMuted, margin: '2px 0 0' }}>{subtitle}</p>}
        </div>
        {actions && <div style={{ marginLeft: 'auto', display: 'flex', gap: 8 }}>{actions}</div>}
      </div>
      {children}
    </div>
  );
}

export function Section({
  title,
  hint,
  actions,
  children,
}: {
  title: string;
  hint?: string;
  actions?: ReactNode;
  children: ReactNode;
}) {
  const t = useLayoutTokens();
  return (
    <div style={{ marginBottom: 28, maxWidth: 1180 }}>
      <div style={{ marginBottom: 10, display: 'flex', alignItems: 'baseline', gap: 10 }}>
        <h2 style={{ fontSize: 15, fontWeight: 700, color: t.textPrimary, margin: 0, letterSpacing: '-0.2px' }}>
          {title}
        </h2>
        {hint && <span style={{ fontSize: 12, color: t.textMuted }}>{hint}</span>}
        {actions && <div style={{ marginLeft: 'auto', display: 'flex', gap: 8 }}>{actions}</div>}
      </div>
      {children}
    </div>
  );
}

export function Card({ children, style }: { children: ReactNode; style?: CSSProperties }) {
  const t = useLayoutTokens();
  return (
    <div
      style={{
        padding: 18, borderRadius: 10, background: t.bgContent,
        border: `1px solid ${t.border}`, ...style,
      }}
    >
      {children}
    </div>
  );
}

/** A small caps label above a value (counts on the ontology cards). */
export function Stat({ label, value, tone }: { label: string; value: ReactNode; tone?: string }) {
  const t = useLayoutTokens();
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
      <span style={{ fontSize: 17, fontWeight: 700, color: tone || t.textPrimary, lineHeight: 1.2 }}>
        {value}
      </span>
      <span style={{ fontSize: 10.5, textTransform: 'uppercase', letterSpacing: 0.5, color: t.textDim }}>
        {label}
      </span>
    </div>
  );
}

export function Chip({
  children,
  colour,
  title,
  onClick,
  active,
}: {
  children: ReactNode;
  colour?: string;
  title?: string;
  onClick?: () => void;
  active?: boolean;
}) {
  const t = useLayoutTokens();
  const c = colour || (active ? t.accent : t.textMuted);
  return (
    <span
      title={title}
      onClick={onClick}
      style={{
        display: 'inline-flex', alignItems: 'center', gap: 5, padding: '2px 9px', borderRadius: 999,
        background: active || colour ? `${c}1f` : 'transparent',
        border: `1px solid ${active || colour ? `${c}55` : t.border}`,
        color: c, fontSize: 11.5, lineHeight: '18px', whiteSpace: 'nowrap',
        cursor: onClick ? 'pointer' : 'default',
        fontFamily: 'ui-monospace, Menlo, monospace',
      }}
    >
      {children}
    </span>
  );
}

export function Btn({
  children,
  onClick,
  variant = 'ghost',
  disabled,
  title,
}: {
  children: ReactNode;
  onClick?: () => void;
  variant?: 'primary' | 'ghost';
  disabled?: boolean;
  title?: string;
}) {
  const t = useLayoutTokens();
  const primary = variant === 'primary';
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      title={title}
      style={{
        display: 'inline-flex', alignItems: 'center', gap: 7, padding: '7px 14px', borderRadius: 8,
        fontSize: 13, fontWeight: primary ? 600 : 500, fontFamily: 'inherit',
        cursor: disabled ? 'default' : 'pointer', opacity: disabled ? 0.45 : 1,
        border: primary ? 'none' : `1px solid ${t.border}`,
        background: primary ? t.accent : 'transparent',
        color: primary ? '#fff' : t.textPrimary, whiteSpace: 'nowrap',
      }}
    >
      {children}
    </button>
  );
}

/** Monospace for identifiers and SQL — the only place a fixed font size is right. */
export const mono: CSSProperties = {
  fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace',
};

export function StatusDot({ up, reason }: { up: boolean; reason?: string }) {
  const t = useLayoutTokens();
  return (
    <span
      title={reason || (up ? 'answering' : 'not answering')}
      style={{
        width: 7, height: 7, borderRadius: 999, flex: 'none',
        background: up ? SUCCESS : reason ? DANGER : t.textDim,
      }}
    />
  );
}

export function Quiet({ children }: { children: ReactNode }) {
  const t = useLayoutTokens();
  return <div style={{ fontSize: 12, color: t.textMuted, lineHeight: 1.7 }}>{children}</div>;
}
