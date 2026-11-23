/**
 * useAgentTurn — one streaming turn against an agent, with the tool trace kept.
 *
 * Why not reuse the chat page's controller: that one is bound to the Chat activity's
 * global state (active project, open conversation, side panels). Here the agent is
 * fixed by the document view, there is no conversation history UI, and what matters
 * is the **tool trace** — for this pipeline, "which script did it run" is the answer
 * to "is it telling me something it actually checked".
 *
 * The stream contract (`POST /api/chat/message/stream`, SSE `data: {json}`) is the
 * same one the chat page uses; only the consumer differs.
 *
 * **状态为什么放在模块级 store 里,而不是组件内 useState**：Tab 之间切换时 Workspace 只渲染
 * 当前 tab,那个视图会被卸载 —— 对话、工具轨迹、正在跑的流全部跟着没。实测症状很具体:
 * 打开 agent 的报告看它写了什么,回头对话就空了,而且还在跑的那一轮被静默丢掉。
 * 一个对话面板不该因为"看了一眼别的文件"就失忆,所以状态按 `<agentId>:<projectId>` 落在
 * 模块里,组件只是订阅者。
 */
import { useCallback, useMemo, useSyncExternalStore } from 'react';
import { API_BASE_URL } from '../../config/api';

export interface ToolEvent {
  name: string;
  input: any;
  output?: string;
  at: number;
}

export interface AgentTurnState {
  answer: string;
  tools: ToolEvent[];
  running: boolean;
  error: string | null;
}

const EMPTY: AgentTurnState = { answer: '', tools: [], running: false, error: null };

interface Store {
  state: AgentTurnState;
  listeners: Set<() => void>;
  /** 正在进行的请求。放这里而不是 ref 里,组件卸载时它不该被连带丢掉。 */
  ctrl: AbortController | null;
}

const STORES = new Map<string, Store>();

function getStore(key: string): Store {
  let s = STORES.get(key);
  if (!s) {
    s = { state: EMPTY, listeners: new Set(), ctrl: null };
    STORES.set(key, s);
  }
  return s;
}

function emit(store: Store, patch: Partial<AgentTurnState>): void {
  store.state = { ...store.state, ...patch };
  for (const l of store.listeners) l();
}

export function useAgentTurn(agentId: number, projectId: number) {
  const key = `${agentId}:${projectId}`;
  const store = useMemo(() => getStore(key), [key]);

  const state = useSyncExternalStore(
    useCallback((cb: () => void) => {
      store.listeners.add(cb);
      return () => { store.listeners.delete(cb); };
    }, [store]),
    useCallback(() => store.state, [store]),
    useCallback(() => store.state, [store]),
  );

  const ask = useCallback(
    async (message: string) => {
      store.ctrl?.abort();
      const ctrl = new AbortController();
      store.ctrl = ctrl;
      emit(store, { answer: '', tools: [], running: true, error: null });

      try {
        const start = await fetch(`${API_BASE_URL}/api/chat/start`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ agent_id: agentId, project_id: projectId }),
        });
        if (!start.ok) throw new Error(`chat/start ${start.status}: ${await start.text()}`);
        const session = await start.json();

        const res = await fetch(`${API_BASE_URL}/api/chat/message/stream`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            session_id: session.session_id,
            message,
            project_id: projectId,
          }),
          signal: ctrl.signal,
        });
        if (!res.ok || !res.body) throw new Error(`stream ${res.status}`);

        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';
        let answer = '';
        const tools: ToolEvent[] = [];

        for (;;) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split('\n');
          buffer = lines.pop() || '';
          for (const raw of lines) {
            const line = raw.trim();
            if (!line.startsWith('data: ')) continue;
            let ev: any;
            try {
              ev = JSON.parse(line.slice(6));
            } catch {
              continue;
            }
            if (ev.type === 'chunk') {
              answer += ev.content || '';
              emit(store, { answer });
            } else if (ev.type === 'tool_start') {
              const item: ToolEvent = {
                name: ev.tool_name || '?',
                input: ev.data?.input ?? {},
                at: Date.now(),
              };
              tools.push(item);
              emit(store, { tools: [...tools] });
            } else if (ev.type === 'tool_end') {
              const last = [...tools].reverse().find((t) => t.name === ev.tool_name && t.output === undefined);
              if (last) {
                last.output = typeof ev.data?.output === 'string'
                  ? ev.data.output
                  : JSON.stringify(ev.data?.output ?? '').slice(0, 4000);
                emit(store, { tools: [...tools] });
              }
            }
          }
        }
        emit(store, { running: false });
      } catch (err: any) {
        if (err?.name === 'AbortError') {
          emit(store, { running: false });
        } else {
          emit(store, { running: false, error: String(err?.message || err) });
        }
      } finally {
        if (store.ctrl === ctrl) store.ctrl = null;
      }
    },
    [agentId, projectId, store],
  );

  const cancel = useCallback(() => {
    store.ctrl?.abort();
  }, [store]);

  return { ...state, ask, cancel };
}
