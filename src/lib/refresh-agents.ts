/**
 * Module-level refresh mechanism for agent lists.
 *
 * Bypasses React context/event complexity by storing a function pointer
 * at the module level. DeepAgentHomePage registers its loadTemplates ref
 * on mount, and LeftSidebar calls it directly on refresh click.
 * When DeepAgentHomePage is unmounted, the pointer is null.
 */

type RefreshFn = () => void;
let _refresh: RefreshFn | null = null;

export function setRefreshAgents(fn: RefreshFn | null) {
  _refresh = fn;
}

export function triggerRefreshAgents() {
  _refresh?.();
}
