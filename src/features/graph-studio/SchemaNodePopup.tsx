/**
 * Click-popup for schema-view nodes (SQL table or Neo4j label).
 *
 * Drag-and-resize chrome is deliberately similar to GraphCanvas.NodePopup
 * for visual consistency. Content is view-specific — kept in a single
 * component here so the popup-vs-content split mirrors the rest of the
 * studio.
 */
import {
  useEffect,
  useRef,
  useState,
  type CSSProperties,
  type MouseEvent as ReactMouseEvent,
} from 'react';
import { X } from 'lucide-react';
import { useLayoutTokens, type LayoutTokens } from '../../components/layout2/tokens';
import { studio, useStudioState } from './studioStore';
import type { LabelNode, TableNode } from './api';

export function SchemaNodePopup() {
  const t = useLayoutTokens();
  const { activeNodeId, dbSummary } = useStudioState();
  const [pos, setPos] = useState<{ x: number; y: number } | null>(null);
  const cardRef = useRef<HTMLDivElement>(null);

  if (!activeNodeId) return null;

  // Find the matching payload entry by id (= table name or label name).
  const tableNode: TableNode | undefined = dbSummary?.er_diagram?.tables.find(
    (tb) => tb.name === activeNodeId
  );
  const labelNode: LabelNode | undefined =
    dbSummary?.network_diagram?.label_nodes.find(
      (l) => l.name === activeNodeId
    );
  if (!tableNode && !labelNode) return null;

  const drag = makeDragHandler(cardRef, setPos);

  const title = tableNode?.name ?? labelNode?.name ?? '';
  const subtitle = tableNode
    ? `${tableNode.columns.length} columns · ${
        tableNode.row_count?.toLocaleString() ?? '—'
      } rows`
    : `${labelNode?.count.toLocaleString() ?? 0} nodes · ${
        labelNode?.properties.length ?? 0
      } properties`;

  // Escape closes the popup.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') studio.selectNode(null);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  return (
    <>
      <div
        style={{ position: 'absolute', inset: 0, zIndex: 9, background: 'transparent' }}
        onClick={() => studio.selectNode(null)}
      />
      <div
        ref={cardRef}
        style={{
          position: 'absolute',
          zIndex: 10,
          width: 560,
          minWidth: 360,
          maxWidth: 'calc(100% - 20px)',
          maxHeight: 'calc(100% - 20px)',
          resize: 'vertical',
          overflow: 'auto',
          display: 'flex',
          flexDirection: 'column',
          background: t.bgContent,
          border: `1px solid ${t.border}`,
          borderRadius: 8,
          boxShadow: '0 8px 32px rgba(0,0,0,0.35)',
          ...(pos
            ? { left: pos.x, top: pos.y }
            : { top: 60, right: 10 }),
        }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div
          onMouseDown={drag.onMouseDown}
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 8,
            padding: '10px 12px',
            borderBottom: `1px solid ${t.border}`,
            background: t.bgSidebar,
            flexShrink: 0,
            cursor: 'move',
            userSelect: 'none',
          }}
        >
          <span
            style={{
              fontSize: 12.5,
              fontWeight: 600,
              fontFamily:
                'ui-monospace, SFMono-Regular, Menlo, monospace',
              color: t.textPrimary,
            }}
          >
            {title}
          </span>
          <span style={{ fontSize: 10.5, color: t.textMuted, marginLeft: 4 }}>
            {subtitle}
          </span>
          <button
            onClick={() => studio.selectNode(null)}
            title="Close (Esc)"
            style={{
              marginLeft: 'auto',
              width: 24,
              height: 24,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              border: 'none',
              background: 'transparent',
              color: t.textMuted,
              cursor: 'pointer',
              borderRadius: 4,
            }}
          >
            <X size={14} />
          </button>
        </div>
        {/* Body */}
        <div
          style={{
            flex: 1,
            minHeight: 0,
            overflow: 'auto',
            padding: 12,
          }}
        >
          {tableNode && <TableDetail table={tableNode} t={t} />}
          {labelNode && <LabelDetail label={labelNode} t={t} />}
        </div>
      </div>
    </>
  );
}

function TableDetail({
  table,
  t,
}: {
  table: TableNode;
  t: LayoutTokens;
}) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <div>
        <SectionLabel t={t}>columns ({table.columns.length})</SectionLabel>
        <div
          style={{
            border: `1px solid ${t.border}`,
            borderRadius: 6,
            overflow: 'hidden',
          }}
        >
          <table
            style={{
              width: '100%',
              borderCollapse: 'collapse',
              fontSize: 11,
            }}
          >
            <thead>
              <tr style={{ background: t.bgTabBar, color: t.textDim }}>
                <th style={cellStyle('left')}>name</th>
                <th style={cellStyle('left')}>type</th>
                <th style={cellStyle('left')}>nullable</th>
                <th style={cellStyle('left')}>key</th>
              </tr>
            </thead>
            <tbody>
              {table.columns.map((c) => (
                <tr key={c.name} style={{ borderTop: `1px solid ${t.border}22` }}>
                  <td
                    style={{
                      ...cellStyle('left'),
                      fontFamily: 'monospace',
                      color: c.pk ? t.accent : t.textPrimary,
                      fontWeight: c.pk ? 600 : 400,
                    }}
                  >
                    {c.pk && (
                      <span
                        style={{
                          display: 'inline-block',
                          width: 6,
                          height: 6,
                          borderRadius: '50%',
                          background: t.accent,
                          marginRight: 6,
                        }}
                      />
                    )}
                    {c.name}
                  </td>
                  <td style={{ ...cellStyle('left'), color: t.textMuted }}>
                    {c.type}
                  </td>
                  <td style={{ ...cellStyle('left'), color: t.textMuted }}>
                    {c.nullable ? 'YES' : 'NO'}
                  </td>
                  <td
                    style={{
                      ...cellStyle('left'),
                      color: c.pk ? t.accent : t.textDim,
                    }}
                  >
                    {c.pk ? 'PK' : '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
      <div>
        <SectionLabel t={t}>sample rows</SectionLabel>
        <div
          style={{
            fontSize: 11,
            color: t.textDim,
            padding: '6px 8px',
            border: `1px solid ${t.border}`,
            borderRadius: 6,
            background: t.bgSidebar,
          }}
        >
          Sample rows are not fetched in v1. Use the chat to query this table.
        </div>
      </div>
    </div>
  );
}

function LabelDetail({
  label,
  t,
}: {
  label: LabelNode;
  t: LayoutTokens;
}) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <div>
        <SectionLabel t={t}>
          properties ({label.properties.length})
        </SectionLabel>
        {label.properties.length === 0 ? (
          <div
            style={{
              fontSize: 11,
              color: t.textDim,
              padding: '6px 0',
            }}
          >
            (none)
          </div>
        ) : (
          <div
            style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}
          >
            {label.properties.map((p) => (
              <span
                key={p}
                style={{
                  fontSize: 11,
                  fontFamily: 'monospace',
                  padding: '2px 6px',
                  borderRadius: 3,
                  background: t.bgInput,
                  color: t.textPrimary,
                  border: `1px solid ${t.border}`,
                }}
              >
                {p}
              </span>
            ))}
          </div>
        )}
      </div>
      <div>
        <SectionLabel t={t}>counts</SectionLabel>
        <div
          style={{
            fontSize: 11,
            color: t.textMuted,
            padding: '6px 8px',
            border: `1px solid ${t.border}`,
            borderRadius: 6,
            background: t.bgSidebar,
          }}
        >
          {label.count.toLocaleString()} node
          {label.count === 1 ? '' : 's'} with label{' '}
          <code style={{ fontFamily: 'monospace' }}>{label.name}</code>
        </div>
      </div>
      <div style={{ fontSize: 10.5, color: t.textDim, fontStyle: 'italic' }}>
        Drill-down to sample nodes ships in a follow-up. Use the chat to query
        this label.
      </div>
    </div>
  );
}

function SectionLabel({
  t,
  children,
}: {
  t: LayoutTokens;
  children: React.ReactNode;
}) {
  return (
    <div
      style={{
        fontSize: 10,
        textTransform: 'uppercase',
        letterSpacing: 0.6,
        color: t.textDim,
        marginBottom: 4,
      }}
    >
      {children}
    </div>
  );
}

function cellStyle(align: 'left' | 'right' | 'center'): CSSProperties {
  return {
    padding: '5px 8px',
    textAlign: align,
    fontFamily: 'inherit',
  };
}

function makeDragHandler(
  cardRef: React.RefObject<HTMLDivElement | null>,
  setPos: (p: { x: number; y: number }) => void
) {
  return {
    onMouseDown(e: ReactMouseEvent) {
      const rect = cardRef.current?.getBoundingClientRect();
      if (!rect) return;
      const startX = e.clientX - rect.left;
      const startY = e.clientY - rect.top;
      const startPos = { x: rect.left, y: rect.top };
      const onMove = (ev: MouseEvent) => {
        setPos({
          x: startPos.x + ev.clientX - startX,
          y: startPos.y + ev.clientY - startY,
        });
      };
      const onUp = () => {
        window.removeEventListener('mousemove', onMove);
        window.removeEventListener('mouseup', onUp);
      };
      window.addEventListener('mousemove', onMove);
      window.addEventListener('mouseup', onUp);
    },
  };
}