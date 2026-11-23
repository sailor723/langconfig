/**
 * StructuredBody — 把 yaml / json **读**给人看，而不是给人改。
 *
 * 为什么需要：JD 的引用文件（`jd_links/*.yaml`）是这条链上的中枢产物 —— 每条引用带着客户原话、
 * `txt_line`、`requirement`、`rationale`。用源码读它，读到的是缩进和引号；用树读它，读到的是
 * 「这一条引了什么、指的是原文第几行」。同一份文件，回答的是两个不同的问题。
 *
 * 与 MarkdownBody 的分工：MarkdownBody 管散文（定稿 / 评审），StructuredBody 管结构化数据
 * （yaml / json）。**两者都不负责写** —— 写永远走源码模式，保存时照样跑逐字回查 + 门禁。
 *
 * 故意不做的事：
 *  - 不引第三方树组件：这里要的是「读到内容」，不是拖拽/编辑/虚拟滚动；
 *  - 解析失败**不隐藏**：红字报错 + 原文兜底。渲染成空白是最坏的结果 —— 它让人以为文件没了；
 *  - 长字符串**不截断**：那些是逐字引文，截断就是在骗人。只折叠结构，不折叠内容；
 *  - 默认展开到第 2 层（键 → 数组项），更深的自动收起，并给一键全开/全收。
 */
import { useEffect, useMemo, useState } from 'react';
import { parse as parseYaml } from 'yaml';
import type { LayoutTokens } from './tokens';

export interface StructuredBodyProps {
  text: string;
  tokens: LayoutTokens;
  /** 决定解析器（报错措辞也不同）。树的渲染两条路完全一样。 */
  format: 'yaml' | 'json';
  maxWidth?: number;
  padding?: string;
}

type Kind = 'object' | 'array' | 'string' | 'number' | 'boolean' | 'null';

function kindOf(v: unknown): Kind {
  if (v === null || v === undefined) return 'null';
  if (Array.isArray(v)) return 'array';
  if (typeof v === 'object') return 'object';
  if (typeof v === 'number') return 'number';
  if (typeof v === 'boolean') return 'boolean';
  return 'string';
}

function childCount(v: unknown, k: Kind): number {
  if (k === 'array') return (v as unknown[]).length;
  if (k === 'object') return Object.keys(v as object).length;
  return 0;
}

/** 数组项的来历：对象取前两个标量字段当身份（`id=C-01 · layer=客户原话`）。 */
function summarize(value: unknown, max = 2): string {
  if (kindOf(value) !== 'object') return '';
  const parts: string[] = [];
  for (const [k, v] of Object.entries(value as Record<string, unknown>)) {
    const kk = kindOf(v);
    if (kk === 'object' || kk === 'array') continue;
    const text = String(v ?? '');
    if (!text) continue;
    parts.push(`${k}=${text.length > 18 ? text.slice(0, 18) + '…' : text}`);
    if (parts.length >= max) break;
  }
  return parts.join(' · ');
}

export default function StructuredBody({
  text,
  tokens: t,
  format,
  maxWidth = 800,
  padding = '14px 20px 40px',
}: StructuredBodyProps) {
  const mono = 'ui-monospace, SFMono-Regular, "SF Mono", monospace';

  const parsed = useMemo(() => {
    if (!text.trim()) return { ok: true as const, value: null };
    try {
      const value = format === 'json' ? JSON.parse(text) : parseYaml(text);
      return { ok: true as const, value };
    } catch (e) {
      return { ok: false as const, message: String((e as Error)?.message || e) };
    }
  }, [text, format]);

  // 默认折叠:第 2 层及更深的容器。够深就停 —— 反正收起来了,再往下走也没有意义。
  // 大文件(>100k 字符)再压一层:只到第 1 层。hr_facts.json 是 14.8 万字符 / 277 个候选,
  // 展开后是 1400 行、近 1MB 的 DOM —— 折叠是诚实的降级,卡死不是。
  // 阈值用字符而不是字节:判的是"要画多少行",不是"占多少磁盘"。
  const big = text.length > 100_000;
  const defaultCollapsed = useMemo(() => {
    const out = new Set<string>();
    if (!parsed.ok) return out;
    const floor = big ? 1 : 2;
    const walk = (v: unknown, depth: number, path: string) => {
      const k = kindOf(v);
      if (k !== 'object' && k !== 'array') return;
      if (depth >= floor) {
        out.add(path);
        return;
      }
      if (k === 'array') {
        (v as unknown[]).forEach((item, i) => walk(item, depth + 1, `${path}[${i}]`));
      } else {
        Object.entries(v as Record<string, unknown>).forEach(([key, val]) => walk(val, depth + 1, `${path}.${key}`));
      }
    };
    walk(parsed.value, 0, '$');
    return out;
  }, [parsed, big]);

  const [collapsed, setCollapsed] = useState<Set<string>>(defaultCollapsed);
  useEffect(() => { setCollapsed(defaultCollapsed); }, [defaultCollapsed]);

  const toggle = (path: string) => {
    setCollapsed((prev) => {
      const next = new Set(prev);
      if (next.has(path)) next.delete(path); else next.add(path);
      return next;
    });
  };

  const allPaths = useMemo(() => {
    const out: string[] = [];
    if (!parsed.ok) return out;
    const walk = (v: unknown, path: string) => {
      const k = kindOf(v);
      if (k !== 'object' && k !== 'array') return;
      out.push(path);
      if (k === 'array') (v as unknown[]).forEach((item, i) => walk(item, `${path}[${i}]`));
      else Object.entries(v as Record<string, unknown>).forEach(([key, val]) => walk(val, `${path}.${key}`));
    };
    walk(parsed.value, '$');
    return out;
  }, [parsed]);

  const header = (
    <div style={{
      display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8, paddingBottom: 6,
      borderBottom: `1px solid ${t.border}`, fontSize: 11, color: t.textMuted,
    }}>
      <span style={{ textTransform: 'uppercase', letterSpacing: 0.5 }}>{format}</span>
      {parsed.ok ? (
        <span>
          {kindOf(parsed.value) === 'null'
            ? '空文件'
            : `${kindOf(parsed.value) === 'array' ? '数组' : '物件'} · ${childCount(parsed.value, kindOf(parsed.value))} ${kindOf(parsed.value) === 'array' ? '项' : '键'}`}
        </span>
      ) : (
        <span style={{ color: '#e5484d', fontWeight: 600 }}>解析失败</span>
      )}
      {big && <span>· 文件较大，默认折叠</span>}
      <button
        onClick={() => setCollapsed(new Set())}
        style={{ marginLeft: 'auto', fontSize: 11, padding: '2px 8px', borderRadius: 4, cursor: 'pointer',
                 border: `1px solid ${t.border}`, background: 'transparent', color: t.textMuted }}
      >全部展开</button>
      <button
        onClick={() => setCollapsed(new Set(allPaths.filter((p) => p !== '$')))}
        style={{ fontSize: 11, padding: '2px 8px', borderRadius: 4, cursor: 'pointer',
                 border: `1px solid ${t.border}`, background: 'transparent', color: t.textMuted }}
      >全部收起</button>
    </div>
  );

  const body = !parsed.ok ? (
    <div>
      <div style={{ fontSize: 11.5, color: '#e5484d', fontFamily: mono, whiteSpace: 'pre-wrap',
                    marginBottom: 10, lineHeight: 1.6 }}>
        {parsed.message}
      </div>
      {/* 原文兜底:文件坏了,更要让人看见坏在哪一行,而不是看见一片空白。 */}
      <pre style={{ margin: 0, fontSize: 11.5, fontFamily: mono, color: t.textPrimary,
                    whiteSpace: 'pre-wrap', wordBreak: 'break-word', opacity: 0.85 }}>
        {text}
      </pre>
    </div>
  ) : (
    <Node
      label={undefined}
      value={parsed.value}
      path="$"
      depth={0}
      tokens={t}
      collapsed={collapsed}
      toggle={toggle}
      mono={mono}
    />
  );

  return (
    <div style={{ flex: 1, minHeight: 0, overflow: 'auto', padding, fontSize: 12.5,
                  lineHeight: 1.55, color: t.textPrimary }}>
      <div style={{ maxWidth }}>
        {header}
        {body}
      </div>
    </div>
  );
}

interface NodeProps {
  label: string | number | undefined;
  value: unknown;
  path: string;
  depth: number;
  tokens: LayoutTokens;
  collapsed: Set<string>;
  toggle: (path: string) => void;
  mono: string;
}

function Node({ label, value, path, depth, tokens: t, collapsed, toggle, mono }: NodeProps) {
  const k = kindOf(value);
  const isContainer = k === 'object' || k === 'array';
  const n = childCount(value, k);
  const isCollapsed = collapsed.has(path);

  const labelEl = label !== undefined && (
    <span style={{ fontFamily: mono, fontSize: 11.5, color: t.textPrimary, flexShrink: 0 }}>
      {label}
      <span style={{ color: t.textMuted }}>: </span>
    </span>
  );

  if (!isContainer) {
    return (
      <div style={{ display: 'flex', gap: 6, padding: '1.5px 0', alignItems: 'baseline' }}>
        <span style={{ width: 12, flexShrink: 0 }} />
        {labelEl}
        <Scalar value={value} kind={k} tokens={t} mono={mono} />
      </div>
    );
  }

  const entries: Array<[string | number, unknown]> = k === 'array'
    ? (value as unknown[]).map((v, i) => [i + 1, v] as [number, unknown])
    : Object.entries(value as Record<string, unknown>);

  const badge = `${n} ${k === 'array' ? '项' : '键'}`;

  return (
    <div>
      <div style={{ display: 'flex', gap: 6, padding: '1.5px 0', alignItems: 'baseline' }}>
        <button
          onClick={() => toggle(path)}
          title={isCollapsed ? '展开' : '收起'}
          style={{ width: 12, flexShrink: 0, padding: 0, border: 'none', background: 'transparent',
                   color: t.textMuted, cursor: 'pointer', fontSize: 10, lineHeight: 1 }}
        >
          {isCollapsed ? '▸' : '▾'}
        </button>
        {labelEl}
        <span style={{ fontSize: 10.5, color: t.textMuted, flexShrink: 0 }}>{badge}</span>
        {/* 数组项的身份:收起时也要看得出这一条是什么（`id=C-01 · layer=客户原话`）。
            没有它,15 条引用收起来就是 15 行"9 键",读者只能一条条点开找 ——
            而这正是这个视图存在的理由。 */}
        {k === 'object' && (
          <span style={{ fontSize: 11, color: t.textMuted, fontFamily: mono, opacity: 0.8,
                         overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {summarize(value)}
          </span>
        )}
        {isCollapsed && k === 'array' && n > 0 && (
          <span style={{ fontSize: 11, color: t.textMuted, fontFamily: mono, opacity: 0.8,
                         overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {summarize((value as unknown[])[0])}
          </span>
        )}
      </div>
      {!isCollapsed && (
        <div style={{ marginLeft: 5, paddingLeft: 10, borderLeft: `1px solid ${t.border}` }}>
          {entries.map(([key, val]) => {
            const childPath = k === 'array' ? `${path}[${(key as number) - 1}]` : `${path}.${key}`;
            return (
              <Node
                key={String(key)}
                label={key}
                value={val}
                path={childPath}
                depth={depth + 1}
                tokens={t}
                collapsed={collapsed}
                toggle={toggle}
                mono={mono}
              />
            );
          })}
        </div>
      )}
    </div>
  );
}

function Scalar({ value, kind, tokens: t, mono }: {
  value: unknown; kind: Kind; tokens: LayoutTokens; mono: string;
}) {
  if (kind === 'null') {
    return <span style={{ color: t.textMuted, fontStyle: 'italic', fontSize: 11.5 }}>— (null)</span>;
  }
  if (kind === 'boolean') {
    return <span style={{ color: '#f08c00', fontFamily: mono, fontSize: 11.5 }}>{String(value)}</span>;
  }
  if (kind === 'number') {
    return <span style={{ color: t.accent, fontFamily: mono, fontSize: 11.5 }}>{String(value)}</span>;
  }
  const s = String(value ?? '');
  if (!s) {
    return <span style={{ color: t.textMuted, fontStyle: 'italic', fontSize: 11.5 }}>（空字符串）</span>;
  }
  // 长文本(引文/理由)换行显示,不截断 —— 它是逐字证据。
  return (
    <span style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word', minWidth: 0 }}>{s}</span>
  );
}
