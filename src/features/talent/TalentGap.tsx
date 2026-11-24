/**
 * TalentGap —— 这份 JD 的 40 格缺口面板。
 *
 * ## 为什么必须有 jd
 * 缺口是**相对某一份 JD** 才成立的：同一个字段在品质经理是「客户原文」，在专案工程师是「缺」。
 * 所以这个组件第一件事就是要求一个 jd，没有 jd 就明说，而不是显示空表 —— 空表会被读成"没有缺口"。
 *
 * ## 两套口径，界面上必须标清楚
 * 数据来自 `GET /api/talent/gap?jd=`：
 *   · `source: draft` —— 有定稿草稿（`jd_draft/<JD>.draft.json`），7 状态，回答"定稿还差什么"；
 *   · `source: trial` —— 没有草稿，退回客户稿覆盖度（`template_fill`），5 状态，
 *     只回答"客户稿写了没有"。
 * 两者混着看，数字一打架就没人再信 —— 所以顶部永远显示当前是哪一套。
 *
 * ## 布局：左边客户原文，右边缺口
 * 「这格填的是什么」和「还缺什么」必须同时看得见 —— 分开两页，看缺口时就得靠记忆回想原文，
 * 于是又出现"这条要求客户到底写没写"的来回猜。所以两栏并排、各自滚动，左边只读。
 *
 * ## 配色不是装饰
 * 「待客户给」用**中性灰蓝**而不是红色：那 5 格现在判不了（不可判），不是错；
 * 用红色会看起来像 5 个 bug，然后有人跑去"修"它们。
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { AlertCircle, ChevronRight, Loader, RefreshCw } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { useLayoutTokens } from '../../components/layout2/tokens';
import { getTalentDoc, getTalentGap, type TalentGapData, type TalentGapField } from './api';

const STATE_COLOR: Record<string, string> = {
  客户原文: '#2f9e44',
  原文: '#2f9e44',
  'HR 侧': '#1c7ed6',
  '原文·空值': '#e8590c',
  '我方建议·待确认': '#8a6d3b',
  待客户确认: '#8a6d3b',
  待客户给: '#5f6b7a',   // 中性：这是「不可判」，不是错
  缺: '#5f6b7a',
  不适用: '#adb5bd',
};

export default function TalentGap({ jd }: { jd: string }) {
  const t = useLayoutTokens();
  const { t: tr, i18n } = useTranslation('chat');
  const isZh = String(i18n.language || '').toLowerCase().startsWith('zh');
  const L = (zh?: string | null, en?: string | null) => (isZh ? (zh || en || '') : (en || zh || ''));
  const [data, setData] = useState<TalentGapData | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [q, setQ] = useState('');
  /** 客户原文（textutil 抽平的 .doc）：和缺口并排看，才知道每格是从哪句话填出来的。 */
  const [jdText, setJdText] = useState<string>('');
  const [textErr, setTextErr] = useState<string>('');
  const [showText, setShowText] = useState(true);
  const [showBlockers, setShowBlockers] = useState(true);
  const [showProps, setShowProps] = useState(true);

  const load = useCallback(async () => {
    if (!jd) { setData(null); return; }
    setBusy(true); setErr(null);
    try {
      setData(await getTalentGap(jd));
    } catch (e: any) {
      setErr(String(e?.message || e));
      setData(null);
    } finally {
      setBusy(false);
    }
  }, [jd]);
  useEffect(() => { void load(); }, [load]);

  useEffect(() => {
    if (!jd) { setJdText(''); return; }
    let dead = false;
    setTextErr('');
    getTalentDoc(jd, `jd_links/_source/${jd}.txt`)
      .then((r) => { if (!dead && r.kind === 'text') setJdText(r.text || ''); })
      .catch((e) => { if (!dead) setTextErr(String((e as Error)?.message || e)); });
    return () => { dead = true; };
  }, [jd]);

  const rows = useMemo(() => {
    const all = data?.fields || [];
    if (!q.trim()) return all;
    const n = q.trim().toLowerCase();
    return all.filter((f) => [f.code, f.label, f.state, f.value, f.why, f.needs]
      .some((x) => String(x ?? '').toLowerCase().includes(n)));
  }, [data, q]);

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
  const chip = (txt: string): React.CSSProperties => ({
    display: 'inline-block', fontSize: 10, padding: '1px 6px', borderRadius: 8,
    border: `1px solid ${STATE_COLOR[txt] || t.textMuted}`,
    color: STATE_COLOR[txt] || t.textMuted, whiteSpace: 'nowrap',
  });

  if (!jd) {
    return (
      <div style={{ ...box, padding: 16, fontSize: 12.5, color: '#e5484d', lineHeight: 1.9 }}>
        <AlertCircle size={13} /> {tr('tg_need_jd')}
      </div>
    );
  }
  if (busy && !data) {
    return <div style={{ padding: 20, fontSize: 12, color: t.textMuted }}>
      <Loader size={12} /> {tr('tg_loading')} {jd}
    </div>;
  }
  if (err) {
    return (
      <div style={{ ...box, padding: 16, fontSize: 12, color: '#e5484d', lineHeight: 1.8 }}>
        <div>{err}</div>
        <div style={{ color: t.textMuted, marginTop: 6 }}>{tr('tg_hint')}</div>
        <button onClick={() => void load()} style={{ marginTop: 10, fontSize: 11 }}>
          <RefreshCw size={11} /> {tr('tg_retry')}
        </button>
      </div>
    );
  }
  if (!data) return null;

  const inJudging = data.in_judging;
  const total = data.template_fields;
  const pct = total ? Math.round((inJudging * 100) / total) : 0;

  /* 客户原文是 textutil 抽平的 Word 表：单元格之间是 \x07（BEL），直接铺出来是一坨。
     这里把它显示成 │，并在标题上写清楚"这是抽平的纯文本，版式与表格不保留"。 */
  const pretty = jdText.replace(/\x07/g, ' │ ').replace(/\r/g, '');

  return (
    <div style={{ display: 'flex', gap: 12, alignItems: 'flex-start', flexWrap: 'wrap' }}>
      {/* ── 左：客户原文（只读锚点）──────────────────────────────── */}
      <div style={{ ...box, flex: '1 1 320px', minWidth: 280, maxWidth: 520,
                    position: 'sticky', top: 0, maxHeight: 'calc(100vh - 130px)',
                    display: 'flex', flexDirection: 'column' }}>
        <button
          onClick={() => setShowText((v) => !v)}
          style={{ display: 'flex', alignItems: 'center', gap: 6, width: '100%', cursor: 'pointer',
                   padding: '7px 10px', background: 'transparent', border: 'none',
                   borderBottom: `1px solid ${t.border}`, color: t.textPrimary,
                   fontSize: 12, textAlign: 'left' }}
        >
          <ChevronRight size={12} style={{ transform: showText ? 'rotate(90deg)' : 'none' }} />
          <b>{tr('tg_jd_text')}</b>
          <span style={{ color: t.textMuted, fontSize: 10.5 }}>· {tr('tg_jd_text_hint')}</span>
        </button>
        {showText && (
          <div style={{ minHeight: 0, overflow: 'auto', padding: '8px 10px' }}>
            {textErr
              ? <div style={{ fontSize: 11, color: '#e5484d' }}>{textErr}</div>
              : pretty
                ? <pre style={{ margin: 0, fontSize: 11, lineHeight: 1.75, whiteSpace: 'pre-wrap',
                                wordBreak: 'break-word', color: t.textPrimary,
                                fontFamily: 'ui-monospace,Menlo,monospace' }}>{pretty}</pre>
                : <div style={{ fontSize: 11, color: t.textMuted }}>{tr('tg_loading')} …</div>}
          </div>
        )}
      </div>

      {/* ── 右：缺口 ─────────────────────────────────────────── */}
      <div style={{ flex: '2 1 560px', minWidth: 420,
                    display: 'flex', flexDirection: 'column', gap: 10 }}>
      {/* 顶部：哪份 JD + 哪套口径 + 能判几格 */}
      <div style={{ ...box, padding: '10px 12px' }}>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, flexWrap: 'wrap' }}>
          <span style={{ fontSize: 14, fontWeight: 600, color: t.textPrimary }}>{data.jd}</span>
          <span style={{ fontSize: 11, color: t.textMuted }}>· {tr('tg_gap_of')} {total} {tr('tg_fields')}</span>
          <span style={{ fontSize: 10.5, padding: '1px 7px', borderRadius: 8,
                         border: `1px solid ${data.source === 'draft' ? '#2f9e44' : '#8a6d3b'}`,
                         color: data.source === 'draft' ? '#2f9e44' : '#8a6d3b' }}>
            {data.source_label}
          </span>
          <span style={{ marginLeft: 'auto', fontSize: 12, color: t.textPrimary }}>
            <b style={{ color: '#2f9e44' }}>{inJudging}</b>/{total} {tr('tg_judgeable')}
            <span style={{ color: t.textMuted }}> ({pct}%)</span>
          </span>
        </div>
        {data.note && (
          <div style={{ marginTop: 6, fontSize: 11, color: '#8a6d3b', lineHeight: 1.7 }}>{data.note}</div>
        )}
        <div style={{ display: 'flex', gap: 12, marginTop: 8, flexWrap: 'wrap', fontSize: 11 }}>
          {data.states.map((s) => (
            <span key={s} style={chip(`${s} ${data.tally[s] ?? 0}`)}>{s} {data.tally[s] ?? 0}</span>
          ))}
        </div>
        <div style={{ marginTop: 8, height: 6, display: 'flex', borderRadius: 3, overflow: 'hidden',
                      background: t.bgInput }}>
          {data.states.map((s) => {
            const n = data.tally[s] ?? 0;
            if (!n) return null;
            return <div key={s} title={`${s} ${n}`}
                        style={{ width: `${(n * 100) / total}%`, background: STATE_COLOR[s] || '#adb5bd' }} />;
          })}
        </div>
      </div>

      {/* 工具栏 */}
      <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder={tr('tg_search')}
          style={{ flex: 1, fontSize: 11.5, padding: '4px 8px', borderRadius: 5,
                   border: `1px solid ${t.border}`, background: t.bgInput, color: t.textPrimary }}
        />
        <button onClick={() => void load()} disabled={busy} style={{ fontSize: 11, cursor: 'pointer' }}>
          <RefreshCw size={11} /> {busy ? '…' : tr('tg_reload')}
        </button>
      </div>

      {/* 等客户给的 */}
      {Boolean(data.blockers.length) && (
        <div style={box}>
          <button onClick={() => setShowBlockers((v) => !v)}
                  style={{ display: 'flex', alignItems: 'center', gap: 6, width: '100%',
                           cursor: 'pointer', padding: '7px 10px', background: 'transparent',
                           border: 'none', color: t.textPrimary, fontSize: 12, textAlign: 'left' }}>
            <ChevronRight size={12} style={{ transform: showBlockers ? 'rotate(90deg)' : 'none' }} />
            <b>{tr('tg_blockers')}</b>
            <span style={{ color: t.textMuted }}>（{data.blockers.length}）</span>
            <span style={{ color: t.textMuted, fontSize: 10.5 }}>· {tr('tg_blockers_hint')}</span>
          </button>
          {showBlockers && (
            <div style={{ padding: '0 10px 8px' }}>
              {data.blockers.map((b) => (
                <div key={b.code} style={{ fontSize: 11, padding: '3px 0', lineHeight: 1.7 }}>
                  <span style={{ fontFamily: 'ui-monospace,Menlo,monospace' }}>{b.code}</span>
                  <span style={{ color: t.textPrimary }}> {b.label}</span>
                  <span style={{ color: t.textMuted }}> — {b.why || '—'}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* 我方建议 */}
      {Boolean(data.proposals.length) && (
        <div style={box}>
          <button onClick={() => setShowProps((v) => !v)}
                  style={{ display: 'flex', alignItems: 'center', gap: 6, width: '100%',
                           cursor: 'pointer', padding: '7px 10px', background: 'transparent',
                           border: 'none', color: t.textPrimary, fontSize: 12, textAlign: 'left' }}>
            <ChevronRight size={12} style={{ transform: showProps ? 'rotate(90deg)' : 'none' }} />
            <b>{tr('tg_proposals')}</b>
            <span style={{ color: t.textMuted }}>（{data.proposals.length}）</span>
            <span style={{ color: t.textMuted, fontSize: 10.5 }}>· {tr('tg_proposals_hint')}</span>
          </button>
          {showProps && (
            <table style={{ width: '100%', borderCollapse: 'collapse' }}>
              <thead>
                <tr>
                  <th style={th()}>{tr('tg_col_field')}</th>
                  <th style={th()}>{tr('tg_col_value')}</th>
                  <th style={th()}>{tr('tg_col_why')}</th>
                  <th style={th()}>{tr('tg_col_needs')}</th>
                </tr>
              </thead>
              <tbody>
                {data.proposals.map((p) => (
                  <tr key={p.code}>
                    <td style={td({ whiteSpace: 'nowrap' })}>
                      <span style={{ fontFamily: 'ui-monospace,Menlo,monospace' }}>{p.code}</span>
                      <div style={{ color: t.textMuted, fontSize: 10.5 }}>{p.label}</div>
                    </td>
                    <td style={td()}>{String(p.value ?? '—')}</td>
                    <td style={td({ color: t.textMuted })}>{p.why || '—'}</td>
                    <td style={td({ color: t.textMuted, whiteSpace: 'nowrap' })}>{p.needs || '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}

      {/* 40 格全表 */}
      <div style={box}>
        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
          <thead>
            <tr>
              <th style={th({ borderTop: `1px solid ${t.border}` })}>{tr('tg_col_sec')}</th>
              <th style={th()}>{tr('tg_col_field')}</th>
              <th style={th()}>{tr('tg_col_value')}</th>
              <th style={th()}>{tr('tg_col_state')}</th>
              <th style={th()}>{tr('tg_col_basis')}</th>
              <th style={th()}>{tr('tg_col_needs')}</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((f: TalentGapField) => (
              <tr key={f.code}>
                <td style={td({ color: t.textMuted, whiteSpace: 'nowrap' })}>{f.section}</td>
                <td style={td({ whiteSpace: 'nowrap' })}>
                  <span style={{ fontFamily: 'ui-monospace,Menlo,monospace', fontSize: 10.5 }}>{f.code}</span>
                  <div style={{ color: t.textMuted, fontSize: 10.5 }}>{L(f.label, (f as any).label_en)}</div>
                </td>
                <td style={td()}>{String(f.value ?? '—')}</td>
                <td style={td()}><span style={chip(f.state)}>{f.state}</span></td>
                <td style={td({ color: t.textMuted, fontSize: 10.5 })}>
                  {f.evidence?.length ? f.evidence.join('；') : (f.why || '—')}
                </td>
                <td style={td({ color: t.textMuted, whiteSpace: 'nowrap' })}>{f.needs || '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {!rows.length && (
          <div style={{ padding: 12, fontSize: 11.5, color: t.textMuted }}>{tr('tg_none')}</div>
        )}
      </div>
      </div>
    </div>
  );
}
