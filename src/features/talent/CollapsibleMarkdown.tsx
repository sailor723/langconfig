/**
 * CollapsibleMarkdown —— 把 md 里的 `::: details 标题` 容器渲染成可展开块。
 *
 * 为什么不用 `<details>` 原生 HTML:MarkdownBody 故意不开 `rehype-raw`
 * (文档正文是第三方/派生文本,不许执行)。所以 md 里写 HTML 不会生效 ——
 * 换成容器语法,由这里解析成安全的 React 结构,正文仍然交给 MarkdownBody 渲染。
 *
 * 语法(只有开头与结尾两行是结构,中间全是普通 md):
 *
 *     ::: details 1. 张三(硬证据 2 · 待核 9 项)
 *     ### 张三
 *     ...
 *     :::
 *
 * 未闭合的容器按"普通文本"处理,不让一个语法错误吞掉后面的整份文档。
 *
 * 站内链接:`[看 CV](#tal:cv/<candidate id>)` 这类 md 写不了 onclick,
 * 所以由这里接管 `<a>` —— 命中 `#tal:` 就交给调用方(弹层),没命中照常跳转。
 */
import { Fragment, useMemo, useState } from 'react';
import { ChevronRight } from 'lucide-react';
import MarkdownBody from '../../components/layout2/MarkdownBody';
import type { LayoutTokens } from '../../components/layout2/tokens';

type Chunk = { kind: 'md'; text: string } | { kind: 'details'; title: string; text: string };

const OPEN = /^:::\s*details(?:\s+(.*))?$/;
const CLOSE = /^:::\s*$/;

export function splitContainers(md: string): Chunk[] {
  const out: Chunk[] = [];
  let buf: string[] = [];
  let cur: { title: string; lines: string[] } | null = null;

  const flushMd = () => {
    const t = buf.join('\n').trim();
    if (t) out.push({ kind: 'md', text: t });
    buf = [];
  };

  for (const line of md.split('\n')) {
    const m = line.match(OPEN);
    if (m && !cur) {
      flushMd();
      cur = { title: (m[1] || '详情').trim(), lines: [] };
      continue;
    }
    if (cur && CLOSE.test(line)) {
      out.push({ kind: 'details', title: cur.title, text: cur.lines.join('\n').trim() });
      cur = null;
      continue;
    }
    if (cur) cur.lines.push(line);
    else buf.push(line);
  }
  // 未闭合:把容器内容退回普通文本,不吞内容
  if (cur) {
    buf.push(...cur.lines);
  }
  flushMd();
  return out;
}

export default function CollapsibleMarkdown({
  text, tokens, onOpenLink,
}: {
  text: string;
  tokens: LayoutTokens;
  /** 命中 `#tal:...` 站内链接时调用。返回 true 表示已处理(比如打开弹层)。 */
  onOpenLink?: (href: string) => void;
}) {
  const chunks = splitContainers(text);
  const components = useMdLinkComponents(tokens, onOpenLink);
  return (
    <>
      {chunks.map((c, i) =>
        c.kind === 'md' ? (
          <MarkdownBody key={i} text={c.text} tokens={tokens} components={components} />
        ) : (
          <Section key={i} title={c.title} text={c.text} tokens={tokens} onOpenLink={onOpenLink} />
        ),
      )}
    </>
  );
}

/** 把 `<a href="#tal:...">` 变成弹层入口;其余链接原样。 */
function useMdLinkComponents(
  tokens: LayoutTokens,
  onOpenLink?: (href: string) => void,
) {
  return useMemo(() => ({
    a: ({ href = '', children, ...rest }: any) => {
      const internal = typeof href === 'string' && href.startsWith('#tal:');
      if (!internal || !onOpenLink) {
        return <a href={href} {...rest}>{children}</a>;
      }
      return (
        <a
          href={href}
          {...rest}
          onClick={(e) => { e.preventDefault(); onOpenLink(href); }}
          style={{
            color: tokens.accent, textDecoration: 'underline', cursor: 'pointer',
            fontWeight: 600, whiteSpace: 'nowrap',
          }}
          title="在弹层里打开全文"
        >
          {children}
        </a>
      );
    },
  }), [tokens.accent, onOpenLink]);
}

function Section({ title, text, tokens, onOpenLink }: {
  title: string; text: string; tokens: LayoutTokens; onOpenLink?: (href: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const components = useMdLinkComponents(tokens, onOpenLink);
  return (
    <div style={{
      margin: '6px 0', border: `1px solid ${tokens.border}`, borderRadius: 6,
      background: open ? tokens.bgInput : 'transparent',
    }}>
      <button
        onClick={() => setOpen((v) => !v)}
        style={{
          display: 'flex', alignItems: 'center', gap: 6, width: '100%', textAlign: 'left',
          cursor: 'pointer', padding: '7px 10px', background: 'transparent', border: 'none',
          color: tokens.textPrimary, fontSize: 12.5,
        }}
        aria-expanded={open}
      >
        <ChevronRight
          size={13}
          style={{ transform: open ? 'rotate(90deg)' : 'none', transition: 'transform .12s',
                   color: tokens.textMuted, flexShrink: 0 }}
        />
        <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {title}
        </span>
      </button>
      {open && (
        <div style={{ padding: '0 12px 10px 12px', borderTop: `1px solid ${tokens.border}` }}>
          <MarkdownBody text={text} tokens={tokens} components={components} />
        </div>
      )}
    </div>
  );
}
