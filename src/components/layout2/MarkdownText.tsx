/**
 * MarkdownText — render a markdown string with the layout's own colours.
 *
 * Why this exists: a skill's `description` and its `instructions` (the SKILL.md body) are **written in
 * markdown** — `## Instructions（指令）`, `**bold**` gates, `| tables |`, fenced commands. Both were being shown
 * as plain text (`instructions` inside a `<pre>`), so an agent's own documentation read like source code: the
 * headings appeared as `## `, emphasis as asterisks, and tables as pipes. Reading a skill is the one thing this
 * activity is for, so it renders.
 *
 * Deliberate limits:
 *  - **No raw HTML.** `react-markdown` ignores it by default; a SKILL.md is third-party text (vendored MIT
 *    skills included), so nothing in it may execute here.
 *  - **Fenced code stays verbatim** — that is the part an agent copies, and syntax colouring is not the point.
 *  - **`#`-links do nothing.** The shell uses a HashRouter; letting a translated anchor change the hash would
 *    unmount the view. External links open in a new tab instead.
 *  - Styling is inline from `LayoutTokens` rather than a stylesheet, because this has to look right in every
 *    theme and inside panels of very different widths.
 */
import { Component, useMemo, type ReactNode } from 'react';
import ReactMarkdown, { type Components } from 'react-markdown';
import remarkGfm from 'remark-gfm';
import type { LayoutTokens } from './tokens';

export interface MarkdownTextProps {
  text: string;
  tokens: LayoutTokens;
  /** Tighten spacing for a card or a one-paragraph field. */
  compact?: boolean;
}

/** Strip the markdown a one-line card cannot render, so lists show sentences rather than asterisks. */
export function stripMarkdown(text: string): string {
  return text
    .replace(/```[\s\S]*?```/g, ' ')
    .replace(/`([^`]+)`/g, '$1')
    .replace(/!\[[^\]]*\]\([^)]*\)/g, ' ')
    .replace(/\[([^\]]+)\]\([^)]*\)/g, '$1')
    .replace(/^\s{0,3}#{1,6}\s+/gm, '')
    .replace(/(\*\*|__)(.*?)\1/g, '$2')
    .replace(/(\*|_)(.*?)\1/g, '$2')
    .replace(/^\s{0,3}[-*+]\s+/gm, '')
    .replace(/^\s{0,3}>\s?/gm, '')
    .replace(/^\s{0,3}(-{3,}|\*{3,})\s*$/gm, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}

/**
 * MarkdownTextSafe — render markdown, and fall back to the raw text if the renderer throws.
 *
 * A prompt or a skill body is data from the database, not code under our control: one pathological document must
 * not take the whole tab down. Without this, a throw inside `react-markdown` unmounts the view and reads as a blank
 * page with nothing to go on.
 */
export class MarkdownBoundary extends Component<
  { text: string; children: ReactNode; fallbackStyle?: React.CSSProperties },
  { failed: boolean }
> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  componentDidCatch(error: unknown) {
    // Keep the reason discoverable: the tab shows the source, the console says why.
    console.error('MarkdownText failed to render; falling back to source', error);
  }

  render() {
    if (this.state.failed) {
      return (
        <pre
          style={{
            margin: 0, whiteSpace: 'pre-wrap', wordBreak: 'break-word',
            fontFamily: '"SF Mono", "Fira Code", monospace', fontSize: 12, lineHeight: 1.55,
            ...this.props.fallbackStyle,
          }}
        >
          {this.props.text}
        </pre>
      );
    }
    return this.props.children;
  }
}

export default function MarkdownText({ text, tokens, compact = false }: MarkdownTextProps) {
  const components = useMemo<Components>(() => {
    const gap = compact ? 0.45 : 0.75;
    const mono = '"SF Mono", "Fira Code", ui-monospace, monospace';
    const SIZES = [19, 16, 14, 13, 12.5, 12];
    const heading = (level: 1 | 2 | 3 | 4 | 5 | 6) => {
      const style: React.CSSProperties = {
        fontSize: SIZES[level - 1],
        fontWeight: level <= 2 ? 700 : 600,
        color: tokens.textPrimary,
        margin: `${gap * 1.4}em 0 ${gap * 0.6}em`,
        paddingBottom: level <= 2 ? 3 : 0,
        borderBottom: level <= 2 ? `1px solid ${tokens.border}` : undefined,
        lineHeight: 1.35,
      };
      const H = `h${level}` as 'h1';
      return ({ children }: { children?: React.ReactNode }) => <H style={style}>{children}</H>;
    };
    return {
      h1: heading(1),
      h2: heading(2),
      h3: heading(3),
      h4: heading(4),
      h5: heading(5),
      h6: heading(6),
      p: ({ children }) => (
        <p style={{ fontSize: 12.5, lineHeight: 1.65, color: tokens.textPrimary, margin: `0 0 ${gap}em` }}>
          {children}
        </p>
      ),
      ul: ({ children }) => (
        <ul style={{ margin: `0 0 ${gap}em`, paddingLeft: 20, color: tokens.textPrimary }}>{children}</ul>
      ),
      ol: ({ children }) => (
        <ol style={{ margin: `0 0 ${gap}em`, paddingLeft: 20, color: tokens.textPrimary }}>{children}</ol>
      ),
      li: ({ children }) => (
        <li style={{ fontSize: 12.5, lineHeight: 1.6, margin: '2px 0' }}>{children}</li>
      ),
      strong: ({ children }) => <strong style={{ fontWeight: 700 }}>{children}</strong>,
      em: ({ children }) => <em style={{ fontStyle: 'italic' }}>{children}</em>,
      del: ({ children }) => <del style={{ opacity: 0.7 }}>{children}</del>,
      a: ({ href, children }) =>
        href && href.startsWith('#') ? (
          // A hash change would unmount this view (HashRouter) — say where it points instead.
          <span style={{ color: tokens.accent, borderBottom: `1px dotted ${tokens.accent}` }}>{children}</span>
        ) : (
          <a href={href} target="_blank" rel="noreferrer" style={{ color: tokens.accent }}>
            {children}
          </a>
        ),
      code: ({ children, className }) => {
        const isBlock = typeof className === 'string' && className.startsWith('language-');
        if (isBlock) {
          return <code className={className}>{children}</code>;
        }
        return (
          <code
            style={{
              fontFamily: mono,
              fontSize: 11.5,
              padding: '1px 4px',
              borderRadius: 3,
              background: tokens.bgHover,
              border: `1px solid ${tokens.border}`,
              color: tokens.textPrimary,
              whiteSpace: 'nowrap',
            }}
          >
            {children}
          </code>
        );
      },
      pre: ({ children }) => (
        <pre
          style={{
            margin: `0 0 ${gap}em`,
            padding: 10,
            borderRadius: 4,
            background: tokens.bgInput,
            border: `1px solid ${tokens.border}`,
            overflowX: 'auto',
            fontFamily: mono,
            fontSize: 11.5,
            lineHeight: 1.5,
            color: tokens.textPrimary,
            whiteSpace: 'pre-wrap',
            wordBreak: 'break-word',
          }}
        >
          {children}
        </pre>
      ),
      blockquote: ({ children }) => (
        <blockquote
          style={{
            margin: `0 0 ${gap}em`,
            padding: '2px 0 2px 10px',
            borderLeft: `2px solid ${tokens.accent}`,
            color: tokens.textMuted,
          }}
        >
          {children}
        </blockquote>
      ),
      hr: () => <hr style={{ border: 0, borderTop: `1px solid ${tokens.border}`, margin: `${gap}em 0` }} />,
      table: ({ children }) => (
        <div style={{ overflowX: 'auto', margin: `0 0 ${gap}em` }}>
          <table style={{ borderCollapse: 'collapse', fontSize: 11.5, width: '100%' }}>{children}</table>
        </div>
      ),
      th: ({ children }) => (
        <th
          style={{
            textAlign: 'left',
            padding: '4px 8px',
            borderBottom: `1px solid ${tokens.border}`,
            background: tokens.bgHover,
            color: tokens.textPrimary,
            fontWeight: 600,
            whiteSpace: 'nowrap',
          }}
        >
          {children}
        </th>
      ),
      td: ({ children }) => (
        <td
          style={{
            padding: '4px 8px',
            borderBottom: `1px solid ${tokens.border}`,
            color: tokens.textPrimary,
            verticalAlign: 'top',
          }}
        >
          {children}
        </td>
      ),
      input: ({ checked, type }) =>
        type === 'checkbox' ? (
          <input type="checkbox" checked={!!checked} readOnly style={{ marginRight: 4, verticalAlign: 'middle' }} />
        ) : null,
    };
  }, [tokens, compact]);

  return (
    <div style={{ wordBreak: 'break-word' }}>
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
        {text}
      </ReactMarkdown>
    </div>
  );
}
