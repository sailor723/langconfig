/**
 * 当前选中的流水线 agent —— 一个模块级的小 store。
 *
 * 为什么需要共享:对话栏要按它选 agent,左轨的「agent 产物」段也要按它列出**那个** agent
 * 写出来的东西。两处各存一份,就会出现"对话问的是 391,左轨列的是 386 的产物"这种
 * 自相矛盾的画面 —— 而这正是最难查的 bug:两边都"正常工作"。
 *
 * 存 localStorage 是为了刷新后回到你刚才用的那步;读不到就退回起草 agent,不许因此崩。
 */
import { useCallback, useSyncExternalStore } from 'react';
import { TALENT_AGENT_ID } from './api';

const KEY = 'talent.agentId';

function load(): number {
  try {
    const raw = Number(window.localStorage.getItem(KEY));
    if (Number.isFinite(raw) && raw > 0) return raw;
  } catch {
    /* 隐私模式读不到 —— 用默认值 */
  }
  return TALENT_AGENT_ID;
}

let current: number = load();
const listeners = new Set<() => void>();

export function getTalentAgentId(): number {
  return current;
}

export function setTalentAgentId(id: number): void {
  if (!Number.isFinite(id) || id <= 0 || id === current) return;
  current = id;
  try { window.localStorage.setItem(KEY, String(id)); } catch { /* 存不下不是错误 */ }
  for (const l of listeners) l();
}

export function useTalentAgentId(): [number, (id: number) => void] {
  const id = useSyncExternalStore(
    useCallback((cb: () => void) => {
      listeners.add(cb);
      return () => { listeners.delete(cb); };
    }, []),
    () => current,
    () => current,
  );
  return [id, setTalentAgentId];
}
