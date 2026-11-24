/**
 * TalentCatalog —— 「标准目录」的可交互版：分类 → 组件、要求清单、JD 模板、CV 模板、缺口。
 *
 * 数据来自 `GET /api/talent/catalog`（`build_catalog.py` 的产物），页面**只读不写**：
 * 编辑仍回三份 YAML，否则又多一个"两处真相"。门禁里有「catalog 与三份 YAML 一致」这一条，
 * 所以这里不重算、也不缓存。
 *
 * 为什么要有这个页面而不是只给一份 md：
 *   md 能读不能查。真正要回答的问题是「`skill_Excel` 被哪几条要求挂、哪几个 JD 用」
 *   「哪 39 个组件还没标证据档」——那是反查与筛选，表格里 Ctrl+F 找不到。
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { AlertTriangle, ChevronRight, Loader, RefreshCw } from 'lucide-react';
import { useLayoutTokens } from '../../components/layout2/tokens';
import { getTalentCatalog, type TalentCatalog } from './api';

type Tab = 'components' | 'requirements' | 'jd' | 'cv' | 'gaps';

const TABS: { key: Tab; label: string }[] = [
  { key: 'components', label: '分类与组件' },
  { key: 'requirements', label: '要求' },
  { key: 'jd', label: 'JD 模板' },
  { key: 'cv', label: 'CV 模板' },
  { key: 'gaps', label: '缺口' },
];

export default function TalentCatalog() {
  const t = useLayoutTokens();
  const [data, setData] = useState<TalentCatalog | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [tab, setTab] = useState<Tab>('components');
  const [q, setQ] = useState('');
  const [open, setOpen] = useState<Record<string, boolean>>({});
  const [onlyGap, setOnlyGap] = useState(false);

  const load = useCallback(async () => {
    setBusy(true); setErr(null);
    try {
      setData(await getTalentCatalog());
    } catch (e: any) {
      setErr(String(e?.message || e));
    } finally {
      setBusy(false);
    }
  }, []);
  useEffect(() => { void load(); }, [load]);

  const hit = useCallback((...parts: (string | number | null | undefined)[]) => {
    if (!q.trim()) return true;
    const needle = q.trim().toLowerCase();
    return parts.some((p) => String(p ?? '').toLowerCase().includes(needle));
  }, [q]);

  const cov = data?.coverage;
  const gapSets = useMemo(() => ({
    roleMissing: new Set(cov?.components_evidence_role_missing || []),
    compUnused: new Set(cov?.components_unused || []),
    reqUnused: new Set(cov?.requirements_unused || []),
    reqUnassessable: new Set(cov?.requirements_unassessable || []),
  }), [cov]);

  const box: React.CSSProperties = {
    border: `1px solid ${t.border}`, borderRadius: 6, background: t.bgContent,
  };
  const th = (extra?: React.CSSProperties): React.CSSProperties => ({
    textAlign: 'left', padding: '5px 8px', fontSize: 11, color: t.textMuted,
    borderBottom: `1px solid ${t.border}`, fontWeight: 600, whiteSpace: 'nowrap', ...extra,
  });
  const td = (extra?: React.CSSProperties): React.CSSProperties => ({
    padding: '4px 8px', fontSize: 11.5, color: t.textPrimary,
    borderBottom: `1px solid ${t.border}`, verticalAlign: 'top', ...extra,
  });
  const chip = (txt: string, color: string): React.CSSProperties => ({
    display: 'inline-block', fontSize: 10, padding: '1px 6px', borderRadius: 8,
    border: `1px solid ${color}`, color, whiteSpace: 'nowrap',
  });

  if (busy && !data) {
    return <div style={{ padding: 20, fontSize: 12, color: t.textMuted }}>
      <Loader size={12} /> 正在读标准目录…
    </div>;
  }
  if (err) {
    return (
      <div style={{ padding: 20, fontSize: 12, color: '#e5484d', lineHeight: 1.8 }}>
        {err}
        <div style={{ marginTop: 8, color: t.textMuted }}>
          目录由脚本现算：<code>python -m scripts.talent.build_catalog</code>
        </div>
        <button onClick={() => void load()} style={{ marginTop: 10, fontSize: 11 }}>
          <RefreshCw size={11} /> 重试
        </button>
      </div>
    );
  }
  if (!data) return null;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10, padding: '4px 2px 24px' }}>
      {/* 顶部:标题 + 缺口概览 */}
      <div style={{ ...box, padding: '10px 12px' }}>
        <div style={{ fontSize: 13, fontWeight: 600, color: t.textPrimary }}>
          标准目录 · {cov?.categories} 分类 · {cov?.components} 组件 · {cov?.requirements} 要求
          {' · '}JD 模板 {data.jd_template.field_count} 字段 · CV 模板 {data.cv_template.field_count} 字段
        </div>
        <div style={{ display: 'flex', gap: 14, marginTop: 6, flexWrap: 'wrap', fontSize: 11 }}>
          <span style={{ color: '#b3261e' }}>
            <AlertTriangle size={11} /> 证据档未标 {gapSets.roleMissing.size}
          </span>
          <span style={{ color: '#8a6d3b' }}>要求没人用 {gapSets.reqUnused.size}</span>
          <span style={{ color: '#8a6d3b' }}>组件没被要求挂 {gapSets.compUnused.size}</span>
          <span style={{ color: t.textMuted }}>要求不可判 {gapSets.reqUnassessable.size}</span>
        </div>
      </div>

      {/* 工具条 */}
      <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
        <div style={{ display: 'flex', border: `1px solid ${t.border}`, borderRadius: 5, overflow: 'hidden' }}>
          {TABS.map((x) => (
            <button
              key={x.key}
              onClick={() => setTab(x.key)}
              style={{
                fontSize: 11.5, padding: '4px 10px', border: 'none', cursor: 'pointer',
                background: tab === x.key ? t.accent : 'transparent',
                color: tab === x.key ? '#fff' : t.textMuted,
              }}
            >
              {x.label}
            </button>
          ))}
        </div>
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="搜组件 / 要求 / 字段（如 Excel、REQ-D、F.AGE）"
          style={{
            flex: 1, minWidth: 180, fontSize: 11.5, padding: '4px 8px', borderRadius: 5,
            border: `1px solid ${t.border}`, background: t.bgInput, color: t.textPrimary,
          }}
        />
        <label style={{ fontSize: 11, color: t.textMuted, display: 'flex', gap: 4, alignItems: 'center' }}>
          <input type="checkbox" checked={onlyGap} onChange={(e) => setOnlyGap(e.target.checked)} />
          只看有缺口的
        </label>
        <button onClick={() => void load()} disabled={busy} style={{ fontSize: 11, cursor: 'pointer' }}>
          <RefreshCw size={11} /> {busy ? '读取中' : '重新读'}
        </button>
      </div>

      {/* 分类与组件 */}
      {tab === 'components' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          {data.categories.map((c) => {
            const rows = c.components.filter((x) =>
              hit(x.id, x.label, x.kind, x.evidence_role, ...x.requirements, ...x.jds)
              && (!onlyGap || gapSets.roleMissing.has(x.id) || gapSets.compUnused.has(x.id)));
            if (!rows.length) return null;
            const opened = open[c.name] ?? Boolean(q.trim()) ?? false;
            return (
              <div key={c.name} style={box}>
                <button
                  onClick={() => setOpen((s) => ({ ...s, [c.name]: !opened }))}
                  style={{
                    display: 'flex', alignItems: 'center', gap: 6, width: '100%', cursor: 'pointer',
                    padding: '7px 10px', background: 'transparent', border: 'none',
                    color: t.textPrimary, fontSize: 12, textAlign: 'left',
                  }}
                >
                  <ChevronRight size={12} style={{ transform: opened ? 'rotate(90deg)' : 'none' }} />
                  <b>{c.name}</b>
                  <span style={{ color: t.textMuted }}>（{c.components.length}）</span>
                </button>
                {opened && (
                  <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                    <thead>
                      <tr>
                        <th style={th()}>组件</th>
                        <th style={th()}>标签</th>
                        <th style={th()}>kind</th>
                        <th style={th()}>证据档</th>
                        <th style={th({ textAlign: 'right' })}>简历命中</th>
                        <th style={th()}>被要求挂</th>
                        <th style={th()}>被 JD 用</th>
                      </tr>
                    </thead>
                    <tbody>
                      {rows.map((x) => (
                        <tr key={x.id}>
                          <td style={td({ fontFamily: 'ui-monospace,Menlo,monospace', fontSize: 10.5 })}>{x.id}</td>
                          <td style={td()}>{x.label}</td>
                          <td style={td({ color: t.textMuted })}>{x.kind || '—'}</td>
                          <td style={td()}>
                            <span style={chip(x.evidence_role || '未声明',
                              x.evidence_role === 'hard' ? '#2f9e44'
                                : x.evidence_role === 'soft' ? '#8a6d3b' : '#e5484d')}>
                              {x.evidence_role || '未声明'}
                            </span>
                          </td>
                          <td style={td({ textAlign: 'right' })}>{x.cv_count ?? '—'}</td>
                          <td style={td()}>{x.requirements.length
                            ? x.requirements.map((r) => r.replace('REQ-', '')).join('、')
                            : <span style={{ color: '#8a6d3b' }}>无</span>}</td>
                          <td style={td()}>{x.jds.length ? x.jds.join('、')
                            : <span style={{ color: '#8a6d3b' }}>无</span>}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </div>
            );
          })}
        </div>
      )}

      {/* 要求 */}
      {tab === 'requirements' && (
        <div style={box}>
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead>
              <tr>
                <th style={th()}>码</th><th style={th()}>名称</th><th style={th()}>维度</th>
                <th style={th()}>kind</th><th style={th()}>类别</th><th style={th()}>可判</th>
                <th style={th({ textAlign: 'right' })}>组件</th><th style={th()}>被 JD 用</th>
              </tr>
            </thead>
            <tbody>
              {data.requirements
                .filter((r) => hit(r.id, r.name, r.dimension, r.kind, r.data_class, ...r.jds)
                  && (!onlyGap || gapSets.reqUnused.has(r.id) || gapSets.reqUnassessable.has(r.id)))
                .map((r) => (
                  <tr key={r.id}>
                    <td style={td({ fontFamily: 'ui-monospace,Menlo,monospace', fontSize: 10.5 })}>
                      {r.id.replace('REQ-', '')}
                    </td>
                    <td style={td()}>{r.name || '—'}</td>
                    <td style={td({ textAlign: 'center' })}>{r.dimension || '—'}</td>
                    <td style={td({ color: t.textMuted })}>{r.kind || '—'}</td>
                    <td style={td({ color: t.textMuted })}>{r.data_class || '—'}</td>
                    <td style={td()}>{r.assessable ? '✅' : <span style={{ color: '#8a6d3b' }}>—</span>}</td>
                    <td style={td({ textAlign: 'right' })}>{r.components.length}</td>
                    <td style={td()}>{r.jds.length ? r.jds.join('、')
                      : <span style={{ color: '#8a6d3b' }}>无</span>}</td>
                  </tr>
                ))}
            </tbody>
          </table>
        </div>
      )}

      {/* JD / CV 模板 */}
      {(tab === 'jd' || tab === 'cv') && (() => {
        const tpl = tab === 'jd' ? data.jd_template : data.cv_template;
        return (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            <div style={{ fontSize: 11, color: t.textMuted }}>
              {tpl.name} · 共 {tpl.field_count} 个字段。{tpl.rule}
            </div>
            {tpl.sections.map((s) => {
              const rows = s.fields.filter((f) =>
                hit(f.id, f.label, f.dimension, f.prop, f.compare));
              if (!rows.length) return null;
              return (
                <div key={s.code} style={box}>
                  <div style={{ padding: '6px 10px', fontSize: 11.5, color: t.textPrimary,
                                borderBottom: `1px solid ${t.border}` }}>
                    <b>{s.code} · {s.label}</b>
                    <span style={{ color: t.textMuted }}>（{s.fields.length}）</span>
                  </div>
                  <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                    <thead>
                      <tr>
                        <th style={th()}>字段</th><th style={th()}>名称</th><th style={th()}>维度</th>
                        <th style={th({ textAlign: 'right' })}>出现</th>
                        {tab === 'jd'
                          ? <th style={th()}>必填</th>
                          : <th style={th()}>属性</th>}
                        {tab === 'cv' && <th style={th()}>两侧可比</th>}
                        <th style={th()}>说明</th>
                      </tr>
                    </thead>
                    <tbody>
                      {rows.map((f) => (
                        <tr key={f.id}>
                          <td style={td({ fontFamily: 'ui-monospace,Menlo,monospace', fontSize: 10.5 })}>{f.id}</td>
                          <td style={td()}>{f.label}</td>
                          <td style={td({ textAlign: 'center' })}>{f.dimension || '—'}</td>
                          <td style={td({ textAlign: 'right' })}>{f.presence ?? '—'}</td>
                          {tab === 'jd'
                            ? <td style={td()}>{f.required ? '是' : '—'}</td>
                            : <td style={td({ color: t.textMuted })}>{f.prop || '—'}</td>}
                          {tab === 'cv' && <td style={td({ color: t.textMuted })}>{f.compare || '—'}</td>}
                          <td style={td({ color: t.textMuted })}>{f.note || '—'}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              );
            })}
          </div>
        );
      })()}

      {/* 缺口 */}
      {tab === 'gaps' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          {[
            ['组件没标证据档', cov?.components_evidence_role_missing || [],
             '能力「满足」里有多少只是自述，现在答不出来 —— 标一条 runtime 就生效一条'],
            ['要求没被任何 JD 引用', cov?.requirements_unused || [],
             '标准建了没人用：要么有 JD 会用到，要么从库里删掉'],
            ['组件没被任何要求挂', cov?.components_unused || [],
             '抽得出、判不到：要么建一条要求用它，要么它只是词表噪音'],
            ['要求不可判（assessable=false）', cov?.requirements_unassessable || [],
             '对所有人一样，不进分母、也不许拿来淘汰人'],
          ].map(([title, list, why]: any) => (
            <div key={title} style={box}>
              <div style={{ padding: '6px 10px', fontSize: 11.5, color: t.textPrimary,
                            borderBottom: `1px solid ${t.border}` }}>
                <b>{title}</b>
                <span style={{ color: '#e5484d' }}> {list.length}</span>
                <span style={{ color: t.textMuted }}> · {why}</span>
              </div>
              <div style={{ padding: '6px 10px', fontSize: 10.5, lineHeight: 1.9,
                            fontFamily: 'ui-monospace,Menlo,monospace', color: t.textPrimary }}>
                {list.length ? list.join('　') : <span style={{ color: t.textMuted }}>无</span>}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
