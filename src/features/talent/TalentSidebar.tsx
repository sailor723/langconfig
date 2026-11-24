/**
 * TalentSidebar — 左轨浏览器。**一个开关,两种内容,不并列**。
 *
 *   Talent  仓库里的正式产物:1 客户原文 → 2 引用文件 → 3 定稿 / 待补清单 …
 *   Agent   某个 agent 自己的工作区:upload/(你交给它的) + generated/(它写出来的)
 *
 * 为什么二选一而不是上下叠着:这两类东西不是同一条链上的。叠在一起时一屏里既有正式产物
 * 又有 agent 的意见,读者分不清哪一行"已经过门禁"、哪一行"只是某人说的" —— 而这条链上
 * 最容易犯的错就是把后者当前者用。开关逼你先说清楚"我要看哪一种"。
 *
 * 选中项**不在这里存**:点一个文件 = `openTab({ viewType: 'talent-doc', data: {...} })`,
 * TalentDocView 从 `tab.data` 里读。和 Knowledge 的 doc tab 是同一套机制,
 * 所以"当前打开的是哪个文件"只有一个权威(tab)。
 *
 * 只读与否由**服务端**决定(api/talent/routes.py 的 WRITABLE/READONLY),这里只照它显示。
 * 前端再判一次就等于有两个权威。
 */
import { useCallback, useEffect, useState } from 'react';
import { Bot, Briefcase, FileText, Inbox, Lock, RefreshCw, Loader2, Upload } from 'lucide-react';
import { useLayoutTokens } from '../../components/layout2/tokens';
import { useLayoutState } from '../../components/layout2/useLayout';
import { useProject } from '../../contexts/ProjectContext';
import {
  getTalentGap, listAgentFiles, listTalentDocs, uploadTalentJd,
  type AgentFile, type TalentFile, type TalentJd,
} from './api';
import { useTalentAgentId } from './currentAgent';

/** 文件名从路径里取（面板窄，全路径会把每一行都撑成两行）。 */
function baseName(path: string): string {
  const parts = path.split('/');
  return parts[parts.length - 1] || path;
}

/** 每个文件一个 tab。id 要能唯一决定「打开的是哪一份」，所以来源和路径都在里面。 */
function tabIdFor(jd: string, path: string): string {
  return `talent:${jd}:${path}`;
}

type BrowserTab = 'talent' | 'agent';
const TAB_KEY = 'talent.browserTab';

/** 只显示人读的产物(md/docx/txt),隐藏 yaml/json。默认开 —— 一屏里全是 yaml 时看不出哪份要读。 */
const HUMAN_KEY = 'talent.humanOnly';
/** 上次选的 JD。刷新后不该跳回清单第一份（第一份往往就是缺口最大的那份）。 */
const JD_KEY = 'talent.jd';

function rememberedJd(): string {
  // URL 里的 ?jd= 优先（方便把"我正在看品质经理"发给同事），其次 localStorage。
  try {
    const fromUrl = new URL(window.location.href).searchParams.get('jd');
    if (fromUrl) return fromUrl;
  } catch { /* 读不到 URL 不算错 */ }
  try {
    return window.localStorage.getItem(JD_KEY) || '';
  } catch {
    return '';
  }
}
/** 机读后缀:md/docx 能覆盖它们的内容,不需要在人读视图里出现。 */
const MACHINE_RE = /\.(ya?ml|json)$/i;
function readHumanOnly(): boolean {
  try {
    const v = window.localStorage.getItem(HUMAN_KEY);
    return v === null ? true : v === '1';
  } catch {
    return true;
  }
}

function readTab(): BrowserTab {
  try {
    return window.localStorage.getItem(TAB_KEY) === 'agent' ? 'agent' : 'talent';
  } catch {
    return 'talent';
  }
}

export default function TalentSidebar() {
  const t = useLayoutTokens();
  const { openTab, closeTab, tabs, activeTabId } = useLayoutState();
  const { activeProject } = useProject();
  const projectId = (activeProject as any)?.id ?? undefined;
  // 和对话栏同一个 agent —— 否则会出现"问的是 391、列的是 386 的产物"。
  const [agentId] = useTalentAgentId();

  // ── 开关:记在 localStorage,刷新后回到你刚才看的那一侧 ──
  const [tab, setTab] = useState<BrowserTab>(readTab);
  const [humanOnly, setHumanOnly] = useState<boolean>(readHumanOnly);
  useEffect(() => {
    try { window.localStorage.setItem(HUMAN_KEY, humanOnly ? '1' : '0'); } catch { /* 同上 */ }
  }, [humanOnly]);
  useEffect(() => {
    try { window.localStorage.setItem(TAB_KEY, tab); } catch { /* 存不下不是错误 */ }
  }, [tab]);

  // ── Talent 侧 ──
  const [jds, setJds] = useState<TalentJd[]>([]);
  const [jd, setJd] = useState<string>('');
  /** 后端给的默认 JD（`jd_inputs` 里 default: true）—— 前端不猜第一份。 */
  const [defaultJd, setDefaultJd] = useState<string>('');
  /** 当前 JD 的缺口小结（数字全部来自后端 /gap，不在前端重算）。 */
  const [gap, setGap] = useState<{ in_judging: number; template_fields: number;
                                  blockers: number; proposals: number;
                                  source: 'draft' | 'trial' } | null>(null);
  const [gapErr, setGapErr] = useState<string>('');
  const [uploading, setUploading] = useState(false);
  const [uploadMsg, setUploadMsg] = useState('');
  /** 全局文档（标准目录/总览）：不属于任何一份 JD，单独一组显示。 */
  const [globals, setGlobals] = useState<TalentFile[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // 当前正在编辑的那个 tab —— 用来高亮"你打开的是哪一份"，而不是靠本地 state 记一遍。
  const activeTab = tabs.find((x) => x.id === activeTabId) ?? null;
  const activeJd: string | undefined = activeTab?.data?.jd;
  const activePath: string | undefined = activeTab?.data?.path;

  // ── Agent 侧 ──
  const [agentFiles, setAgentFiles] = useState<AgentFile[]>([]);
  const [agentName, setAgentName] = useState<string>('');
  const [agentErr, setAgentErr] = useState<string | null>(null);

  const onUpload = async (file: File) => {
    setUploading(true); setUploadMsg('');
    try {
      const r = await uploadTalentJd(file);
      setDefaultJd((d) => d || r.jd);
      await new Promise<void>((res) => { loadDocs(); setTimeout(res, 300); });
      setJd(r.jd);
      remember(r.jd);
      // 上传后先给人看缺口 md（业务与 HR 要读的那一份），而不是丢在列表深处
      openTab({
        id: tabIdFor(r.jd, r.md),
        label: baseName(r.md),
        viewType: 'talent-doc',
        data: { jd: r.jd, path: r.md },
      });
      dropPlaceholder();
      setUploadMsg(`已抽取：能判 ${r.gap.in_judging}/${r.gap.template_fields} 格`);
    } catch (e: any) {
      setUploadMsg('');
      setError(`上传失败：${String(e?.message || e)}`);
    } finally {
      setUploading(false);
    }
  };

  const remember = (v: string) => {
    try { window.localStorage.setItem(JD_KEY, v); } catch { /* 存不下不影响使用 */ }
    try {
      const u = new URL(window.location.href);
      u.searchParams.set('jd', v);
      window.history.replaceState({}, '', u.toString());
    } catch { /* 同上 */ }
  };

  const loadDocs = useCallback(() => {
    setLoading(true);
    listTalentDocs()
      .then((d) => {
        const list = d.jds || [];
        setJds(list);
        setDefaultJd(d.default_jd || '');
        setGlobals((d.globals || []) as TalentFile[]);
        setError(null);
        // 落点优先级：正在编辑的那份 → 上次选的（localStorage）→ 后端默认（品质经理）→ 第一份。
        // 「第一份」永远是最后手段：清单是按名字排的，第一份往往就是缺口最大的那份。
        setJd((cur) => cur || activeJd || rememberedJd() || d.default_jd || list[0]?.jd || '');
      })
      .catch((e) => setError(`读取 JD 清单失败：${String((e as Error)?.message || e)}`))
      .finally(() => setLoading(false));
    // activeJd 只在首屏落地时有意义，之后由用户点选决定 —— 故意不列进依赖，否则刷新会抢走选择。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const loadAgentFiles = useCallback(() => {
    setAgentErr(null);
    listAgentFiles(agentId, projectId)
      .then((r) => { setAgentFiles(r.files || []); setAgentName(r.agent?.name || ''); })
      .catch((e) => {
        setAgentFiles([]);
        // 后端可能还没重启(接口 404)—— 把话说清楚,别让人以为"它就是没文件"
        setAgentErr(String((e as Error)?.message || e));
      });
  }, [projectId, agentId]);

  useEffect(() => { loadDocs(); }, [loadDocs]);

  // 缺口小结：换 JD 就重新取。取不到不影响文档树，只是这一行显示"读取失败"。
  useEffect(() => {
    if (!jd) { setGap(null); return; }
    let dead = false;
    setGapErr('');
    getTalentGap(jd)
      .then((g) => {
        if (dead) return;
        setGap({ in_judging: g.in_judging, template_fields: g.template_fields,
                 blockers: g.blockers.length, proposals: g.proposals.length,
                 source: g.source });
      })
      .catch((e) => { if (!dead) { setGapErr(String((e as Error)?.message || e)); setGap(null); } });
    return () => { dead = true; };
  }, [jd]);
  useEffect(() => { loadAgentFiles(); }, [loadAgentFiles]);

  const refresh = () => { loadDocs(); loadAgentFiles(); };

  const current = jds.find((x) => x.jd === jd) || null;
  const allFiles: TalentFile[] = (current?.files || []).filter((f) => f.exists);
  // 只显示人读的:md/docx/txt。yaml/json 是机读的,内容在 md 里都有;
  // 但要看原始口径(rank_rule / cut / 引用行号)时把开关打开即可。
  const files: TalentFile[] = humanOnly ? allFiles.filter((f) => !MACHINE_RE.test(f.path)) : allFiles;
  const hiddenCount = allFiles.length - files.length;

  // 进入 Talent 时 App 会开一个空占位 tab（direct-talent）。用户真正选了文件之后
  // 它就没有意义了，留着只会让 tab 栏多一个空白页。
  const dropPlaceholder = () => {
    if (tabs.some((x) => x.id === 'direct-talent')) closeTab('direct-talent');
  };

  const openRepoFile = (f: TalentFile) => {
    openTab({
      id: tabIdFor(jd, f.path),
      label: baseName(f.path),
      viewType: 'talent-doc',
      data: { jd, path: f.path },
    });
    dropPlaceholder();
  };

  const openAgentFile = (f: AgentFile) => {
    openTab({
      id: `talent-agent:${agentId}:${f.path}`,
      label: f.name,
      // 和正式产物**同一个视图**:中间文档 + 右边对话栏。区别只在数据来源和只读。
      viewType: 'talent-doc',
      data: { agentId, agentPath: f.path },
    });
    dropPlaceholder();
  };

  const byDir = (dir: AgentFile['dir']) => agentFiles.filter((f) => f.dir === dir);

  const rowStyle = (active: boolean): React.CSSProperties => ({
    display: 'flex', alignItems: 'center', gap: 5, width: '100%', textAlign: 'left',
    cursor: 'pointer', padding: '4px 8px', borderRadius: 4, marginBottom: 1,
    border: `1px solid ${active ? t.accent : 'transparent'}`,
    background: active ? `${t.accent}18` : 'transparent',
    color: t.textPrimary, fontSize: 11.5, lineHeight: 1.35,
  });

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', minHeight: 0,
                  fontSize: 12, color: t.textPrimary }}>
      {/* 头：标题 + 刷新 */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '8px 10px',
                    borderBottom: `1px solid ${t.border}`, flexShrink: 0 }}>
        <Briefcase size={13} style={{ color: t.accent }} />
        <span style={{ fontSize: 11, fontWeight: 600, letterSpacing: 0.4,
                       textTransform: 'uppercase', color: t.textMuted }}>浏览器</span>
        <button
          onClick={refresh}
          title="重新读取"
          style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', background: 'transparent',
                   border: 'none', color: t.textMuted, cursor: 'pointer', padding: 2 }}
        >
          {loading ? <Loader2 size={13} className="animate-spin" /> : <RefreshCw size={13} />}
        </button>
      </div>

      {/* 开关:一次只看一种 */}
      <div style={{ display: 'flex', border: `1px solid ${t.border}`, borderRadius: 5,
                    overflow: 'hidden', margin: '8px 10px 6px', flexShrink: 0 }}>
        {([
          ['talent', 'Talent 产物', Briefcase],
          ['agent', 'Agent 文件', Bot],
        ] as const).map(([key, label, Icon]) => (
          <button
            key={key}
            onClick={() => setTab(key)}
            style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center',
                     gap: 4, fontSize: 11, padding: '5px 6px', cursor: 'pointer', border: 'none',
                     background: tab === key ? t.accent : 'transparent',
                     color: tab === key ? '#fff' : t.textMuted }}
          >
            <Icon size={11} /> {label}
          </button>
        ))}
      </div>

      {/* ── Talent:仓库里的正式产物链 ── */}
      {tab === 'talent' && (
        <>
          <div style={{ padding: '2px 10px 8px', borderBottom: `1px solid ${t.border}`, flexShrink: 0 }}>
            <select
              value={jd}
              onChange={(e) => { setJd(e.target.value); remember(e.target.value); }}
              disabled={jds.length === 0}
              style={{ width: '100%', fontSize: 12, padding: '4px 6px', borderRadius: 4,
                       border: `1px solid ${t.border}`, background: t.bgContent, color: t.textPrimary }}
            >
              {jds.length === 0 && <option value="">（没有 JD）</option>}
              {jds.map((x) => (
                <option key={x.jd} value={x.jd}>
                  {x.jd} · {x.existing} 个产物{x.jd === defaultJd ? '（默认）' : ''}
                </option>
              ))}
            </select>
            {/* 缺口小结：跟着上面那份 JD 走。零占位 —— 它回答的是"这份 JD 现在能判几格"，
                而不是再造一个需要点开才知道的页面。 */}
            {jd && (
              <button
                onClick={() => {
                  openTab({
                    id: tabIdFor(jd, '@gap'),
                    label: 'JD · 原文与缺口',
                    viewType: 'talent-doc',
                    data: { jd, path: '@gap' },
                  });
                  dropPlaceholder();
                }}
                title={gapErr || '点开看 40 格明细：能判几格 / 等客户给什么 / 我方建议什么'}
                style={{
                  marginTop: 6, width: '100%', textAlign: 'left', fontSize: 11,
                  padding: '4px 7px', borderRadius: 4, cursor: 'pointer',
                  border: `1px solid ${t.border}`, background: t.bgInput, color: t.textPrimary,
                }}
              >
                {gap
                  ? <>缺口 · <b style={{ color: '#2f9e44' }}>{gap.in_judging}</b>/{gap.template_fields} 能判
                      {gap.blockers ? <span style={{ color: '#5f6b7a' }}> · 等客户 {gap.blockers}</span> : null}
                      {gap.proposals ? <span style={{ color: '#8a6d3b' }}> · 建议 {gap.proposals}</span> : null}
                      {gap.source === 'trial' ? <span style={{ color: t.textMuted }}> · 仅客户稿覆盖度</span> : null}
                    </>
                  : gapErr ? <span style={{ color: '#e5484d' }}>缺口读取失败</span> : '缺口 …'}
              </button>
            )}
            {/* Phase 1 入口：上传一份 JD。上传后自动选中它，并打开"缺口 vs 标准模板"的 md。
                浏览器始终只服务**一份** JD —— 上传不会变成"多 JD 视图"。 */}
            <label
              title="上传一份客户 JD（doc/docx/pdf/xlsx/txt/md）→ 抽文本 → 生成缺口 md"
              style={{
                marginTop: 6, width: '100%', display: 'flex', alignItems: 'center',
                justifyContent: 'center', gap: 5, fontSize: 11, padding: '3px 6px',
                borderRadius: 4, cursor: uploading ? 'progress' : 'pointer',
                border: `1px solid ${t.border}`,
                background: t.bgInput, color: uploading ? t.textMuted : t.textPrimary,
              }}
            >
              <Upload size={11} />
              {uploading ? '正在抽取…' : uploadMsg || '上传 JD（出缺口 md）'}
              <input
                type="file"
                accept=".doc,.docx,.pdf,.xlsx,.txt,.md"
                style={{ display: 'none' }}
                onChange={(e) => {
                  const f = e.target.files?.[0];
                  e.currentTarget.value = '';
                  if (f) void onUpload(f);
                }}
              />
            </label>
            <button
              onClick={() => setHumanOnly((v) => !v)}
              title={humanOnly
                ? `只显示人读的(md/docx/txt);已隐藏 ${hiddenCount} 个机读文件(yaml/json)`
                : '显示全部,包含 yaml/json 机读文件'}
              style={{
                marginTop: 6, width: '100%', display: 'flex', alignItems: 'center',
                justifyContent: 'center', gap: 5, fontSize: 11, padding: '3px 6px',
                borderRadius: 4, cursor: 'pointer',
                border: `1px solid ${t.border}`,
                background: humanOnly ? t.bgContent : t.bgInput,
                color: humanOnly ? t.textMuted : t.textPrimary,
              }}
            >
              <FileText size={11} />
              {humanOnly ? `只看人读的 · 已隐藏 ${hiddenCount} 个机读` : '显示全部(含 yaml)'}
            </button>
          </div>

          {/* 产物链：按 layer 分组，因为顺序本身是信息（原文 → 派生 → 定稿） */}
          <div style={{ flex: 1, minHeight: 0, overflow: 'auto', padding: '6px 6px 12px' }}>
            {/* 全局文档：不属于任何一份 JD，单独一组。浏览器是单 JD 作用域，
                所以标准目录不能混进"这份 JD 的产物"里。 */}
            {globals.length > 0 && (
              <div style={{ marginBottom: 8 }}>
                <div style={{ fontSize: 10, color: t.textMuted, padding: '0 8px 3px',
                              display: 'flex', alignItems: 'center', gap: 4 }}>
                  <Lock size={9} /> 全局 · 不属于任何一份 JD
                </div>
                {globals.filter((f) => humanOnly ? !MACHINE_RE.test(f.path) : true).map((f) => (
                  <button key={f.path} onClick={() => openRepoFile(f)}
                          title={f.note || ''}
                          style={rowStyle(activePath === f.path)}>
                    <FileText size={10} style={{ color: t.textMuted, flexShrink: 0 }} />
                    <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis',
                                   whiteSpace: 'nowrap' }}>{baseName(f.path)}</span>
                  </button>
                ))}
              </div>
            )}
            {error && (
              <div style={{ fontSize: 11, color: '#e5484d', padding: 8, whiteSpace: 'pre-wrap' }}>{error}</div>
            )}
            {!error && loading && jds.length === 0 && (
              <div style={{ fontSize: 11, color: t.textMuted, padding: 8 }}>正在读取产物清单…</div>
            )}
            {!error && !loading && jds.length === 0 && (
              <div style={{ fontSize: 11, color: '#e5484d', padding: 8 }}>
                接口返回了 0 份 JD。work/talent/jd_links/ 下应该有 10 个 .yaml。
              </div>
            )}
            {!error && current && files.length === 0 && (
              <div style={{ fontSize: 11, color: t.textMuted, padding: 8 }}>这份 JD 还没有任何产物。</div>
            )}

            {files.map((f, i) => {
              const active = activeJd === jd && activePath === f.path;
              const newLayer = i === 0 || files[i - 1].layer !== f.layer;
              return (
                <div key={f.path}>
                  {newLayer && (
                    <div style={{ fontSize: 10, letterSpacing: 0.3, color: t.textMuted,
                                  padding: '8px 8px 3px', textTransform: 'uppercase' }}>
                      {f.layer}
                    </div>
                  )}
                  <button
                    onClick={() => openRepoFile(f)}
                    title={f.writable ? f.note : f.readonly_reason}
                    style={rowStyle(active)}
                  >
                    <FileText size={11} style={{ opacity: 0.55, flexShrink: 0 }} />
                    <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {baseName(f.path)}
                    </span>
                    {!f.writable && <Lock size={10} style={{ marginLeft: 'auto', opacity: 0.7, flexShrink: 0 }} />}
                  </button>
                </div>
              );
            })}
          </div>

          <div style={{ padding: '6px 10px', fontSize: 10.5, color: t.textMuted,
                        borderTop: `1px solid ${t.border}`, flexShrink: 0, lineHeight: 1.5 }}>
            🔒 客户原文是只读锚点。其它产物保存时会自动跑逐字回查 + 门禁。
          </div>
        </>
      )}

      {/* ── Agent:它自己的工作区 ── */}
      {tab === 'agent' && (
        <>
          <div style={{ padding: '2px 10px 8px', fontSize: 10.5, color: t.textMuted,
                        borderBottom: `1px solid ${t.border}`, flexShrink: 0, lineHeight: 1.5 }}>
            agent {agentId}{agentName ? ` · ${agentName}` : ''} · <span style={{ color: '#f08c00' }}>只读</span>
          </div>

          <div style={{ flex: 1, minHeight: 0, overflow: 'auto', padding: '6px 6px 12px' }}>
            {agentErr && (
              <div style={{ fontSize: 10.5, color: '#e5484d', padding: 8, whiteSpace: 'pre-wrap' }}>
                读不到 agent 文件:{agentErr}
              </div>
            )}
            {!agentErr && agentFiles.length === 0 && (
              <div style={{ fontSize: 11, color: t.textMuted, padding: 8 }}>
                这个 agent 的工作区里还没有文件。
              </div>
            )}

            {(['upload', 'generated'] as const).map((dir) => {
              const list = byDir(dir);
              return (
                <div key={dir}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 10,
                                letterSpacing: 0.3, color: t.textMuted, padding: '8px 8px 3px',
                                textTransform: 'uppercase' }}>
                    {dir === 'upload' ? <Inbox size={10} /> : <Bot size={10} />}
                    {dir === 'upload' ? 'upload · 你交给它的' : 'generated · 它写出来的'}
                    <span style={{ marginLeft: 'auto', textTransform: 'none' }}>{list.length}</span>
                  </div>
                  {list.length === 0 && (
                    <div style={{ fontSize: 10.5, color: t.textMuted, padding: '2px 10px 4px', opacity: 0.7 }}>
                      （空）
                    </div>
                  )}
                  {list.map((f) => {
                    const active = activeTab?.data?.agentPath === f.path;
                    return (
                      <button
                        key={f.path}
                        onClick={() => openAgentFile(f)}
                        title={`${f.path} · ${f.bytes} B`}
                        style={rowStyle(active)}
                      >
                        <FileText size={11} style={{ opacity: 0.5, flexShrink: 0 }} />
                        <span style={{ whiteSpace: 'normal', wordBreak: 'break-all' }}>{f.name}</span>
                        <Lock size={10} style={{ marginLeft: 'auto', opacity: 0.6, flexShrink: 0 }} />
                      </button>
                    );
                  })}
                </div>
              );
            })}
          </div>

          <div style={{ padding: '6px 10px', fontSize: 10.5, color: t.textMuted,
                        borderTop: `1px solid ${t.border}`, flexShrink: 0, lineHeight: 1.5 }}>
            这些是 agent 写的**意见**。要成为正式产物，得由人抬进 jd_docs/（那条路上有回检 + 门禁）。
          </div>
        </>
      )}
    </div>
  );
}
