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
  path: string;
  jd: string;
  text: string;
  bytes: number;
  mtime: number;
  writable: boolean;
  readonly_reason: string;
}

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

export async function getTalentDoc(jd: string, path: string): Promise<DocPayload> {
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
