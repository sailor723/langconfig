/**
 * Skill categories — the Skills activity's taxonomy, in one place.
 *
 * The Tools activity already organises itself by `category` (13 values in the database, a sidebar row per
 * category with a count, clickable category badges on the cards, and a category tab that lists them). The
 * Skills activity grouped by `source_type` only — Builtin vs My Skills — which was fine at 44 skills and
 * useless at 110.
 *
 * The rules live in `skill-categories.rules.json` rather than here, because a Python test
 * (`backend/tests/test_skill_categories.py`) has to map the same skills through the same rules and fail
 * when a new skill arrives without a category. Two copies of a taxonomy is how the two surfaces drift.
 *
 * Order of resolution, applied by {@link categoryForSkill}:
 *   1. a declared prefix (`lc-…` → `ecosystem`) — provenance beats topic;
 *   2. an explicit override for the skill id — the honest list, one line per skill;
 *   3. a tag match, for a skill nobody has categorised yet;
 *   4. `other`.
 */
import rules from './skill-categories.rules.json';

export interface SkillCategory {
  id: string;
  label: string;
  blurb: string;
}

/** Categories in display order. */
export const SKILL_CATEGORIES: SkillCategory[] = rules.categories;

const BY_ID: Record<string, string> = rules.overrides as Record<string, string>;
const PREFIXES: Array<[string, string]> = Object.entries(rules.rules.prefix as Record<string, string>);

/** Tag → category, used only when no override names the skill. */
const TAG_RULES: Array<[string, string]> = [
  ['ontology', 'ontology'], ['semantic-layer', 'ontology'],
  ['data-analysis', 'data'], ['sql', 'data'], ['pandas', 'data'], ['csv', 'data'],
  ['langgraph', 'ecosystem'], ['langchain', 'ecosystem'], ['deepagents', 'ecosystem'],
  ['testing', 'quality'], ['review', 'quality'], ['security', 'quality'], ['debugging', 'quality'],
  ['requirements', 'requirements'], ['planning', 'requirements'], ['tickets', 'requirements'],
  ['research', 'research'], ['web-search', 'research'],
  ['writing', 'documents'], ['documentation', 'documents'], ['presentation', 'documents'],
  ['agents', 'agents'], ['skills', 'agents'], ['tools', 'agents'],
];

export interface CategorisableSkill {
  skill_id?: string;
  tags?: string[] | null;
  source_type?: string | null;
}

/** Which category a skill belongs to. Never throws: an unknown skill lands in `other`, and a test says so. */
export function categoryForSkill(skill: CategorisableSkill): string {
  const id = String(skill.skill_id ?? '');
  for (const [prefix, category] of PREFIXES) {
    if (id.startsWith(prefix)) return category;
  }
  if (BY_ID[id]) return BY_ID[id];
  for (const [tag, category] of TAG_RULES) {
    if ((skill.tags ?? []).some(t => String(t).toLowerCase() === tag)) return category;
  }
  return 'other';
}

/** The label a reader sees, falling back to the id so a new category is never blank. */
export function categoryLabel(category: string): string {
  return SKILL_CATEGORIES.find(c => c.id === category)?.label ?? category;
}
