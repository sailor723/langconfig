/**
 * Shared constants for DeepAgent Creator and Editor components.
 *
 * Keeps SECTIONS and SectionId in a single source of truth so that
 * adding/removing a section only requires updating one file.
 */
import type { ReactNode } from 'react';
import { Info, FileText, Wrench, Award, Users, Layers, Shield, Code, BookOpen, Network, Database } from 'lucide-react';

export type SectionId = 'overview' | 'prompt' | 'tools' | 'skills' | 'langgraph' | 'subagents' | 'middleware' | 'guardrails' | 'database' | 'docs' | 'json';

export const SECTIONS: { id: SectionId; label: string; icon: ReactNode }[] = [
  { id: 'overview',   label: 'Overview',   icon: <Info size={13} /> },
  { id: 'prompt',     label: 'Prompt',     icon: <FileText size={13} /> },
  { id: 'tools',      label: 'Tools',      icon: <Wrench size={13} /> },
  { id: 'skills',     label: 'Skills',     icon: <Award size={13} /> },
  // A code-defined LangGraph graph can BE the agent (see backend/langgraph/assigned.py).
  // It sits beside the other capability sections because choosing a graph replaces
  // prompt/tools/skills — they do not compose with it.
  { id: 'langgraph',  label: 'LangGraph',  icon: <Network size={13} /> },
  { id: 'subagents',  label: 'Subagents',  icon: <Users size={13} /> },
  { id: 'middleware', label: 'Middleware', icon: <Layers size={13} /> },
  { id: 'guardrails', label: 'Guardrails', icon: <Shield size={13} /> },
  // Where THIS agent's database is. Agent-level, not the global catalogue: a database two agents share
  // belongs in Settings → Databases, a database only this agent should touch belongs here.
  { id: 'database',   label: 'Database',   icon: <Database size={13} /> },
  { id: 'docs',       label: 'Docs',       icon: <BookOpen size={13} /> },
  { id: 'json',       label: 'JSON',       icon: <Code size={13} /> },
];
