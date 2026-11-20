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
 */
import { useCallback, useRef, useState } from 'react';
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

export function useAgentTurn(agentId: number, projectId: number) {
  const [state, setState] = useState<AgentTurnState>({
    answer: '', tools: [], running: false, error: null,
  });
  const abortRef = useRef<AbortController | null>(null);

  const ask = useCallback(
    async (message: string) => {
      abortRef.current?.abort();
      const ctrl = new AbortController();
      abortRef.current = ctrl;
      setState({ answer: '', tools: [], running: true, error: null });

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
              setState((s) => ({ ...s, answer }));
            } else if (ev.type === 'tool_start') {
              const item: ToolEvent = {
                name: ev.tool_name || '?',
                input: ev.data?.input ?? {},
                at: Date.now(),
              };
              tools.push(item);
              setState((s) => ({ ...s, tools: [...tools] }));
            } else if (ev.type === 'tool_end') {
              const last = [...tools].reverse().find((t) => t.name === ev.tool_name && t.output === undefined);
              if (last) {
                last.output = typeof ev.data?.output === 'string'
                  ? ev.data.output
                  : JSON.stringify(ev.data?.output ?? '').slice(0, 4000);
                setState((s) => ({ ...s, tools: [...tools] }));
              }
            }
          }
        }
        setState((s) => ({ ...s, running: false }));
      } catch (err: any) {
        if (err?.name === 'AbortError') {
          setState((s) => ({ ...s, running: false }));
        } else {
          setState((s) => ({ ...s, running: false, error: String(err?.message || err) }));
        }
      }
    },
    [agentId, projectId],
  );

  const cancel = useCallback(() => {
    abortRef.current?.abort();
  }, []);

  return { ...state, ask, cancel };
}
