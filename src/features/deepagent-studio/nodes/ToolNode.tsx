/**
 * ToolNode — small pill showing a native tool. Includes a short description
 * inside the box so users can see what the tool does without clicking.
 */

import { memo } from 'react';
import { Handle, Position, NodeProps, NodeResizer } from 'reactflow';

interface Data {
  label: string;
  description?: string;
}

/** Compact descriptions for common LangConfig tools (auto-shown in the pill). */
const TOOL_DESCRIPTIONS: Record<string, string> = {
  graphindex_search: 'Search project knowledge base',
  graphindex_load: 'Load full document by ID',
  read_file: 'Read a file from disk',
  write_file: 'Write a file to disk',
  ls: 'List directory contents',
  glob: 'Find files by pattern',
  grep: 'Search text in files',
  web_search: 'Search the web',
  http_get: 'Fetch a URL',
  shell: 'Run a shell command',
  python_repl: 'Execute Python code',
  calculator: 'Evaluate math expressions',
  tavily_search: 'Tavily web search',
  duckduckgo_search: 'DuckDuckGo search',
  arxiv_search: 'Search arxiv papers',
  wikipedia: 'Query Wikipedia',
  requests_get: 'HTTP GET request',
  human_input: 'Ask the user a question',
};

const ToolNode = memo(({ data, selected }: NodeProps<Data>) => {
  const borderColor = selected ? '#A85A2E' : '#C8B6A6';
  const desc = data.description || TOOL_DESCRIPTIONS[data.label] || '';

  return (
    <div
      className="rounded-md px-2 py-1 shadow-sm relative"
      style={{
        backgroundColor: '#FAF9F5',
        border: `1.5px solid ${borderColor}`,
        color: '#1F1E1B',
        fontFamily: 'monospace',
        fontSize: 9,
        width: 130,
        minHeight: 32,
      }}
    >
      <NodeResizer
        color="#C75F3D"
        isVisible={selected}
        minWidth={130}
        minHeight={32}
        lineStyle={{ borderWidth: 1, opacity: 0.4 }}
        handleStyle={{ width: 6, height: 6, borderRadius: 2 }}
      />
      <Handle type="target" position={Position.Top} style={{ background: '#C75F3D', opacity: 0 }} />
      <Handle type="source" position={Position.Bottom} style={{ background: '#C75F3D', opacity: 0 }} />
      <div className="flex items-center gap-1 overflow-hidden">
        <span style={{ fontSize: 9 }}>🔧</span>
        <span className="font-bold truncate" style={{ color: '#A85A2E', fontSize: 9 }}>
          {data.label}
        </span>
      </div>
      {desc && (
        <div
          className="truncate"
          style={{ fontSize: 8, color: '#5C5A55', marginTop: 1 }}
        >
          {desc}
        </div>
      )}
    </div>
  );
});

ToolNode.displayName = 'ToolNode';
export default ToolNode;