/**
 * contentStore — lightweight in-memory store for tab content.
 *
 * Why this exists instead of using tab.data:
 * When a user closes and reopens a tab, the old Tab object is gone.
 * This store persists content across reopen cycles during a session.
 */
const store = new Map<string, string>();

export function getContent(id: string): string | undefined {
  return store.get(id);
}

export function setContent(id: string, content: string): void {
  store.set(id, content);
}

export function deleteContent(id: string): void {
  store.delete(id);
}

export function hasContent(id: string): boolean {
  return store.has(id);
}
