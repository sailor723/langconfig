/**
 * MarkdownBody — 一份文档正文的**唯一** markdown 渲染器。
 *
 * 为什么共享:Knowledge 用它渲染知识文档,Talent 用它渲染 JD 的定稿/评审。读者会在这两个活动之间
 * 来回看同一份内容,「看起来一样」不能靠两份拷贝维持 —— 两份 CSS 一定会分叉,而分叉以后
 * 同一段 markdown 在两处会折行不同、表格不同、标题间距不同,人只会以为其中一处坏了。
 *
 * 沿用 KnowledgeView 里长出来的那套做法,原样保留:
 *  - 样式是一段作用域化的 `.markdown-body` style 块,颜色全部来自 LayoutTokens——所以任何主题都对。
 *  - `maxWidth: 800` 是**行宽**(measure),不是容器宽度:中文正文铺满整屏极难读。
 *  - 需要标题锚点/目录的调用方把 `components` 传进来(Knowledge 传它自己的 TOC 锚点;
 *    Talent 不需要,不传就是普通渲染)。
 *  - 不用 `dangerouslySetInnerHTML`,也不开 `rehype-raw`:文档正文是第三方/派生文本,不许执行。
 */
import ReactMarkdown, { type Components } from 'react-markdown';
import remarkGfm from 'remark-gfm';
import type { Ref } from 'react';
import type { LayoutTokens } from './tokens';

export interface MarkdownBodyProps {
  text: string;
  tokens: LayoutTokens;
  /** 覆盖标题渲染(Knowledge 用它注入目录锚点 id)。 */
  components?: Components;
  /** 需要跟踪滚动位置时传自己的 ref / onScroll(目录高亮就是这么做的)。 */
  scrollRef?: Ref<HTMLDivElement>;
  onScroll?: () => void;
  maxWidth?: number;
  padding?: string;
}

export default function MarkdownBody({
  text,
  tokens: t,
  components,
  scrollRef,
  onScroll,
  maxWidth = 800,
  padding = '16px 24px',
}: MarkdownBodyProps) {
  return (
    <div
      ref={scrollRef}
      onScroll={onScroll}
      style={{
        flex: 1,
        minHeight: 0,
        overflow: 'auto',
        padding,
        fontSize: 14,
        lineHeight: 1.6,
        color: t.textPrimary,
      }}
    >
      <div className="markdown-body" style={{ maxWidth }}>
        <style>{`
          .markdown-body h1 { font-size: 1.6em; font-weight: 700; margin: 0.8em 0 0.4em; padding-bottom: 0.3em; border-bottom: 1px solid ${t.border}; }
          .markdown-body h2 { font-size: 1.35em; font-weight: 600; margin: 0.7em 0 0.3em; }
          .markdown-body h3 { font-size: 1.15em; font-weight: 600; margin: 0.6em 0 0.25em; }
          .markdown-body p { margin: 0.5em 0; }
          .markdown-body ul, .markdown-body ol { padding-left: 1.5em; margin: 0.4em 0; }
          .markdown-body li { margin: 0.2em 0; }
          .markdown-body a { color: #a855f7; text-decoration: underline; }
          .markdown-body pre { background: ${t.bgBase}; padding: 12px; border-radius: 6px; overflow-x: auto; margin: 0.6em 0; font-size: 0.875em; }
          .markdown-body code { background: ${t.bgHover}; padding: 1px 4px; border-radius: 3px; font-size: 0.875em; }
          .markdown-body pre code { background: transparent; padding: 0; }
          .markdown-body blockquote { border-left: 3px solid #a855f7; padding-left: 12px; color: ${t.textMuted}; margin: 0.5em 0; }
          .markdown-body table { border-collapse: collapse; width: 100%; margin: 0.6em 0; }
          .markdown-body th, .markdown-body td { border: 1px solid ${t.border}; padding: 6px 10px; text-align: left; }
          .markdown-body th { background: ${t.bgBase}; font-weight: 600; }
          .markdown-body hr { border: none; border-top: 1px solid ${t.border}; margin: 1em 0; }
          .markdown-body img { max-width: 100%; }
          .markdown-body h1, .markdown-body h2, .markdown-body h3,
          .markdown-body h4, .markdown-body h5, .markdown-body h6 {
            scroll-margin-top: 12px;
          }
        `}</style>
        <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
          {text}
        </ReactMarkdown>
      </div>
    </div>
  );
}
