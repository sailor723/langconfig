/**
 * ModernDetailPanel — shows detail of selected node.
 */

import type { Node } from 'reactflow';
import type { AgentStructure } from '../types';

interface Props {
  structure: AgentStructure | null;
  selectedNode: Node | null;
}

export default function ModernDetailPanel({ structure, selectedNode }: Props) {
  if (!structure) {
    return (
      <div
        className="w-[432px] h-full p-4 text-xs overflow-y-auto thick-scrollbar"
        style={{
          background: '#0D1322',
          color: '#99D3FF',
          borderLeft: '1px solid rgba(0, 109, 221, 0.3)',
        }}
      >
        Select an agent to view details.
      </div>
    );
  }

  const data = (selectedNode?.data ?? {}) as Record<string, any>;
  const isMain = selectedNode?.id === 'main';
  const isSkill = selectedNode?.type === 'subAgent';
  const isTool = selectedNode?.type === 'tool';
  const isInfo = selectedNode?.type === 'info';

  // No selection: show agent overview
  if (!selectedNode) {
    return (
      <div
        className="w-[432px] h-full p-4 overflow-y-auto thick-scrollbar"
        style={{
          background: '#0D1322',
          borderLeft: '1px solid rgba(0, 109, 221, 0.3)',
          color: '#F2FAFF',
        }}
      >
        <div className="flex items-center gap-2 mb-3">
          <span style={{ fontSize: 18 }}>🧠</span>
          <h3 className="text-sm font-semibold">{structure.name}</h3>
        </div>
        {structure.description && (
          <p className="text-[15px] mb-3" style={{ color: '#99D3FF' }}>
            {structure.description}
          </p>
        )}
        <SectionTitle>Model</SectionTitle>
        <Pill>{structure.model}</Pill>
        <SectionTitle>Tools</SectionTitle>
        <div className="flex flex-wrap gap-1.5">
          {(structure.native_tools ?? []).slice(0, 8).map((t, i) => (
            <Pill key={i}>{t}</Pill>
          ))}
          {(structure.native_tools?.length ?? 0) > 8 && (
            <Pill>+{(structure.native_tools?.length ?? 0) - 8} more</Pill>
          )}
        </div>
        <SectionTitle>Sub-agents</SectionTitle>
        <div className="flex flex-wrap gap-1.5">
          {(structure.subagents ?? []).slice(0, 6).map((s, i) => (
            <Pill key={i}>{s.name}</Pill>
          ))}
          {(structure.subagents?.length ?? 0) === 0 && (
            <span className="text-[15px]" style={{ color: '#99D3FF' }}>None</span>
          )}
        </div>
        {structure.system_prompt && (
          <>
            <SectionTitle>System Prompt</SectionTitle>
            <div
              className="text-[15px] p-2 rounded-lg"
              style={{
                background: 'rgba(0, 109, 221, 0.08)',
                color: '#99D3FF',
                minHeight: 345,
                maxHeight: 690,
                overflowY: 'auto',
              }}
            >
              {structure.system_prompt}
            </div>
          </>
        )}
      </div>
    );
  }

  return (
    <div
      className="w-[432px] h-full p-4 overflow-y-auto"
      style={{
        background: '#0D1322',
        borderLeft: '1px solid rgba(0, 109, 221, 0.3)',
        color: '#F2FAFF',
      }}
    >
      <div className="flex items-center gap-2 mb-3">
        <span style={{ fontSize: 18 }}>
          {isMain ? '🧠' : isSkill ? '📡' : isTool ? '⚙️' : isInfo ? 'ℹ️' : '📦'}
        </span>
        <h3 className="text-sm font-semibold">{data.label ?? selectedNode.id}</h3>
      </div>

      {data.model && (
        <>
          <SectionTitle>Model</SectionTitle>
          <Pill>{data.model}</Pill>
        </>
      )}

      {data.value && (
          <>
            <SectionTitle>{data.label}</SectionTitle>
            <div
              className="text-[15px] p-2 rounded-lg"
              style={{
                background: 'rgba(0, 109, 221, 0.08)',
                color: '#99D3FF',
                minHeight: 345,
                maxHeight: 690,
                overflowY: 'auto',
                whiteSpace: 'pre-wrap',
              }}
            >
              {data.value}
            </div>
          </>
        )}

      {data.skill_type && (
        <>
          <SectionTitle>Type</SectionTitle>
          <Pill>{data.skill_type}</Pill>
        </>
      )}

      {data.description && !data.value && (
        <>
          <SectionTitle>Description</SectionTitle>
          <div className="text-[11px]" style={{ color: '#99D3FF' }}>{data.description}</div>
        </>
      )}

      <SectionTitle>Node Info</SectionTitle>
      <div className="text-[15px] space-y-1" style={{ color: '#99D3FF' }}>
        <div>ID: <span style={{ color: '#F2FAFF' }}>{selectedNode.id}</span></div>
        <div>Position: <span style={{ color: '#F2FAFF' }}>{Math.round(selectedNode.position.x)}, {Math.round(selectedNode.position.y)}</span></div>
        <div>Type: <span style={{ color: '#F2FAFF' }}>{selectedNode.type}</span></div>
      </div>
    </div>
  );
}

function SectionTitle({ children }: { children: React.ReactNode }) {
  return (
    <div
      className="text-[14px] uppercase tracking-wider mt-4 mb-1.5 font-bold"
      style={{ color: '#7FC8FF' }}
    >
      {children}
    </div>
  );
}

function Pill({ children }: { children: React.ReactNode }) {
  return (
    <span
      className="inline-block px-3 py-1 text-[14px] rounded-full font-medium"
      style={{
        background: 'linear-gradient(135deg, rgba(0, 109, 221, 0.25), rgba(127, 200, 255, 0.1))',
        border: '1px solid rgba(0, 109, 221, 0.5)',
        color: '#F2FAFF',
      }}
    >
      {children}
    </span>
  );
}
