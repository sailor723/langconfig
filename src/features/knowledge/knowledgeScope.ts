/**
 * The knowledge scope: which knowledge base, and which folder inside it.
 *
 * One selection, shared by the Knowledge sidebar and Doc Chat. It used to be two — a base chosen
 * in the sidebar and a folder chosen in the chat panel — which could disagree, and did: the chat
 * answered from a different folder than the one being browsed.
 *
 * The list comes from `GET /api/doc-chat/folders`, the endpoint doc chat itself reads through.
 * That matters more than it looks: it returns only folders holding files doc chat can actually
 * read, so every option in the dropdown can answer a question. Listing the raw directory tree
 * instead offered folders that were guaranteed to come back "No supported documents found" —
 * `.docx` and `.pptx` are not chat-able, however many of them a folder holds.
 *
 * Labels are the FULL prettified path, not the leaf name: a `<select>` only ever shows the
 * selected option's text, so "business_model" alone does not say which base or parent it is in,
 * and there are several.
 */
import { useCallback, useEffect, useMemo, useState } from 'react';

import { listDocChatFolders } from '../../lib/api-doc-chat';
import { useLayoutState } from '../../components/layout2/useLayout';

export interface ScopeOption {
  /** Full path from the knowledge root, e.g. "langconfig-test/eyewear_industry". */
  path: string;
  /** The knowledge base the scope sits in — the first segment, the folder that has a catalog. */
  base: string;
  /** The folder inside that base. '' is the base itself. */
  folder: string;
  /** What to show. Readable, and complete enough to tell two same-named folders apart. */
  label: string;
}

/** Split a scope path into the knowledge base and the folder inside it. */
export function splitScope(path: string): { base: string; folder: string } {
  const [base, ...rest] = path.split('/');
  return { base, folder: rest.join('/') };
}

/** A path as a person reads it: `eyewear_industry/新溢眼镜` -> `eyewear industry / 新溢眼镜`. */
export function prettyPath(path: string): string {
  return path.replace(/_/g, ' ').replace(/\//g, ' / ');
}

/** How the current scope reads as a value: the base, then the folder inside it. */
export function scopeDisplayName(base: string, folder: string): string {
  if (!base) return '';
  return folder ? `${base} / ${prettyPath(folder)}` : base;
}

/** The option label. Kept as a function so the shape of a scope stays in one place. */
export function scopeOptionLabel(option: ScopeOption): string {
  return option.label;
}

/**
 * The current scope and the list to pick it from.
 *
 * Reads and writes the shared selection, so every panel that shows a scope shows the same one.
 */
export function useKnowledgeScope() {
  const { knowledgeBase, knowledgeFolder, setKnowledgeBase, setKnowledgeFolder } = useLayoutState();
  const [folders, setFolders] = useState<string[]>([]);

  // The folders inside the current base that doc chat can read from, at every depth.
  useEffect(() => {
    if (!knowledgeBase) {
      setFolders([]);
      return;
    }
    let alive = true;
    listDocChatFolders(knowledgeBase).then((found) => { if (alive) setFolders(found); });
    return () => { alive = false; };
  }, [knowledgeBase]);

  const options = useMemo<ScopeOption[]>(() => {
    if (!knowledgeBase) return [];
    return [
      // The knowledge base itself: its documents sit at its root, which is a real scope and the
      // only one there is for a base whose files were uploaded flat.
      { path: knowledgeBase, base: knowledgeBase, folder: '', label: knowledgeBase },
      ...folders.map((folder) => ({
        path: `${knowledgeBase}/${folder}`,
        base: knowledgeBase,
        folder,
        label: prettyPath(folder),
      })),
    ];
  }, [knowledgeBase, folders]);

  const setScope = useCallback((path: string) => {
    const { base, folder } = splitScope(path);
    setKnowledgeBase(base);
    setKnowledgeFolder(folder);
  }, [setKnowledgeBase, setKnowledgeFolder]);

  return {
    options,
    setScope,
    base: knowledgeBase,
    folder: knowledgeFolder,
    /** The current scope as one path, e.g. "langconfig-test/eyewear_industry". */
    scope: knowledgeFolder ? `${knowledgeBase}/${knowledgeFolder}` : knowledgeBase,
  };
}
