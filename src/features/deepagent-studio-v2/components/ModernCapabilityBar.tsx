/**
 * ModernCapabilityBar — horizontal pill bar showing tool capabilities.
 */

import type { AgentStructure } from '../types';

interface Props {
  structure: AgentStructure | null;
}

const nativeIcons: Record<string, string> = {
  web_search: '🌐',
  tavily_search: '🔍',
  web_fetch: '🕸️',
  ls: '📁',
  read_file: '📖',
  write_file: '✏️',
  edit_file: '🖊️',
  glob: '🔎',
  grep: '🔍',
  reasoning_chain: '🧮',
  task: '📡',
  memory_store: '💾',
  memory_recall: '🧠',
  graphindex_search: '📚',
  graphindex_load: '📜',
  graphindex_list_docs: '📋',
  graphindex_multi_doc_load: '📚',
};

export default function ModernCapabilityBar({ structure }: Props) {
  if (!structure) return null;
  const tools = [...(structure.native_tools || []), ...(structure.tools || [])];
  if (tools.length === 0) {
    return (
      <div
        className="px-4 py-2 text-xs"
        style={{ color: '#99D3FF' }}
      >
        No tools configured
      </div>
    );
  }

  return (
    <div
      className="flex items-center gap-2 px-4 py-3 overflow-x-auto"
      style={{
        background: '#030710',
        borderTop: '1px solid rgba(0, 109, 221, 0.4)',
      }}
    >
      <span
        className="text-[12px] uppercase tracking-wider font-bold flex-shrink-0"
        style={{ color: '#7FC8FF' }}
      >
        Capabilities
      </span>
      {tools.map((t, i) => (
        <span
          key={i}
          className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-[12px] font-medium flex-shrink-0"
          style={{
            background: 'linear-gradient(135deg, rgba(0, 109, 221, 0.25), rgba(127, 200, 255, 0.1))',
            border: '1px solid rgba(0, 109, 221, 0.5)',
            color: '#F2FAFF',
            boxShadow: '0 1px 4px rgba(0, 0, 0, 0.3)',
          }}
        >
          <span style={{ color: '#7FC8FF' }}>{nativeIcons[t] ?? '⚙️'}</span>
          <span>{t}</span>
        </span>
      ))}
    </div>
  );
}
