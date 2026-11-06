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
 * The counts on the cards are read from the running workbench, never typed in.
 */
import { useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Boxes, ListTree, Play, RefreshCw, AlertTriangle, ShieldCheck, Loader2, Layers,
  Link2, Sigma, GitBranch, Gavel, Compass, CircleHelp, ArrowRight, Sparkles,
} from 'lucide-react';
import { useLayoutTokens } from '../components/layout2/tokens';
import { ontology, useOntology } from '../features/ontology/ontologyStore';

const CONCEPTS = [
  {
    icon: Layers,
    term: 'Objects',
    palantir: 'Object type',
    body: 'A thing the business talks about — a patient, an order, an appointment. Each object names its physical table and its primary key, including composite keys. 18 classes in the clinic ontology: 8 objects, 10 definitions.',
  },
  {
    icon: Link2,
    term: 'Links',
    palantir: 'Link type',
    body: 'A declared relationship, never an inferred one: the child’s foreign-key column plus the target it references. Drop the reference and a join is refused by name — the ontology refuses to guess a path between two tables.',
  },
  {
    icon: GitBranch,
    term: 'Definitions',
    palantir: 'Type / derived property',
    body: 'What a word MEANS, as an axiom: 已完成就诊 is an appointment whose status is "completed". A ratio’s denominator is written down once, so 拒赔率 cannot silently count pending claims as "not rejected".',
  },
  {
    icon: Sigma,
    term: 'Metrics',
    palantir: 'Function / metric',
    body: 'Meaning and computation live in separate files: the axiom says what a number is, the overlay says how it is computed (aggregate, grain, universe, where, group-by). A metric with a formula but no grain refuses — that is the whole point.',
  },
  {
    icon: Gavel,
    term: 'Actions',
    palantir: 'Action type',
    body: 'A declared write with compiled preconditions, a dry-run and an audit trail (lane C). Properties a write owns are marked as such, so nobody hand-edits state that an action is supposed to own.',
  },
  {
    icon: ShieldCheck,
    term: 'Guardrails + gates',
    palantir: 'Platform controls',
    body: 'Page cap, time bound, plan budget, statement timeout — enforced on every read. And gates that can go red: 41 checks on the clinic ontology, including five mutations that must each fail.',
  },
];

const STEPS = [
  {
    icon: ListTree,
    title: '1 · Browse what is declared',
    body: 'Open a profile and read its objects, definitions, links and metrics. Every metric shows the SQL compiled from its declaration — or the compiler’s refusal, in the compiler’s own words.',
  },
  {
    icon: Play,
    title: '2 · Ask in your own words',
    body: 'The workbench maps the question onto the menu (rules first, model only when unsure), compiles the metric, runs it under the guardrails, and shows the number with the SQL that produced it.',
  },
  {
    icon: Sigma,
    title: '3 · Add a metric, two ways',
    body: 'A sentence ("按城市看诊疗收入") or an uploaded declaration (.csv / .json / .ttl). Nothing is kept unless it compiles; a declaration that cannot is refused by name and the overlay is left untouched.',
  },
  {
    icon: Gavel,
    title: '4 · Read the refusals',
    body: 'What the ontology cannot answer is a deliverable: the refusal list is generated from the graph, and each item says what would have to be declared — a grain, a link, a threshold a human owns.',
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

  const card: React.CSSProperties = {
    background: t.bgInput,
    border: `1px solid ${t.border}`,
    borderRadius: 10,
    padding: '13px 15px',
    display: 'flex',
    flexDirection: 'column',
    gap: 7,
  };
  const h2 = (text: string, icon?: React.ReactNode) => (
    <div style={{ display: 'flex', alignItems: 'center', gap: 7, margin: '26px 0 10px' }}>
      {icon}
      <h2 style={{ margin: 0, fontSize: 13, fontWeight: 650, color: t.textPrimary, letterSpacing: 0.2 }}>
        {text}
      </h2>
    </div>
  );
  const stat = (label: string, value: React.ReactNode, dim = false) => (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
      <span style={{ fontSize: 16, fontWeight: 600, color: dim ? t.textMuted : t.textPrimary }}>{value}</span>
      <span style={{ fontSize: 9.5, textTransform: 'uppercase', letterSpacing: 0.5, color: t.textDim }}>{label}</span>
    </div>
  );

  return (
    <div style={{ height: '100%', overflowY: 'auto', padding: '22px 28px 48px' }}>
      {/* ── hero ─────────────────────────────────────────────────────────── */}
      <div style={{ display: 'flex', alignItems: 'flex-end', gap: 10, marginBottom: 6 }}>
        <Boxes size={20} color={t.accent} />
        <h1 style={{ margin: 0, fontSize: 20, fontWeight: 650, color: t.textPrimary }}>Ontology</h1>
        <button
          onClick={() => void ontology.probeAll()}
          style={{
            marginLeft: 'auto', display: 'inline-flex', alignItems: 'center', gap: 6,
            fontSize: 11.5, padding: '5px 10px', borderRadius: 999, cursor: 'pointer',
            border: `1px solid ${t.border}`, background: 'transparent', color: t.textMuted,
          }}
        >
          <RefreshCw size={11} /> re-probe
        </button>
      </div>

      <p style={{ margin: '0 0 6px', fontSize: 13, color: t.textMuted, maxWidth: 880, lineHeight: 1.7 }}>
        An <b>ontology</b> is the layer where a company’s data is described in its own words — objects,
        the links between them, and what each number means — so that every report, dashboard and agent
        computes from the same definitions instead of re-deriving them in SQL.
      </p>
      <p style={{ margin: '0 0 4px', fontSize: 12.5, color: t.textMuted, maxWidth: 880, lineHeight: 1.7 }}>
        This one goes further than a catalogue: the semantic layer is <b>compiled</b>. A metric is a
        declaration; the SQL is generated from it; a declaration that cannot compile is <b>refused by
        name</b> rather than approximated. That refusal — not the dashboard — is the deliverable.
      </p>
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', margin: '10px 0 4px' }}>
        {[
          'nouns → objects · links · properties',
          'verbs → definitions · metrics · actions',
          'numbers → compiled, never typed',
          'refusals → the backlog',
        ].map(chip => (
          <span
            key={chip}
            style={{
              fontSize: 10.5, padding: '2px 9px', borderRadius: 999,
              border: `1px solid ${t.border}`, color: t.textMuted,
              fontFamily: 'ui-monospace, Menlo, monospace',
            }}
          >
            {chip}
          </span>
        ))}
      </div>

      {/* ── the ontologies ──────────────────────────────────────────────── */}
      {h2('Ontologies available here', <Boxes size={13} color={t.accent} />)}
      <p style={{ margin: '0 0 10px', fontSize: 11.5, color: t.textDim, maxWidth: 860, lineHeight: 1.6 }}>
        Each card is one workbench profile — a server that loads one ontology folder and serves it.
        Counts come from that server right now; a profile that is not running is listed with the command
        that starts it. Which profiles appear is a setting (Settings → Ontology), not a hardcoded list.
      </p>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))', gap: 14 }}>
        {s.profiles.map(p => {
          const probe = s.probes[p.url];
          const up = probe?.status === 'up';
          const c = probe?.counts;
          const loading = probe?.status === 'unknown';
          return (
            <div key={p.key} style={{ ...card, opacity: up ? 1 : 0.92 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <span style={{ fontSize: 14, fontWeight: 650, color: t.textPrimary }}>{p.label}</span>
                <span
                  style={{
                    display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 10,
                    padding: '1px 7px', borderRadius: 999,
                    background: up ? '#e9f7f0' : loading ? '#fdf6e3' : '#fdecea',
                    color: up ? '#12805c' : loading ? '#8a6d3b' : '#b3261e',
                  }}
                >
                  {loading && <Loader2 size={9} className="animate-spin" />}
                  {up ? 'running' : loading ? 'probing' : 'not running'}
                </span>
              </div>
              <div style={{ fontSize: 10.5, color: t.textDim, fontFamily: 'ui-monospace, Menlo, monospace' }}>
                {p.url} · {p.profile}
              </div>
              <div style={{ fontSize: 11.5, color: t.textMuted, lineHeight: 1.5 }}>{p.note}</div>

              {up && c ? (
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: 6, marginTop: 2 }}>
                  {stat('objects', c.objects)}
                  {stat('definitions', c.definitions)}
                  {stat('links', c.links)}
                  {stat('metrics', c.metrics)}
                  {stat('refused', c.refused, c.refused > 0)}
                </div>
              ) : (
                <div style={{ fontSize: 11, color: '#b3261e', display: 'flex', gap: 5, alignItems: 'flex-start' }}>
                  <AlertTriangle size={12} style={{ flex: 'none', marginTop: 2 }} />
                  <span>
                    {probe?.error || 'probing…'}
                    <br />
                    <code style={{ fontFamily: 'ui-monospace, Menlo, monospace', fontSize: 10 }}>
                      {`serve_ui.py --settings ${p.profile || '<profile>'} --port ${new URL(p.url).port}`}
                    </code>
                  </span>
                </div>
              )}

              <div style={{ display: 'flex', gap: 8, marginTop: 'auto', paddingTop: 4 }}>
                <button
                  disabled={!up}
                  onClick={() => void openProfile(p.key, p.url, 'browse')}
                  style={{
                    display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 11.5,
                    padding: '6px 11px', borderRadius: 7, cursor: up ? 'pointer' : 'default',
                    border: 'none', background: up ? t.accent : t.border,
                    color: up ? '#fff' : t.textDim, opacity: up ? 1 : 0.7,
                  }}
                >
                  <ListTree size={12} /> Browse
                </button>
                <button
                  disabled={!up}
                  onClick={() => void openProfile(p.key, p.url, 'app')}
                  style={{
                    display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 11.5,
                    padding: '6px 11px', borderRadius: 7, cursor: up ? 'pointer' : 'default',
                    border: `1px solid ${t.border}`, background: 'transparent',
                    color: up ? t.textMuted : t.textDim,
                  }}
                >
                  <Play size={12} /> Ask
                </button>
              </div>
            </div>
          );
        })}
      </div>

      {/* ── what is inside ──────────────────────────────────────────────── */}
      {h2('What is inside an ontology', <Layers size={13} color={t.accent} />)}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: 12 }}>
        {CONCEPTS.map(({ icon: Icon, term, palantir, body }) => (
          <div key={term} style={card}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 7 }}>
              <Icon size={13} color={t.accent} />
              <span style={{ fontSize: 12.5, fontWeight: 650, color: t.textPrimary }}>{term}</span>
              <span
                style={{
                  marginLeft: 'auto', fontSize: 9.5, padding: '1px 7px', borderRadius: 999,
                  border: `1px solid ${t.border}`, color: t.textDim,
                }}
              >
                Palantir · {palantir}
              </span>
            </div>
            <div style={{ fontSize: 11.5, color: t.textMuted, lineHeight: 1.6 }}>{body}</div>
          </div>
        ))}
      </div>

      {/* ── how to use ──────────────────────────────────────────────────── */}
      {h2('How to use it', <Compass size={13} color={t.accent} />)}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(300px, 1fr))', gap: 12 }}>
        {STEPS.map(({ icon: Icon, title, body }) => (
          <div key={title} style={{ ...card, background: t.bgTabBar }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 7 }}>
              <Icon size={13} color={t.accent} />
              <span style={{ fontSize: 12, fontWeight: 650, color: t.textPrimary }}>{title}</span>
            </div>
            <div style={{ fontSize: 11.5, color: t.textMuted, lineHeight: 1.6 }}>{body}</div>
          </div>
        ))}
      </div>

      {/* ── Palantir vocabulary ─────────────────────────────────────────── */}
      {h2('Vocabulary — Foundry ↔ here', <Sparkles size={13} color={t.accent} />)}
      <div style={{ border: `1px solid ${t.border}`, borderRadius: 10, overflow: 'hidden', maxWidth: 900 }}>
        {[
          ['Object type', 'Object — a class with :physicalTable and :primaryKey'],
          ['Property type', 'Property — a data property with :physicalColumn and a label in the user’s words'],
          ['Link type', 'Link — :physicalColumn + :references on the child row; a join is never inferred'],
          ['Type / derived property / rule', 'Definition — an owl:equivalentClass axiom (intersection / union / hasValue) or the one :physicalPredicate escape hatch'],
          ['Function / metric', 'Metric — meaning in 02-meaning.ttl, computation in metrics_ext.ttl; compiled to SQL, or refused by name'],
          ['Action type', 'Declared action — compiled preconditions, dry-run, audit trail (lane C)'],
          ['Platform controls', 'Guardrails (page cap · time bound · plan budget · statement timeout) plus gates that can go red'],
          ['AIP / agents', 'A DeepAgent with the build-ontology-from-db skill: it introspects a database and writes the declarations; the workbench compiles them'],
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
      </div>

      {/* ── footer ──────────────────────────────────────────────────────── */}
      <div
        style={{
          marginTop: 22, padding: '12px 14px', borderRadius: 9,
          border: `1px solid ${t.border}`, background: t.bgTabBar,
          fontSize: 11.5, color: t.textMuted, lineHeight: 1.7, maxWidth: 900,
          display: 'flex', gap: 8, alignItems: 'flex-start',
        }}
      >
        <ShieldCheck size={14} color={t.accent} style={{ flex: 'none', marginTop: 2 }} />
        <span>
          Every number the workbench serves is computed by SQL compiled from a declaration and run
          under the guardrails. The browser shows the other half: what is <i>declared</i>, which
          metrics compile, and which refuse. A gate that cannot fail is decoration — so the clinic
          ontology’s suite includes five mutations (delete a grain, drop a reference, misspell a
          formula column, duplicate a column, remove an axiom) that each have to turn it red.
          <br />
          <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5, marginTop: 8, color: t.accent }}>
            <CircleHelp size={12} /> Settings → Ontology decides which profiles exist here.
            <ArrowRight size={12} />
          </span>
        </span>
      </div>
    </div>
  );
}
