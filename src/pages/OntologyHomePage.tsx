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
import {
  PageShell, Hero, Section, Card, Stat, Chip, Btn, Quiet, StatusDot,
  SUCCESS, DANGER, WARN, VIOLET, CYAN, INFO,
} from '../features/ontology/ui';

const CONCEPTS = [
  {
    icon: Layers,
    term: 'Objects',
    colour: INFO,
    palantir: 'Object type',
    body: 'A thing the business talks about — a patient, an order, an appointment. Each object names its physical table and its primary key, including composite keys. 18 classes in the clinic ontology: 8 objects, 10 definitions.',
  },
  {
    icon: Link2,
    term: 'Links',
    colour: CYAN,
    palantir: 'Link type',
    body: 'A declared relationship, never an inferred one: the child’s foreign-key column plus the target it references. Drop the reference and a join is refused by name — the ontology refuses to guess a path between two tables.',
  },
  {
    icon: GitBranch,
    term: 'Definitions',
    colour: VIOLET,
    palantir: 'Type / derived property',
    body: 'What a word MEANS, as an axiom: 已完成就诊 is an appointment whose status is "completed". A ratio’s denominator is written down once, so 拒赔率 cannot silently count pending claims as "not rejected".',
  },
  {
    icon: Sigma,
    term: 'Metrics',
    colour: SUCCESS,
    palantir: 'Function / metric',
    body: 'Meaning and computation live in separate files: the axiom says what a number is, the overlay says how it is computed (aggregate, grain, universe, where, group-by). A metric with a formula but no grain refuses — that is the whole point.',
  },
  {
    icon: Gavel,
    term: 'Actions',
    colour: WARN,
    palantir: 'Action type',
    body: 'A declared write with compiled preconditions, a dry-run and an audit trail (lane C). Properties a write owns are marked as such, so nobody hand-edits state that an action is supposed to own.',
  },
  {
    icon: ShieldCheck,
    term: 'Guardrails + gates',
    colour: DANGER,
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

  return (
    <PageShell>
      <Hero
        icon={Boxes}
        title="Ontology"
        subtitle="the semantic layer, compiled — objects, definitions and metrics one number at a time"
        actions={
          <Btn onClick={() => void ontology.probeAll()} title="re-probe every workbench">
            <RefreshCw size={13} /> re-probe
          </Btn>
        }
      >
        <p style={{ fontSize: 14, color: t.textPrimary, lineHeight: 1.8, margin: '0 0 8px', maxWidth: 760 }}>
          An <b>ontology</b> is the layer where a company's data is described in its own words — objects,
          the links between them, and what each number means — so every report, dashboard and agent
          computes from the same definitions instead of re-deriving them in SQL.
        </p>
        <p style={{ fontSize: 13, color: t.textMuted, lineHeight: 1.7, margin: 0, maxWidth: 760 }}>
          This one goes further than a catalogue: the semantic layer is <b>compiled</b>. A metric is a
          declaration; the SQL is generated from it; a declaration that cannot compile is <b>refused by
          name</b> rather than approximated. That refusal — not the dashboard — is the deliverable.
        </p>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginTop: 14 }}>
          {[
            'nouns → objects · links · properties',
            'verbs → definitions · metrics · actions',
            'numbers → compiled, never typed',
            'refusals → the backlog',
          ].map(chip => <Chip key={chip}>{chip}</Chip>)}
        </div>
      </Hero>

      <Section
        title="Ontologies available here"
        hint={`${s.profiles.length} profile${s.profiles.length === 1 ? '' : 's'} · counts read live`}
      >
      <Quiet>
        Each card is one workbench profile — a server that loads one ontology folder and serves it. A
        profile that is not running is listed with the command that starts it. Which profiles appear is
        a setting (Settings → Ontology), not a hardcoded list.
      </Quiet>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(330px, 1fr))', gap: 14, marginTop: 12 }}>
        {s.profiles.map(p => {
          const probe = s.probes[p.url];
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
                  {up ? 'running' : loading ? 'probing' : 'not running'}
                </Chip>
              </div>
              {/* The address is an implementation detail: the backend starts the server.
                  What a reader needs is which profile is loaded. */}
              <div style={{ fontSize: 11.5, color: t.textDim, fontFamily: 'ui-monospace, Menlo, monospace' }}>
                {p.profile || p.key}
              </div>
              <div style={{ fontSize: 12.5, color: t.textMuted, lineHeight: 1.6 }}>{p.note}</div>

              {up && c ? (
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: 6, marginTop: 2 }}>
                  <Stat label="objects" value={c.objects} />
                  <Stat label="definitions" value={c.definitions} />
                  <Stat label="links" value={c.links} />
                  <Stat label="metrics" value={c.metrics} />
                  <Stat label="refused" value={c.refused} tone={c.refused > 0 ? DANGER : undefined} />
                </div>
              ) : (
                <div style={{ fontSize: 12, color: DANGER, display: 'flex', gap: 6, alignItems: 'flex-start' }}>
                  <AlertTriangle size={13} style={{ flex: 'none', marginTop: 2 }} />
                  <span style={{ lineHeight: 1.6 }}>
                    {s.starting ? 'starting the workbench…' : (probe?.error || 'not running')}
                    <br />
                    <span style={{ color: t.textMuted, fontSize: 11.5 }}>
                      the app starts a workbench for this profile on demand — if it stays down,
                      check Settings → Ontology (repo path and interpreter).
                    </span>
                  </span>
                </div>
              )}

              <div style={{ display: 'flex', gap: 8, marginTop: 'auto', paddingTop: 6 }}>
                <Btn variant="primary" disabled={!up} onClick={() => void openProfile(p.key, p.url, 'browse')}>
                  <ListTree size={13} /> Browse
                </Btn>
                <Btn disabled={!up} onClick={() => void openProfile(p.key, p.url, 'app')} title="open the workbench">
                  <Play size={13} /> Open
                </Btn>
              </div>
            </Card>
          );
        })}
      </div>
      </Section>

      <Section title="What is inside an ontology">
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

      <Section title="How to use it">
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

      <Section title="Vocabulary — Foundry ↔ here" hint="the same ideas, two names">
      <Card style={{ padding: 0, overflow: 'hidden', maxWidth: 940 }}>
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
      </Card>
      </Section>

      <Card style={{ maxWidth: 940, display: 'flex', gap: 10, alignItems: 'flex-start' }}>
        <ShieldCheck size={16} color={t.accent} style={{ flex: 'none', marginTop: 2 }} />
        <div style={{ fontSize: 12.5, color: t.textMuted, lineHeight: 1.75 }}>
          Every number the workbench serves is computed by SQL compiled from a declaration and run
          under the guardrails. The browser shows the other half: what is <i>declared</i>, which
          metrics compile, and which refuse. A gate that cannot fail is decoration — so the clinic
          ontology’s suite includes five mutations (delete a grain, drop a reference, misspell a
          formula column, duplicate a column, remove an axiom) that each have to turn it red.
          <div style={{ display: 'inline-flex', alignItems: 'center', gap: 6, marginTop: 10, color: t.accent, fontSize: 12.5 }}>
            <CircleHelp size={13} /> Settings → Ontology decides which profiles exist here.
            <ArrowRight size={13} />
          </div>
        </div>
      </Card>
    </PageShell>
  );
}
