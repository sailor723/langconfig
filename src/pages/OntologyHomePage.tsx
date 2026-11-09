/**
 * OntologyHomePage — what an ontology is, what is in it, how to use it, and which ones are
 * running right now.
 *
 * The framing is Palantir Foundry's, because that is the model this repo implements: an
 * ontology is a **semantic layer** (object types, properties, link types, the definitions
 * that decide membership) plus a **kinetic layer** (validated, audited actions), with
 * functions/rules and AI agents on top. What is different here is that the semantic layer
 * is *compiled*: a metric is a declaration, the SQL is generated from it, and a declaration
 * that cannot compile is refused by name instead of being approximated.
 *
 * The counts on the cards are compiled from the ontology's declarations by the app itself, never typed in.
 */
import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Boxes, ListTree, Play, RefreshCw, AlertTriangle, ShieldCheck, Loader2, Layers, Link2, Sigma, GitBranch, Gavel, Compass, CircleHelp, ArrowRight, Sparkles } from 'lucide-react';
import { useLayoutTokens } from '../components/layout2/tokens';
import { ontology, useOntology } from '../features/ontology/ontologyStore';
import BuildOntologyDialog from '../features/ontology/BuildOntologyDialog';
import {
  PageShell, Hero, Section, Card, Stat, Chip, Btn, Quiet, StatusDot,
  SUCCESS, DANGER, WARN, VIOLET, CYAN, INFO,
} from '../features/ontology/ui';

const CONCEPTS = [
  {
    icon: Layers,
    term: '对象',
    colour: INFO,
    palantir: 'Object type',
    body: '业务嘴里说的那个「东西」——一位病人、一张订单、一次预约。每个对象都写明它落在哪张物理表、主键是什么（复合主键也行）。诊所本体里有 18 个类：8 个对象、10 个定义。',
  },
  {
    icon: Link2,
    term: '关联',
    colour: CYAN,
    palantir: 'Link type',
    body: '关系必须声明，绝不推测：子表上的外键列 + 它指向哪张表。把这条引用删掉，join 就会被按名拒绝——本体宁可拒绝，也不猜两张表之间的路径。',
  },
  {
    icon: GitBranch,
    term: '定义',
    colour: VIOLET,
    palantir: 'Type / derived property',
    body: '一个词「是什么意思」，写成公理：「已完成就诊」= 状态为 "completed" 的就诊。比率的分子分母只写一次，所以「拒赔率」不会偷偷把待判定算成「未拒赔」。',
  },
  {
    icon: Sigma,
    term: '指标',
    colour: SUCCESS,
    palantir: 'Function / metric',
    body: '「意思」和「怎么算」分两个文件：公理说这个数是什么，计算层说它怎么算（聚合、粒度、范围、where、分组）。有公式却没有粒度的指标会被拒绝——这正是重点。',
  },
  {
    icon: Gavel,
    term: '动作',
    colour: WARN,
    palantir: 'Action type',
    body: '声明的写入：前置条件编译出来、可干跑、有审计留痕（lane C）。被写入拥有的属性会被标出来，免得有人手改本该由动作拥有的状态。',
  },
  {
    icon: ShieldCheck,
    term: '护栏与门禁',
    colour: DANGER,
    palantir: 'Platform controls',
    body: '行数上限、时间窗、计划行数预算、语句超时——每一次读都要过。还有会变红的门禁：诊所本体 41 项检查，其中 5 个「必须失败」的变异测试。',
  },
];

const STEPS = [
  {
    icon: ListTree,
    title: '1 · 先看它声明了什么',
    body: '打开一个本体，读它的对象、定义、关联和指标。每条指标都会显示由声明编译出来的 SQL——或者编译器按名给出的拒绝理由（用编译器自己的话）。',
  },
  {
    icon: Play,
    title: '2 · 用自己的话提问',
    body: '问题先映射到指标菜单（规则优先，规则不确定才用模型），然后编译、过护栏执行，并连同产生它的 SQL 一起显示。',
  },
  {
    icon: Sigma,
    title: '3 · 加指标的两条路',
    body: '一句话（「按城市看诊疗收入」）或上传一份声明（.csv / .json / .ttl）。编译不过就不留：按名拒绝，覆盖层保持原样。',
  },
  {
    icon: Gavel,
    title: '4 · 读拒绝清单',
    body: '本体答不了什么是交付物：拒绝清单从图里生成，每一条都说清还缺哪条声明——粒度、关联，还是必须由人给出的阈值。',
  },
];

export default function OntologyHomePage() {
  const t = useLayoutTokens();
  const navigate = useNavigate();
  const s = useOntology();

  useEffect(() => {
    void (async () => {
      await ontology.ensureReady();
      void ontology.probeAll();
    })();
  }, []);

  const openProfile = async (key: string, url: string, where: 'browse' | 'app') => {
    await ontology.select(url, key);
    navigate(where === 'browse' ? '/ontology/browse' : '/ontology/app');
  };

  const [buildOpen, setBuildOpen] = useState(false);

  return (
    <PageShell>
      {buildOpen && (
        <BuildOntologyDialog
          ontologyKey={ontology.get().preset ?? ''}
          onClose={() => setBuildOpen(false)}
          onLanded={() => void ontology.probeAll()}
        />
      )}
      <Hero
        icon={Boxes}
        title="本体"
        subtitle="把语义层编译出来——对象、定义、指标，一个数字一个数字地算"
        actions={
          <>
            <Btn onClick={() => void ontology.probeAll()} title="重新编译每个本体，并报告它声明了什么">
              <RefreshCw size={13} /> 重新编译
            </Btn>
            {/* Measured: the Build entry existed only on /ontology/browse, inside the tab bar, and
                only once an ontology compiled — so "generate an ontology with an agent" was
                unreachable for exactly the people who do not know the browse URL. It is here too. */}
            <Btn onClick={() => setBuildOpen(true)} title="用 agent 生成或重建一个本体（后台任务）">
              <Sparkles size={13} /> 生成…
            </Btn>
          </>
        }
      >
        <p style={{ fontSize: 14, color: t.textPrimary, lineHeight: 1.8, margin: '0 0 8px', maxWidth: 760 }}>
          <b>本体</b>是「用公司自己的话描述它的数据」的那一层——有哪些对象、它们之间怎么关联、每个数字是什么意思。
          于是报表、看板、agent 都从同一份定义出发，而不是各自在 SQL 里重新推导一遍。
        </p>
        <p style={{ fontSize: 13, color: t.textMuted, lineHeight: 1.7, margin: 0, maxWidth: 760 }}>
          这里比「目录」更进一步：语义层是<b>编译出来的</b>。一条指标就是一份声明，SQL 由它生成；
          编译不过的声明会被<b>按名拒绝</b>，而不是糊成一个近似值。那份拒绝清单——而不是看板——才是交付物。
        </p>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginTop: 14 }}>
          {[
            '名词 → 对象 · 关联 · 属性',
            '动词 → 定义 · 指标 · 动作',
            '数字 → 编译出来，不是手打',
            '拒绝 → 待办清单',
          ].map(chip => <Chip key={chip}>{chip}</Chip>)}
        </div>
      </Hero>

      <Section
        title="这里可用的本体"
        hint={`${s.profiles.length} 个本体 · 计数实时读取`}
      >
      <Quiet>
        每张卡是一个本体——它的声明由这个应用在本进程里编译。答不出来的卡会说出编译器拒绝了什么；
        不需要先启动任何服务。出现哪些本体是一个设置（Settings → 本体），不是写死的清单。
      </Quiet>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(330px, 1fr))', gap: 14, marginTop: 12 }}>
        {s.profiles.map(p => {
          const probe = s.probes[p.key];     // keyed by ontology, not by a url that is '' for all of them
          const up = probe?.status === 'up';
          const c = probe?.counts;
          const loading = probe?.status === 'unknown';
          return (
            <Card key={p.key} style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <StatusDot up={up} reason={probe?.error} />
                <span style={{ fontSize: 14, fontWeight: 600, color: t.textPrimary }}>{p.label}</span>
                <Chip colour={up ? SUCCESS : loading ? WARN : DANGER}>
                  {loading && <Loader2 size={10} className="animate-spin" />}
                  {up ? '已声明' : loading ? '编译中' : '被拒绝'}
                </Chip>
              </div>
              {/* The address is an implementation detail: the app compiles the profile in place.
                  What a reader needs is which ontology is loaded. */}
              <div style={{ fontSize: 11.5, color: t.textDim, fontFamily: 'ui-monospace, Menlo, monospace' }}>
                {p.profile || p.key}
              </div>
              {/* WHEN this ontology last published — from the ledger, not from a file mtime: the file
                  moves on any edit, the publish is the event a reader is actually asking about. */}
              <div style={{ fontSize: 11.5, color: t.textMuted }}>
                {p.publishedAt
                  ? `发布 ${new Date(p.publishedAt).toLocaleString()}${p.publishedBy ? ` · ${p.publishedBy}` : ''}`
                  : '未发布（还没有一次 apply 落到这个本体上）'}
              </div>
              <div style={{ fontSize: 12.5, color: t.textMuted, lineHeight: 1.6 }}>{p.note}</div>

              {up && c ? (
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: 6, marginTop: 2 }}>
                  <Stat label="对象" value={c.objects} />
                  <Stat label="定义" value={c.definitions} />
                  <Stat label="关联" value={c.links} />
                  <Stat label="指标" value={c.metrics} />
                  <Stat label="拒绝" value={c.refused} tone={c.refused > 0 ? DANGER : undefined} />
                </div>
              ) : (
                <div style={{ fontSize: 12, color: DANGER, display: 'flex', gap: 6, alignItems: 'flex-start' }}>
                  <AlertTriangle size={13} style={{ flex: 'none', marginTop: 2 }} />
                  <span style={{ lineHeight: 1.6 }}>
                    {s.starting ? '编译中…' : (probe?.error || '没有应答')}
                    <br />
                    <span style={{ color: t.textMuted, fontSize: 11.5 }}>
                      这个应用在进程里编译本体：如果它拒绝，上面那句就是编译器自己说的话——
                      它点名的那条声明就是要修的地方。
                    </span>
                  </span>
                </div>
              )}

              <div style={{ display: 'flex', gap: 8, marginTop: 'auto', paddingTop: 6 }}>
                <Btn variant="primary" disabled={!up} onClick={() => void openProfile(p.key, p.url, 'browse')}>
                  <ListTree size={13} /> 浏览
                </Btn>
                {/* "Open" read as "open a new window". It actually opens this ontology's sections
                    inside this app, so the label says what you get. */}
                <Btn
                  disabled={!up}
                  onClick={() => void openProfile(p.key, p.url, 'app')}
                  title="这个本体的各个板块——图谱、查询、动作、教程——由本应用编译，在这个窗口里打开"
                >
                  <Play size={13} /> 打开
                </Btn>
              </div>
            </Card>
          );
        })}
      </div>
      </Section>

      <Section title="本体里有什么">
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(290px, 1fr))', gap: 12 }}>
          {CONCEPTS.map(({ icon: Icon, term, palantir, body, colour }) => (
            <Card key={term} style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <div
                  style={{
                    width: 28, height: 28, borderRadius: 7, display: 'flex', alignItems: 'center',
                    justifyContent: 'center', background: `${colour}22`, color: colour, flex: 'none',
                  }}
                >
                  <Icon size={14} />
                </div>
                <span style={{ fontSize: 13.5, fontWeight: 600, color: t.textPrimary }}>{term}</span>
                <span style={{ marginLeft: 'auto', fontSize: 11, color: t.textDim, whiteSpace: 'nowrap' }}>
                  {palantir}
                </span>
              </div>
              <div style={{ fontSize: 12.5, color: t.textMuted, lineHeight: 1.65 }}>{body}</div>
            </Card>
          ))}
        </div>
      </Section>

      <Section title="怎么用">
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(300px, 1fr))', gap: 12 }}>
          {STEPS.map(({ icon: Icon, title, body }) => (
            <Card key={title} style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <div
                  style={{
                    width: 28, height: 28, borderRadius: 7, display: 'flex', alignItems: 'center',
                    justifyContent: 'center', background: `${t.accent}22`, color: t.accent, flex: 'none',
                  }}
                >
                  <Icon size={14} />
                </div>
                <span style={{ fontSize: 13, fontWeight: 600, color: t.textPrimary }}>{title}</span>
              </div>
              <div style={{ fontSize: 12.5, color: t.textMuted, lineHeight: 1.65 }}>{body}</div>
            </Card>
          ))}
        </div>
      </Section>

      <Section title="术语对照：Foundry ↔ 这里" hint="同一批概念，两个名字">
      <Card style={{ padding: 0, overflow: 'hidden', maxWidth: 940 }}>
        {[
          ['Object type', '对象——带 :physicalTable 与 :primaryKey 的类'],
          ['Property type', '属性——带 :physicalColumn 的数据属性，标签用用户自己的说法'],
          ['Link type', '关联——子行上的 :physicalColumn + :references；join 从不推测'],
          ['Type / derived property / rule', '定义——owl:equivalentClass 公理（交集 / 并集 / hasValue），或唯一那个 :physicalPredicate 逃生口'],
          ['Function / metric', '指标——意思写在 02-meaning.ttl，算法写在 metrics_ext.ttl；编译成 SQL，否则按名拒绝'],
          ['Action type', '声明的动作——前置条件编译、可干跑、有审计留痕（lane C）'],
          ['Platform controls', '护栏（行数上限 · 时间窗 · 计划预算 · 语句超时）加上会变红的门禁'],
          ['AIP / agents', '带 build-ontology-from-db 技能的 DeepAgent：它读库、写声明，应用负责编译'],
        ].map(([foundry, here], i) => (
          <div
            key={foundry}
            style={{
              display: 'grid', gridTemplateColumns: '220px 1fr', gap: 10,
              padding: '7px 12px', fontSize: 11.5,
              borderTop: i === 0 ? 'none' : `1px solid ${t.border}`,
              background: i % 2 ? t.bgTabBar : 'transparent',
            }}
          >
            <span style={{ color: t.textDim, fontFamily: 'ui-monospace, Menlo, monospace', fontSize: 11 }}>{foundry}</span>
            <span style={{ color: t.textPrimary, lineHeight: 1.55 }}>{here}</span>
          </div>
        ))}
      </Card>
      </Section>

      <Card style={{ maxWidth: 940, display: 'flex', gap: 10, alignItems: 'flex-start' }}>
        <ShieldCheck size={16} color={t.accent} style={{ flex: 'none', marginTop: 2 }} />
        <div style={{ fontSize: 12.5, color: t.textMuted, lineHeight: 1.75 }}>
          这里显示的每个数字，都是「由声明编译出的 SQL」在护栏下跑出来的。浏览器展示另一半：
          到底<i>声明</i>了什么、哪些指标编译得过、哪些被拒绝。不会变红的门禁只是装饰——所以诊所本体的
          检查里有五个变异测试（删掉粒度、删掉引用、拼错公式列、重复一列、去掉一条公理），每一个都必须让它变红。
          <div style={{ display: 'inline-flex', alignItems: 'center', gap: 6, marginTop: 10, color: t.accent, fontSize: 12.5 }}>
            <CircleHelp size={13} /> 这里出现哪些本体，由 Settings → 本体 决定。
            <ArrowRight size={13} />
          </div>
        </div>
      </Card>
    </PageShell>
  );
}
