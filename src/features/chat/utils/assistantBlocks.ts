/**
 * Assistant content as an ordered block list — the shape DSH (deepseek-harness)
 * uses, not the per-session state this app had.
 *
 * Why the rewrite: LangConfig kept the three things a turn produces in three
 * *global* pieces of state (`activeToolCalls`, `customEvents`, `thinkingBuffer`),
 * cleared only when the stream reported `complete`. Measured consequences:
 *
 *  - the pre-tool narration was appended to `thinkingBufferRef` **and** to the
 *    answer text, so the "Thinking" panel printed the answer a second time;
 *  - a turn that ended without `complete` (HITL interrupt, error, stop) kept its
 *    tool calls, so the next turn's panel showed the old steps *plus* the new
 *    ones — "thinking appended to all thinking";
 *  - nothing tied a tool call to the message that made it, so history could only
 *    show a session-wide pile.
 *
 * DSH's model instead gives every assistant step one array of blocks in arrival
 * order — `reasoning`, `text`, `tool-call` — and the UI renders that array. State
 * for a turn is the message's own blocks, so it cannot leak into the next turn.
 * See `packages/client/runtime/src/client/sessions/conversation.ts` in the
 * harness (`AssistantBlock`, `toAssistantBlocks`) and the reducer in
 * `packages/client/ui-conversation/src/client/conversation-nodes/assistant.ts`.
 *
 * Deliberate difference: DSH interleaves every block in the transcript. Here the
 * text blocks still feed `message.content` (the existing markdown renderer), and
 * reasoning + tool blocks render in the collapsible panel of *that* message. Same
 * data, smaller blast radius; the interleaved render is a later step.
 */

export type ToolCallStatus = 'running' | 'completed' | 'failed';

export interface ReasoningBlock {
  kind: 'reasoning';
  text: string;
}

export interface TextBlock {
  kind: 'text';
  text: string;
}

export interface ToolCallBlock {
  kind: 'tool-call';
  /** Wire id when the stream supplies one; falls back to the tool name. */
  callId: string;
  name: string;
  argsRaw: string;
  status: ToolCallStatus;
  result?: string;
}

export type AssistantBlock = ReasoningBlock | TextBlock | ToolCallBlock;

/** A fresh, empty transcript entry for one assistant turn. */
export function emptyBlocks(): AssistantBlock[] {
  return [];
}

/**
 * Append a reasoning delta: continues the trailing reasoning block, or starts one.
 *
 * Deliberately *not* merged into the text block — that merge is exactly the
 * duplication this model exists to remove.
 */
export function appendReasoning(blocks: AssistantBlock[], delta: string): AssistantBlock[] {
  if (!delta) return blocks;
  const last = blocks[blocks.length - 1];
  if (last?.kind === 'reasoning') {
    return [...blocks.slice(0, -1), { kind: 'reasoning', text: last.text + delta }];
  }
  return [...blocks, { kind: 'reasoning', text: delta }];
}

/** Append answer text: continues the trailing text block, or starts one. */
export function appendText(blocks: AssistantBlock[], delta: string): AssistantBlock[] {
  if (!delta) return blocks;
  const last = blocks[blocks.length - 1];
  if (last?.kind === 'text') {
    return [...blocks.slice(0, -1), { kind: 'text', text: last.text + delta }];
  }
  return [...blocks, { kind: 'text', text: delta }];
}

/** Record a tool call starting. */
export function startToolCall(
  blocks: AssistantBlock[],
  call: { name: string; args?: unknown; callId?: string },
): AssistantBlock[] {
  return [...blocks, {
    kind: 'tool-call',
    callId: call.callId || call.name,
    name: call.name,
    argsRaw: serializeArgs(call.args),
    status: 'running',
  }];
}

/**
 * Record a tool call finishing.
 *
 * Matched by `callId` when the stream gives one, otherwise by name against the
 * last still-running call — agents legitimately call the same tool twice, so the
 * name alone must not update the wrong (already finished) one.
 */
export function finishToolCall(
  blocks: AssistantBlock[],
  result: { name: string; callId?: string; output?: string; status?: ToolCallStatus },
): AssistantBlock[] {
  const status = result.status || 'completed';
  let index = -1;
  for (let i = blocks.length - 1; i >= 0; i -= 1) {
    const block = blocks[i];
    if (block.kind !== 'tool-call') continue;
    if (result.callId && block.callId !== result.callId) continue;
    if (!result.callId && block.name !== result.name) continue;
    if (block.status !== 'running') continue;
    index = i;
    break;
  }
  if (index === -1) return blocks;
  const block = blocks[index] as ToolCallBlock;
  const next = [...blocks];
  next[index] = { ...block, status, result: result.output ?? block.result };
  return next;
}

/** Everything the reader should see as prose, in block order. */
export function blocksToText(blocks: AssistantBlock[]): string {
  return blocks
    .filter((b): b is TextBlock => b.kind === 'text')
    .map((b) => b.text)
    .join('');
}

/** How many tool calls this turn made (the panel's step count). */
export function countToolCalls(blocks: AssistantBlock[]): number {
  return blocks.filter((b) => b.kind === 'tool-call').length;
}

/** True while any tool call of this turn is still running. */
export function hasRunningToolCall(blocks: AssistantBlock[]): boolean {
  return blocks.some((b) => b.kind === 'tool-call' && b.status === 'running');
}

function serializeArgs(args: unknown): string {
  if (args === undefined || args === null) return '';
  if (typeof args === 'string') return args;
  try {
    return JSON.stringify(args);
  } catch {
    return String(args);
  }
}
