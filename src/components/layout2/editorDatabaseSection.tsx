/**
 * DatabaseSection — where an agent's database is configured, at the AGENT level.
 *
 * Two levels, two jobs:
 *
 *  · Settings → Databases is the CATALOGUE: admin-managed, validated there with its own test button,
 *    right for a database several agents share.
 *  · This section is the agent's OWN configuration. `mode: 'custom'` carries the connection itself, so
 *    an agent can be pointed at a database nobody listed — which is the case the catalogue could not
 *    serve, and the reason this exists.
 *
 * The password is write-only: the API returns `password_set` instead of the value, and leaving the field
 * blank keeps whatever is stored. 测试连接 posts the candidate block and shows the SERVER'S OWN WORDS —
 * a host that does not resolve, a role without rights and a rejected password all look identical in a
 * form, so a test is what makes them different.
 */
import { useEffect, useState } from 'react';
import type { LayoutTokens } from './tokens';

export interface AgentDatabaseBlock {
  mode?: 'catalog' | 'custom';
  name?: string;
  host?: string;
  port?: number | string;
  dbname?: string;
  user?: string;
  password?: string;
  sslmode?: string;
  /** Response-only marker: the stored password exists. Never sent back as a value. */
  password_set?: boolean;
}

export interface DatabaseTestResult {
  ok: boolean;
  detail?: string;
  database?: string;
  user?: string;
  tables?: number;
  server_version?: string;
  host?: string;
  port?: number;
  elapsed_ms?: number;
  target?: string;
}

interface Props {
  /** Persisted agent id; null/0 for a draft → the test button explains it must be saved first. */
  agentId: number | null;
  value: AgentDatabaseBlock | null | undefined;
  onChange: (next: AgentDatabaseBlock | null) => void;
  /** Catalogue entries (Settings → Databases), for the 'catalog' mode picker. */
  catalog: { name: string; dbname?: string | null; host?: string | null; port?: number | string | null; kind?: string }[];
  apiBase: string;
  t: LayoutTokens;
}

const inputStyle = (t: LayoutTokens): React.CSSProperties => ({
  width: '100%',
  padding: '6px 8px',
  fontSize: 12,
  fontFamily: 'inherit',
  background: t.bgContent,
  color: t.textPrimary,
  border: `1px solid ${t.border}`,
  borderRadius: 6,
  outline: 'none',
});

const labelStyle = (t: LayoutTokens): React.CSSProperties => ({
  fontSize: 11,
  color: t.textMuted,
  marginBottom: 3,
  display: 'block',
});

export default function DatabaseSection({ agentId, value, onChange, catalog, apiBase, t }: Props) {
  const block: AgentDatabaseBlock = value ?? { mode: 'catalog' };
  const mode = block.mode ?? 'catalog';
  const [testing, setTesting] = useState(false);
  const [result, setResult] = useState<DatabaseTestResult | null>(null);
  const [draftPassword, setDraftPassword] = useState('');

  // A new agent id (or a different block) invalidates a result from another target.
  useEffect(() => {
    setResult(null);
  }, [mode, block.name, block.host, block.dbname]);

  const patch = (next: Partial<AgentDatabaseBlock>) => {
    const merged: AgentDatabaseBlock = { ...block, ...next };
    // Moving to the catalogue drops the custom fields: keeping them would leave a block that says
    // 'catalog' while carrying a host, and the reader can never tell which one won.
    if (next.mode === 'catalog') {
      setDraftPassword('');
      onChange({ mode: 'catalog', name: merged.name || '' });
      return;
    }
    if (next.mode === 'custom') {
      onChange({
        mode: 'custom',
        host: merged.host || '127.0.0.1',
        port: merged.port || 5432,
        dbname: merged.dbname || '',
        user: merged.user || '',
        sslmode: merged.sslmode || '',
        ...(merged.password ? { password: merged.password } : {}),
        ...(merged.password_set ? { password_set: true } : {}),
      });
      return;
    }
    onChange(merged);
  };

  const test = async () => {
    if (!agentId) {
      setResult({ ok: false, detail: '保存这个 agent 之后才能测试连接（草稿还没有 id）' });
      return;
    }
    setTesting(true);
    setResult(null);
    try {
      // `password` is included only when the user typed one in this session — the stored one never
      // travels to the browser, so a blank field means "test with what the server has".
      const candidate = mode === 'custom'
        ? { mode: 'custom', host: block.host, port: Number(block.port || 5432), dbname: block.dbname,
            user: block.user, sslmode: block.sslmode,
            ...(draftPassword ? { password: draftPassword } : {}) }
        : { mode: 'catalog', name: block.name };
      const res = await fetch(`${apiBase}/api/deepagents/${agentId}/database/test`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ database: candidate }),
      });
      const body = await res.json();
      setResult(body as DatabaseTestResult);
    } catch (err: any) {
      setResult({ ok: false, detail: err?.message ?? '请求失败' });
    } finally {
      setTesting(false);
    }
  };

  const field = (label: string, node: React.ReactNode) => (
    <div style={{ marginBottom: 10 }}>
      <span style={labelStyle(t)}>{label}</span>
      {node}
    </div>
  );

  return (
    <div style={{ maxWidth: 720 }}>
      <div style={{ fontSize: 13, fontWeight: 600, color: t.textPrimary, marginBottom: 4 }}>
        数据库（这个 agent 自己用哪个库）
      </div>
      <div style={{ fontSize: 11, color: t.textMuted, marginBottom: 14, lineHeight: 1.6 }}>
        两种模式：<strong style={{ color: t.textPrimary }}>目录</strong> 指 Settings → Databases 里管理员维护的一条
        （可以共用，也能在那里先测试）；<strong style={{ color: t.textPrimary }}>自定义</strong> 就是这里的字段——
        目录里没有的库也能接。口令只写不读：留空表示沿用已保存的那个。
      </div>

      {/* mode switch */}
      <div style={{ display: 'flex', gap: 6, marginBottom: 14 }}>
        {([['catalog', '目录（Settings → Databases）'], ['custom', '自定义连接']] as const).map(([id, label]) => {
          const active = mode === id;
          return (
            <button
              key={id}
              onClick={() => patch({ mode: id })}
              style={{
                padding: '6px 12px', fontSize: 12, borderRadius: 6, cursor: 'pointer',
                background: active ? 'rgba(0,109,221,0.14)' : t.bgContent,
                border: `1px solid ${active ? '#006DDD' : t.border}`,
                color: active ? '#0b6bcb' : t.textPrimary,
                fontWeight: active ? 600 : 400,
              }}
            >
              {label}
            </button>
          );
        })}
      </div>

      {mode === 'catalog' ? (
        field('目录条目', (
          <select
            value={block.name || ''}
            onChange={e => patch({ name: e.target.value })}
            style={inputStyle(t)}
          >
            <option value="">— 选择一个数据库 —</option>
            {catalog.map(c => (
              <option key={c.name} value={c.name}>
                {c.name}{c.dbname && c.dbname !== c.name ? ` · ${c.dbname}` : ''}
                {c.host ? ` · ${c.host}${c.port ? ':' + c.port : ''}` : ''}
              </option>
            ))}
          </select>
        ))
      ) : (
        <>
          <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr', gap: 10 }}>
            {field('主机 host', (
              <input style={inputStyle(t)} value={block.host ?? ''} placeholder="127.0.0.1"
                     onChange={e => patch({ host: e.target.value })} />
            ))}
            {field('端口 port', (
              <input style={inputStyle(t)} value={String(block.port ?? '')} placeholder="5432"
                     onChange={e => patch({ port: e.target.value })} />
            ))}
          </div>
          {field('数据库名 dbname', (
            <input style={inputStyle(t)} value={block.dbname ?? ''} placeholder="retail_db"
                   onChange={e => patch({ dbname: e.target.value })} />
          ))}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
            {field('用户 user', (
              <input style={inputStyle(t)} value={block.user ?? ''} placeholder="postgres"
                     onChange={e => patch({ user: e.target.value })} />
            ))}
            {field('口令 password（只写）', (
              <input
                style={inputStyle(t)}
                type="password"
                autoComplete="new-password"
                value={draftPassword}
                placeholder={block.password_set ? '已保存（留空 = 不修改）' : '未设置'}
                onChange={e => setDraftPassword(e.target.value)}
              />
            ))}
          </div>
          {field('sslmode（可选）', (
            <input style={inputStyle(t)} value={block.sslmode ?? ''} placeholder="require / prefer / disable"
                   onChange={e => patch({ sslmode: e.target.value })} />
          ))}
        </>
      )}

      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginTop: 8 }}>
        <button
          onClick={test}
          disabled={testing || (mode === 'catalog' ? !block.name : !block.host || !block.dbname)}
          style={{
            padding: '6px 14px', fontSize: 12, borderRadius: 6,
            border: '1px solid #006DDD', background: 'rgba(0,109,221,0.12)', color: '#0b6bcb',
            cursor: testing ? 'default' : 'pointer', fontWeight: 600,
          }}
        >
          {testing ? '连接中…' : '测试连接'}
        </button>
        <span style={{ fontSize: 11, color: t.textMuted }}>
          用当前表单里的值真连一次，不会保存
        </span>
      </div>

      {result && (
        <div
          style={{
            marginTop: 10, padding: '8px 10px', borderRadius: 6, fontSize: 11.5, lineHeight: 1.6,
            background: result.ok ? 'rgba(34,197,94,0.10)' : 'rgba(239,68,68,0.10)',
            border: `1px solid ${result.ok ? 'rgba(34,197,94,0.35)' : 'rgba(239,68,68,0.35)'}`,
            color: result.ok ? '#15803d' : '#b91c1c',
            fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace',
          }}
        >
          {result.ok
            ? `连接成功 · ${result.database}@${result.host}:${result.port} · 角色 ${result.user} · ${result.tables} 张表 · ${result.server_version} · ${result.elapsed_ms}ms`
            : `连接失败 · ${result.detail ?? '未知原因'}`}
        </div>
      )}
    </div>
  );
}
