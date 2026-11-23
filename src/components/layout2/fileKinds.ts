/**
 * 文件类型判定 —— 决定"这个文件怎么展示"。
 *
 * 为什么单独一个文件:同一套扩展名判定散在各处,最后一定会分叉(一边认 `.markdown`,
 * 另一边只认 `.md`),而分叉的后果是同一个文件在两处一个能预览、一个只能下载。
 * 这里的集合与 `KnowledgeView` 里那张表保持一致(它以私有常量形式存在,未导出)——
 * 要改就改这里,并顺手对齐那边。
 */

export type FileKind = 'markdown' | 'structured' | 'text' | 'pdf' | 'office' | 'image' | 'html' | 'legacy' | 'other';

const MARKDOWN = new Set(['md', 'markdown']);
const STRUCTURED = new Set(['yaml', 'yml', 'json']);
const TEXT = new Set([
  'txt', 'csv', 'tsv', 'log', 'xml', 'ini', 'toml', 'conf', 'env',
  'css', 'sql', 'sh', 'bash', 'zsh', 'py', 'js', 'ts', 'tsx', 'jsx', 'mjs',
  'rb', 'go', 'rs', 'java', 'kt', 'swift', 'c', 'cpp', 'h', 'hpp', 'mdx',
]);
const PDF = new Set(['pdf']);
const OFFICE = new Set(['docx', 'pptx']);
/** 老式二进制 Office(antiword/catdoc 能抽字,但版式不保留)—— 服务端转成纯文本。 */
const LEGACY = new Set(['doc', 'ppt', 'xls']);
const IMAGE = new Set(['png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp', 'svg']);
const HTML = new Set(['html', 'htm']);

export function extOf(name: string): string {
  const m = /\.([A-Za-z0-9]+)$/.exec(name);
  return m ? m[1].toLowerCase() : '';
}

export function fileKind(name: string): FileKind {
  const e = extOf(name);
  if (MARKDOWN.has(e)) return 'markdown';
  if (STRUCTURED.has(e)) return 'structured';
  if (PDF.has(e)) return 'pdf';
  if (OFFICE.has(e)) return 'office';
  if (LEGACY.has(e)) return 'legacy';
  if (IMAGE.has(e)) return 'image';
  if (HTML.has(e)) return 'html';
  if (TEXT.has(e)) return 'text';
  return 'other';
}
