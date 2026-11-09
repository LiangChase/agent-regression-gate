export type Run = { run_id: string; status: string; created_at: string; started_at?: string; completed_at?: string; fail_on: string; case_count: number; summary: Record<string, number>; gate: Record<string, number | string>; error_message?: string };
export type Case = { id: string; name: string; description: string; risk_level: string; tags: string[]; turns: string[]; rules: { id: string; type: string; severity: string; description: string; params: Record<string, unknown> }[] };
export type Dashboard = { recent_runs: Run[]; run_count: number; active_runs: number; pass_rate: number | null; critical_failures: number; sut_revision?: string; statuses: Record<string, number> };
export type Baseline = { name: string; run_id: string; reason: string; saved_at: string; file_path: string };

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api${path}`, { ...init, headers: { ...(init?.body ? { "Content-Type": "application/json" } : {}), ...init?.headers }, cache: "no-store" });
  if (!response.ok) {
    let detail = `请求失败 (${response.status})`;
    try { const body = await response.json(); detail = body.detail || body.error || detail; } catch { /* use status */ }
    throw new Error(detail);
  }
  return response.json() as Promise<T>;
}

export const date = (value?: string) => value ? new Date(value).toLocaleString("zh-CN", { hour12: false }) : "—";
export const statusLabel: Record<string, string> = { queued: "排队中", running: "运行中", pass: "通过", fail: "未通过", error: "错误", incomplete: "不完整" };
