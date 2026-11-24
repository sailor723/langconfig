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
import { useTranslation } from 'react-i18next';
import { useLayoutTokens } from '../../components/layout2/tokens';
import { getTalentCatalog, type TalentCatalog } from './api';

type Tab = 'components' | 'requirements' | 'jd' | 'cv' | 'gaps';

const TABS: { key: Tab; key_: string }[] = [
  { key: 'components', key_: 'tc_tab_components' },
  { key: 'requirements', key_: 'tc_tab_requirements' },
  { key: 'jd', key_: 'tc_tab_jd' },
  { key: 'cv', key_: 'tc_tab_cv' },
  { key: 'gaps', key_: 'tc_tab_gaps' },
];

export default function TalentCatalog() {
  const t = useLayoutTokens();
  const { t: tr, i18n } = useTranslation('chat');
  const isZh = String(i18n.language || '').toLowerCase().startsWith('zh');
  /** 数据标签(组件/字段/要求/区段)按全局语言挑;缺英文就回落中文,不显示空白。 */
  const L = (zh?: string | null, en?: string | null) => (isZh ? (zh || en || '') : (en || zh || ''));
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
      <Loader size={12} /> {tr('tc_loading')}
    </div>;
  }
  if (err) {
    return (
      <div style={{ padding: 20, fontSize: 12, color: '#e5484d', lineHeight: 1.8 }}>
        {err}
        <div style={{ marginTop: 8, color: t.textMuted }}>
          {tr('tc_hint')}
        </div>
        <button onClick={() => void load()} style={{ marginTop: 10, fontSize: 11 }}>
          <RefreshCw size={11} /> {tr('tc_retry')}
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
          {tr('tc_summary')} · {cov?.categories} × {cov?.components} × {cov?.requirements}
          {' · '}JD {data.jd_template.field_count} / CV {data.cv_template.field_count} {tr('tc_fields_rule')}
        </div>
        <div style={{ display: 'flex', gap: 14, marginTop: 6, flexWrap: 'wrap', fontSize: 11 }}>
          <span style={{ color: '#b3261e' }}>
            <AlertTriangle size={11} /> {tr('tc_gap_evidence')} {gapSets.roleMissing.size}
          </span>
          <span style={{ color: '#8a6d3b' }}>{tr('tc_gap_req_unused')} {gapSets.reqUnused.size}</span>
          <span style={{ color: '#8a6d3b' }}>{tr('tc_gap_comp_unused')} {gapSets.compUnused.size}</span>
          <span style={{ color: t.textMuted }}>{tr('tc_gap_unassessable')} {gapSets.reqUnassessable.size}</span>
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
              {tr(x.key_)}
            </button>
          ))}
        </div>
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder={tr('tc_search')}
          style={{
            flex: 1, minWidth: 180, fontSize: 11.5, padding: '4px 8px', borderRadius: 5,
            border: `1px solid ${t.border}`, background: t.bgInput, color: t.textPrimary,
          }}
        />
        <label style={{ fontSize: 11, color: t.textMuted, display: 'flex', gap: 4, alignItems: 'center' }}>
          <input type="checkbox" checked={onlyGap} onChange={(e) => setOnlyGap(e.target.checked)} />
          {tr('tc_only_gap')}
        </label>
        <button onClick={() => void load()} disabled={busy} style={{ fontSize: 11, cursor: 'pointer' }}>
          <RefreshCw size={11} /> {busy ? '…' : tr('tc_reload')}
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
                        <th style={th()}>{tr('tc_col_component')}</th>
                        <th style={th()}>{tr('tc_col_label')}</th>
                        <th style={th()}>{tr('tc_col_kind')}</th>
                        <th style={th()}>{tr('tc_col_evidence')}</th>
                        <th style={th({ textAlign: 'right' })}>{tr('tc_col_hits')}</th>
                        <th style={th()}>{tr('tc_col_reqs')}</th>
                        <th style={th()}>{tr('tc_col_jds')}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {rows.map((x) => (
                        <tr key={x.id}>
                          <td style={td({ fontFamily: 'ui-monospace,Menlo,monospace', fontSize: 10.5 })}>{x.id}</td>
                          <td style={td()}>{L(x.label, (x as any).label_en)}</td>
                          <td style={td({ color: t.textMuted })}>{x.kind || '—'}</td>
                          <td style={td()}>
                            <span style={chip(x.evidence_role || tr('tc_undeclared'),
                              x.evidence_role === 'hard' ? '#2f9e44'
                                : x.evidence_role === 'soft' ? '#8a6d3b' : '#e5484d')}>
                              {x.evidence_role || tr('tc_undeclared')}
                            </span>
                          </td>
                          <td style={td({ textAlign: 'right' })}>{x.cv_count ?? '—'}</td>
                          <td style={td()}>{x.requirements.length
                            ? x.requirements.map((r) => r.replace('REQ-', '')).join('、')
                            : <span style={{ color: '#8a6d3b' }}>{tr('tc_none')}</span>}</td>
                          <td style={td()}>{x.jds.length ? x.jds.join('、')
                            : <span style={{ color: '#8a6d3b' }}>{tr('tc_none')}</span>}</td>
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
                <th style={th()}>{tr('tc_col_code')}</th><th style={th()}>{tr('tc_col_name')}</th>
                <th style={th()}>{tr('tc_col_dim')}</th>
                <th style={th()}>{tr('tc_col_kind')}</th><th style={th()}>{tr('tc_col_class')}</th>
                <th style={th()}>{tr('tc_col_assessable')}</th>
                <th style={th({ textAlign: 'right' })}>{tr('tc_col_component')}</th>
                <th style={th()}>{tr('tc_col_jds')}</th>
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
                    <td style={td()}>{L(r.name, (r as any).name_en) || '—'}</td>
                    <td style={td({ textAlign: 'center' })}>{r.dimension || '—'}</td>
                    <td style={td({ color: t.textMuted })}>{r.kind || '—'}</td>
                    <td style={td({ color: t.textMuted })}>{r.data_class || '—'}</td>
                    <td style={td()}>{r.assessable ? '✅' : <span style={{ color: '#8a6d3b' }}>—</span>}</td>
                    <td style={td({ textAlign: 'right' })}>{r.components.length}</td>
                    <td style={td()}>{r.jds.length ? r.jds.join('、')
                      : <span style={{ color: '#8a6d3b' }}>{tr('tc_none')}</span>}</td>
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
              {L(tpl.name, tab === 'jd' ? 'Job description' : 'Candidate profile')} ·{' '}
              {tpl.field_count} {tr('tc_fields_rule')}
            </div>
            {tpl.sections.map((s) => {
              const rows = s.fields.filter((f) =>
                hit(f.id, f.label, f.dimension, f.prop, f.compare));
              if (!rows.length) return null;
              return (
                <div key={s.code} style={box}>
                  <div style={{ padding: '6px 10px', fontSize: 11.5, color: t.textPrimary,
                                borderBottom: `1px solid ${t.border}` }}>
                    <b>{s.code} · {L(s.label, (s as any).label_en)}</b>
                    <span style={{ color: t.textMuted }}>（{s.fields.length}）</span>
                  </div>
                  <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                    <thead>
                      <tr>
                        <th style={th()}>{tr('tc_col_field')}</th><th style={th()}>{tr('tc_col_name')}</th>
                        <th style={th()}>{tr('tc_col_dim')}</th>
                        <th style={th({ textAlign: 'right' })}>{tr('tc_col_presence')}</th>
                        {tab === 'jd'
                          ? <th style={th()}>{tr('tc_col_required')}</th>
                          : <th style={th()}>{tr('tc_col_prop')}</th>}
                        {tab === 'cv' && <th style={th()}>{tr('tc_col_compare')}</th>}
                        <th style={th()}>{tr('tc_col_note')}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {rows.map((f) => (
                        <tr key={f.id}>
                          <td style={td({ fontFamily: 'ui-monospace,Menlo,monospace', fontSize: 10.5 })}>{f.id}</td>
                          <td style={td()}>{L(f.label, (f as any).label_en)}</td>
                          <td style={td({ textAlign: 'center' })}>{f.dimension || '—'}</td>
                          <td style={td({ textAlign: 'right' })}>{f.presence ?? '—'}</td>
                          {tab === 'jd'
                            ? <td style={td()}>{f.required ? (isZh ? '是' : 'yes') : '—'}</td>
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
            [tr('tc_gap_t1'), cov?.components_evidence_role_missing || [], tr('tc_gap_t1_why')],
            [tr('tc_gap_t2'), cov?.requirements_unused || [], tr('tc_gap_t2_why')],
            [tr('tc_gap_t3'), cov?.components_unused || [], tr('tc_gap_t3_why')],
            [tr('tc_gap_t4'), cov?.requirements_unassessable || [], tr('tc_gap_t4_why')],
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
                {list.length ? list.join('　') : <span style={{ color: t.textMuted }}>{tr('tc_none')}</span>}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
