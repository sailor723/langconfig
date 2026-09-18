/**
 * Shared constants for DeepAgent Creator and Editor components.
 *
 * Keeps SECTIONS and SectionId in a single source of truth so that
 * adding/removing a section only requires updating one file.
 */
import type { ReactNode } from 'react';
import { Info, FileText, Wrench, Award, Users, Layers, Shield, Code, BookOpen } from 'lucide-react';

export type SectionId = 'overview' | 'prompt' | 'tools' | 'skills' | 'subagents' | 'middleware' | 'guardrails' | 'docs' | 'json';

export const SECTIONS: { id: SectionId; label: string; icon: ReactNode }[] = [
  { id: 'overview',   label: 'Overview',   icon: <Info size={13} /> },
  { id: 'prompt',     label: 'Prompt',     icon: <FileText size={13} /> },
  { id: 'tools',      label: 'Tools',      icon: <Wrench size={13} /> },
  { id: 'skills',     label: 'Skills',     icon: <Award size={13} /> },
  { id: 'subagents',  label: 'Subagents',  icon: <Users size={13} /> },
  { id: 'middleware', label: 'Middleware', icon: <Layers size={13} /> },
  { id: 'guardrails', label: 'Guardrails', icon: <Shield size={13} /> },
  { id: 'docs',       label: 'Docs',       icon: <BookOpen size={13} /> },
  { id: 'json',       label: 'JSON',       icon: <Code size={13} /> },
];
