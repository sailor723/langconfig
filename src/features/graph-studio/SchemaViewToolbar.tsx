/**
 * Schema-view toolbar: filter input + refresh button.
 *
 * Lives only when the schema view is mounted. Communicates with the
 * diagram components via a tiny module-scoped event bus. A zustand-style
 * approach would be overkill for a single text input.
 */
import { RefreshCw, Search } from 'lucide-react';
import { useLayoutTokens } from '../../components/layout2/tokens';
import { studio, useStudioState } from './studioStore';

/** Module-scoped event bus for the filter input. */
type Listener = (q: string) => void;
const listeners = new Set<Listener>();
export function emitSchemaFilter(query: string): void {
  for (const l of listeners) l(query);
}
export function subscribeSchemaFilter(l: Listener): () => void {
  listeners.add(l);
  return () => {
    listeners.delete(l);
  };
}

export default function SchemaViewToolbar() {
  const t = useLayoutTokens();
  const { dbSummary } = useStudioState();
  const isNeo4j = dbSummary?.type === 'neo4j';

  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 8,
        padding: '6px 12px',
        borderBottom: `1px solid ${t.border}`,
        background: t.bgTabBar,
        flexShrink: 0,
      }}
    >
      <Search size={12} color={t.textDim} />
      <input
        type="text"
        placeholder={
          isNeo4j
            ? 'Filter labels or properties…'
            : 'Filter tables or columns…'
        }
        onChange={(e) => emitSchemaFilter(e.target.value)}
        style={{
          flex: 1,
          background: t.bgInput,
          color: t.textPrimary,
          border: `1px solid ${t.border}`,
          borderRadius: 4,
          padding: '4px 8px',
          fontSize: 12,
          fontFamily: 'inherit',
          outline: 'none',
        }}
      />
      <button
        onClick={() => studio.loadDatabaseSummary()}
        title="Re-introspect the active database"
        style={{
          display: 'inline-flex',
          alignItems: 'center',
          gap: 4,
          padding: '4px 8px',
          fontSize: 11,
          background: 'transparent',
          color: t.textDim,
          border: `1px solid ${t.border}`,
          borderRadius: 4,
          cursor: 'pointer',
        }}
      >
        <RefreshCw size={11} />
        Refresh
      </button>
    </div>
  );
}