/**
 * ToolNode — full info card for a native tool. 3x larger than before so the
 * full description is readable inline.
 */

import { memo } from 'react';
import { Handle, Position, NodeProps, NodeResizer } from 'reactflow';

interface Data {
  label: string;
  description?: string;
}

/** Compact descriptions for common LangConfig tools (auto-shown in the card). */
const TOOL_DESCRIPTIONS: Record<string, string> = {
  graphindex_search: 'Search the project knowledge base for relevant documents and snippets',
  graphindex_load: 'Load the full content of a document by its ID from the knowledge base',
  read_file: 'Read a file from the local filesystem',
  write_file: 'Write content to a file on the local filesystem',
  ls: 'List directory contents and file metadata',
  glob: 'Find files by name pattern (e.g. *.py)',
  grep: 'Search text in files using regular expressions',
  web_search: 'Search the web using a search engine',
  http_get: 'Fetch content from an HTTP URL',
  shell: 'Run a shell command on the local machine',
  python_repl: 'Execute Python code in a sandboxed REPL',
  calculator: 'Evaluate mathematical expressions',
  tavily_search: 'Tavily API web search with rich results',
  duckduckgo_search: 'DuckDuckGo web search (privacy-focused)',
  arxiv_search: 'Search arxiv.org for academic papers',
  wikipedia: 'Query Wikipedia for factual information',
  requests_get: 'Make an HTTP GET request to a URL',
  human_input: 'Ask the user a clarifying question',
};

const ToolNode = memo(({ data, selected }: NodeProps<Data>) => {
  const borderColor = selected ? '#A85A2E' : '#C8B6A6';
  const desc = data.description || TOOL_DESCRIPTIONS[data.label] || '';

  return (
    <div
      className="rounded-lg px-3 py-2 shadow-md relative h-full w-full flex flex-col gap-1"
      style={{
        backgroundColor: '#FAF9F5',
        border: `2px solid ${borderColor}`,
        color: '#1F1E1B',
        fontFamily: 'system-ui, -apple-system, sans-serif',
      }}
    >
      <NodeResizer
        color="#C75F3D"
        isVisible={selected}
        minWidth={200}
        minHeight={80}
        lineStyle={{ borderWidth: 1, opacity: 0.4 }}
        handleStyle={{ width: 8, height: 8, borderRadius: 2 }}
      />
      <Handle type="target" position={Position.Top} style={{ background: '#C75F3D', opacity: 0 }} />
      <Handle type="source" position={Position.Bottom} style={{ background: '#C75F3D', opacity: 0 }} />

      {/* Header: icon + tool name */}
      <div className="flex items-center gap-1.5">
        <span style={{ fontSize: 14 }}>🔧</span>
        <span
          className="font-bold truncate"
          style={{ color: '#A85A2E', fontSize: 12, fontFamily: 'monospace' }}
        >
          {data.label}
        </span>
      </div>

      {/* Description (full, max 3 lines) */}
      {desc && (
        <div
          className="overflow-hidden"
          style={{
            fontSize: 10,
            color: '#5C5A55',
            lineHeight: 1.4,
            display: '-webkit-box',
            WebkitLineClamp: 3,
            WebkitBoxOrient: 'vertical',
          }}
        >
          {desc}
        </div>
      )}
    </div>
  );
});

ToolNode.displayName = 'ToolNode';
export default ToolNode;