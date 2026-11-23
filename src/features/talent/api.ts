/**
 * Talent API client — the four endpoints behind the JD/CV document editor.
 *
 * Why a separate module instead of apiClient methods: this surface is small, typed
 * here, and its write path has rules the rest of the client has no business knowing
 * (the server refuses certain paths outright — see api/talent/routes.py). Keeping it
 * in one file means "which files may be written" is answerable by reading one place.
 */
import { API_BASE_URL } from '../../config/api';

const BASE = `${API_BASE_URL}/api/talent`;

export interface TalentFile {
  path: string;
  layer: string;
  exists: boolean;
  bytes: number;
  mtime: number | null;
  /** Server-decided. The editor must not allow typing into a readonly file. */
  writable: boolean;
  readonly_reason: string;
  note: string;
}

export interface TalentJd {
  jd: string;
  files: TalentFile[];
  existing: number;
}

export interface ValidationResult {
  jd: string;
  verify: { ok: boolean; status: string; lines: string[] };
  /** `summary` is the gate's `N checks · M failed` line; empty means it never finished. */
  gate: { ok: boolean; summary: string; lines: string[] };
  ok: boolean;
}

export interface DocPayload {
  kind: 'text';
  path: string;
  jd: string;
  name?: string;
  ext?: string;
  text: string;
  bytes: number;
  mtime: number;
  writable: boolean;
  readonly_reason: string;
}

/** 有格式的产物(docx/pdf/图片/html):不让后端正文本读,交给查看器取原始字节。 */
export interface DocBinaryPayload {
  kind: 'binary';
  path: string;
  jd: string;
  name: string;
  ext: string;
  bytes: number;
  mtime: number;
  writable: boolean;
  readonly_reason: string;
  url: string;
  media_type: string;
  viewer: 'pdf' | 'office' | 'image' | 'html' | 'other';
}

export type TalentDoc = DocPayload | DocBinaryPayload;

async function jsonFetch<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...(init?.headers || {}) },
  });
  const body = await res.text();
  let parsed: any = null;
  try {
    parsed = body ? JSON.parse(body) : null;
  } catch {
    parsed = null;
  }
  if (!res.ok) {
    const detail = parsed?.detail || parsed?.message || body.slice(0, 300) || res.statusText;
    throw new Error(`${res.status}: ${detail}`);
  }
  return (parsed ?? ({} as T)) as T;
}

export async function listTalentDocs(): Promise<{ jds: TalentJd[] }> {
  return jsonFetch(`${BASE}/docs`);
}

export async function getTalentDoc(jd: string, path: string): Promise<TalentDoc> {
  const q = new URLSearchParams({ jd, path });
  return jsonFetch(`${BASE}/doc?${q.toString()}`);
}

export async function saveTalentDoc(
  jd: string,
  path: string,
  text: string,
  expectedMtime?: number | null,
): Promise<{ saved: boolean; validate?: ValidationResult; audit?: any; reason?: string }> {
  return jsonFetch(`${BASE}/doc`, {
    method: 'PUT',
    body: JSON.stringify({ jd, path, text, expected_mtime: expectedMtime ?? null }),
  });
}

export async function validateTalentJd(jd: string): Promise<ValidationResult> {
  const q = new URLSearchParams({ jd });
  return jsonFetch(`${BASE}/validate?${q.toString()}`, { method: 'POST' });
}

// ── agent 产物(只读)──────────────────────────────────────────
// 左轨的产物链读的是仓库 work/talent/**;而 agent 用 write_file 写的报告落在
// **它自己的工作区** generated/ 下。两棵树,所以"它写了什么"必须单独列一段。
// 这一段**只读** —— 写这条路永远只走上面的白名单。

/**
 * 默认/兜底 agent。历史上是步 1 的起草 agent(386),它已于 2026-11-20 退休
 * (名字改成 `[已退休] Talent · 1 JD 起草`,不再出现在下拉框里)。
 * 这里保留它作为**兜底**:localStorage 里没存过选择时用它,而不是让对话栏空着 ——
 * 一个退休但还能用的 agent,比一个不知道是谁的空白框好。
 */
export const TALENT_AGENT_ID = 386;

export interface AgentFile {
  name: string;
  /** 相对 agent 工作区根,形如 `generated/xxx.md` */
  path: string;
  /** `upload` 或 `generated` —— 左轨按它分组:一个是你给它的,一个是它写的 */
  dir: 'upload' | 'generated';
  ext: string;
  bytes: number;
  mtime: number;
}

export interface AgentFiles {
  agent: { id: number; name: string };
  workspace: string;
  dirs: string[];
  files: AgentFile[];
}

/** `agent-file` 的三种返回。判定在服务端做一次,前端只按 kind 选渲染器。 */
export type AgentFileContent =
  | { kind: 'text'; path: string; name: string; ext: string; bytes: number; mtime: number; text: string }
  | { kind: 'converted'; path: string; name: string; ext: string; bytes: number; mtime: number;
      text: string; converter: string }
  | { kind: 'binary'; path: string; name: string; ext: string; bytes: number; mtime: number;
      url: string; media_type: string;
      /** 服务端已经判好该用哪个查看器(含"老 .doc 已转成 .docx"这种情况) —— 前端不再自己猜 */
      viewer?: 'pdf' | 'office' | 'image' | 'html' | 'other';
      /** 老格式转换来的,原后缀为 .doc/.ppt/.xls */
      converted_from?: string };

function agentQuery(agentId: number, projectId?: number): string {
  const q = new URLSearchParams({ agent_id: String(agentId) });
  if (projectId != null) q.set('project_id', String(projectId));
  return q.toString();
}

export async function listAgentFiles(agentId: number, projectId?: number): Promise<AgentFiles> {
  return jsonFetch(`${BASE}/agent-files?${agentQuery(agentId, projectId)}`);
}

export async function getAgentFile(
  agentId: number, path: string, projectId?: number,
): Promise<AgentFileContent> {
  const q = new URLSearchParams({ agent_id: String(agentId), path });
  if (projectId != null) q.set('project_id', String(projectId));
  return jsonFetch(`${BASE}/agent-file?${q.toString()}`);
}

/** 直接把 `binary` 那类文件交给浏览器查看器用(<img src>、PdfViewer、OfficeViewer)。 */
export function agentRawUrl(agentId: number, path: string, projectId?: number): string {
  const q = new URLSearchParams({ agent_id: String(agentId), path });
  if (projectId != null) q.set('project_id', String(projectId));
  return `${BASE}/agent-raw?${q.toString()}`;
}

// ── 流水线里的 agent 清单 ─────────────────────────────────────
// 复用已有的 `GET /api/deepagents/`,不另开接口:**成员资格和顺序只该有一处定义**。
// 判据是名字前缀("Talent · N …"),它由 seed_talent_agents.py 建立 —— 所以新加一步只要
// 按这个命名 seed 进来,下拉框自动多一项。

export interface TalentAgent {
  id: number;
  /** 下拉框里显示的名字(去掉公共前缀) */
  label: string;
  /** 全名,提示里用 */
  name: string;
  description: string;
  step: number;
}

/** `Talent · 4a 一面收数据` → 42(4 + 'a'),`Talent · 2 …` → 20。用来按流水线顺序排。 */
function stepRank(name: string): number {
  const m = name.match(/^Talent\s*·\s*(\d+)\s*([a-z]?)/i);
  if (!m) return 9999;
  return Number(m[1]) * 10 + (m[2] ? m[2].toLowerCase().charCodeAt(0) - 96 : 0);
}

export async function listTalentAgents(): Promise<TalentAgent[]> {
  const raw: any = await jsonFetch(`${API_BASE_URL}/api/deepagents/?public_only=false`);
  const rows: any[] = Array.isArray(raw) ? raw : (raw?.data ?? raw?.agents ?? []);
  return rows
    .filter((r) => typeof r?.name === 'string' && r.name.startsWith('Talent · '))
    .map((r) => ({
      id: Number(r.id),
      label: r.name.replace(/^Talent\s*·\s*/, ''),
      name: r.name,
      description: r.description || '',
      step: stepRank(r.name),
    }))
    .sort((a, b) => a.step - b.step);
}

export interface RunStepResult {
  jd: string;
  step: string;
  seconds: number;
  /** 只有门禁最后一行是绿的时候才算成功 —— 没有汇总行就是没跑完。 */
  ok: boolean;
  gate: string;
  steps: { module: string; status: string; exit: number | null; lines: string[] }[];
}

/** 跑一步流程(白名单:5 = 名单→选人→判定说明→CV清单→门禁;4 = 代拟→重渲染→待核)。 */
export async function runTalentStep(jd: string, step = '5'): Promise<RunStepResult> {
  const r = await fetch(`${BASE}/run`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify({ jd, step }),
  });
  if (!r.ok) throw new Error((await r.text()).slice(0, 200) || `HTTP ${r.status}`);
  return r.json();
}
