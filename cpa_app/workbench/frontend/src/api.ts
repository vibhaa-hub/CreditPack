// Typed client for the workbench API. The server enforces every rule; the UI only reflects it.
export type User = { username: string; display_name: string; roles: string[] };
export type Me = { user: User; roles: Record<string, string>; can: Record<string, boolean> };
export type Waiting = { role: string; item: string; tab: string };
export type CaseSummary = {
  sid: string; case_id: string | null; dealer: string; owner: string; stage: string;
  gate: string | null; run: string; waiting: Waiting[]; created: string | null; types: string[];
};
export type QueueItem = Waiting & { sid: string; case_id: string | null; dealer: string; stage: string };
export type Gap = { rule: string; result: string; reason: string; action: string; item?: string };
export type RegisterLine = { party: string; role: string; check: string; marker: string; status: string; reason: string | null; manual?: boolean };
export type Gate = {
  result: "PASS" | "ADVISORY" | "BLOCK"; deciding_rule: string; gaps: Gap[]; advisories: Gap[];
  completeness: { display: string; value: number | null }; mandatory_items: { complete: number; applicable: number };
  check_register: RegisterLine[]; policy_version: string; submission_may_be_authorised: boolean;
};
export type RunStatus = { state: string; workflow: string | null; error: string | null; agents_completed: string[]; events: number;
  waiting_on?: string | null; failed_step?: string | null };
export type Perm = { allowed: boolean; reason: string };
export type Pack = { id: number; version: number; sha256: string; created_at: string; created_by: string; reason: string };
export type Query = { id: number; text: string; raised_by: string; owner: string | null; status: string; resolution: string | null; raised_at: string };
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export type CaseState = Record<string, any>;
export type CaseDetail = {
  sid: string; state: CaseState; request_text: string | null; owner: string | null; gate: Gate | null;
  status: RunStatus; waiting: Waiting[]; prereq: Record<string, string>; permissions: Record<string, Perm>;
  diffs: Record<string, string>; packs: Pack[]; queries: Query[]; reconciliation?: ReconItem[];
};
export type ReconValue = { label: string; value: number | string; source: string | null };
export type ReconItem = { key: string; kind: string; severity: "BLOCK" | "ADVISORY"; period: string | null; field: string | null;
  description: string; values: ReconValue[]; difference: number | null; tolerance: string | null; action: string;
  explained: { explanation: string; by: string; date: string } | null };
export type AuditEvent = { seq: number; at: string; actor_type: string; actor: string; action: string; tool: string | null;
  result_status: string | null; detail: Record<string, unknown> | null };

export type Sample = { name: string; title: string; summary: string; documents: string[]; expect: string[] };

export class ApiError extends Error {
  constructor(public status: number, message: string, public hint = "") { super(message); }
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(path, { credentials: "same-origin", ...init });
  const body = await r.json().catch(() => ({}));
  if (!r.ok) throw new ApiError(r.status, body.error || r.statusText, body.action || "");
  return body as T;
}
const json = (method: string, data: unknown): RequestInit => ({
  method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(data),
});

export const api = {
  me: () => call<Me>("/api/me"),
  login: (username: string, password: string) => call<{ user: User }>("/api/login", json("POST", { username, password })),
  logout: () => call("/api/logout", { method: "POST" }),
  cases: () => call<{ cases: CaseSummary[] }>("/api/cases"),
  queue: () => call<{ items: QueueItem[] }>("/api/queue"),
  case: (sid: string) => call<CaseDetail>(`/api/cases/${sid}`),
  audit: (sid: string) => call<{ events: AuditEvent[]; chain: { ok: boolean; events: number; broken_at: number | null } }>(`/api/cases/${sid}/audit`),
  createCase: (form: FormData) => call<{ sid: string }>("/api/cases", { method: "POST", body: form }),
  upload: (sid: string, form: FormData) => call<{ message: string }>(`/api/cases/${sid}/upload`, { method: "POST", body: form }),
  run: (sid: string, workflow: string) => call<{ message: string }>(`/api/cases/${sid}/run/${workflow}`, { method: "POST" }),
  samples: () => call<{ samples: Sample[] }>("/api/samples"),
  openSample: (name: string) => call<{ sid: string }>(`/api/samples/${name}/open`, { method: "POST" }),
  act: (sid: string, action: string, body: Record<string, unknown>) =>
    call<{ message: string }>(`/api/cases/${sid}/act/${action}`, json("POST", body)),
};

export const fmtMoney = (v: unknown): string =>
  typeof v === "number" ? v.toLocaleString("en-GB", { maximumFractionDigits: 0 }) : v == null ? "" : String(v);
export const label = (s: string) => s.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());
