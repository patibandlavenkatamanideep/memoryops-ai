// Thin API client for the MemoryOps AI backend.
//
// This client carries NO identity. Every request goes to the same-origin BFF at
// /api/memoryops/*, which resolves tenant/user/role on the server (lib/identity.ts)
// and attaches them there.
//
// Previously this module exported hardcoded `DEMO_TENANT` / `DEMO_USER` constants
// and put them in the query string or body of every call, straight from the
// browser. That meant the tenant scope was client-controlled request data — anyone
// could edit it in devtools — and no credential was sent at all, so the official UI
// only worked against `MEMORYOPS_AUTH_MODE=none`, which the production profile
// refuses to run. The UI and the production security profile were mutually
// exclusive.
//
// Do not reintroduce a tenant_id/user_id argument here. The BFF strips any that
// arrive from the client (see app/api/memoryops/[...path]/route.ts); adding one
// back would be silently ignored at best and misleading at worst.

/** Same-origin BFF base. The upstream API URL is server-only. */
export const API_BASE = "/api/memoryops";

export type Decision =
  | "SAVE"
  | "PENDING_APPROVAL"
  | "BLOCK"
  | "DROP_LOW_UTILITY"
  | "MERGE_WITH_EXISTING"
  | "UPDATE_EXISTING";

export interface CandidateDecision {
  content: string;
  decision: Decision;
  type: string;
  confidence: number;
  importance: number;
  sensitivity: string;
  reason: string;
  memory_id?: string | null;
}

export interface ScoreBreakdown {
  vector_similarity: number;
  keyword_score: number;
  importance_score: number;
  confidence: number;
  recency: number;
  reinforcement: number;
}

export type RetrievalMode = "hybrid" | "fallback" | "none";

export interface UsedMemory {
  memory_id: string;
  content: string;
  memory_type?: string;
  score: number;
  score_breakdown?: Partial<ScoreBreakdown>;
  reason: string;
  source?: { kind: string; excerpt: string };
}

export interface ChatResponse {
  assistant_message: string;
  used_memories: UsedMemory[];
  candidate_memories: CandidateDecision[];
  audit_event_ids: string[];
  temporary_chat: boolean;
  retrieval_mode?: RetrievalMode;
  loop_evidence?: Record<string, string>;
  trace_id: string;
}

export interface MemoryRecord {
  id: string;
  tenant_id: string;
  user_id: string;
  memory_type: string;
  content: string;
  importance: number;
  confidence: number;
  sensitivity: string;
  status: string;
  source: { kind: string; excerpt: string };
  reinforcement_count: number;
  created_at: string;
  updated_at: string;
}

export interface AuditEvent {
  id: string;
  action: string;
  reason: string;
  memory_id?: string | null;
  user_id?: string | null;
  trace_id?: string | null;
  metadata?: Record<string, unknown>;
  created_at: string;
}

export interface MemoryProvenance {
  memory_id: string;
  source: { kind: string; excerpt: string; message_id?: string | null; conversation_id?: string | null };
  status: string;
  created_at: string;
  updated_at: string;
  reinforcement_count: number;
  importance: number;
  confidence: number;
  weight: number;
  audit_trail: AuditEvent[];
  loop_run_ids: string[];
}

export interface LoopDefinition {
  id: string;
  name: string;
  purpose: string;
  trigger: string;
  input_contract: string;
  output_contract: string;
  states: string[];
  policy_gates: string[];
  audit_events: string[];
  failure_modes: string[];
  fallback_behavior: string[];
  evidence_required: string[];
}

export interface LoopRun {
  id: string;
  loop_id: string;
  trace_id: string;
  tenant_id?: string | null;
  user_id?: string | null;
  status: string;
  started_at: string;
  ended_at?: string | null;
  metadata: Record<string, unknown>;
}

export interface LoopEvent {
  id: string;
  loop_run_id: string;
  loop_id: string;
  trace_id: string;
  state_from?: string | null;
  state_to: string;
  event_type: string;
  reason: string;
  evidence: Record<string, unknown>;
  audit_event_id?: string | null;
  created_at: string;
}

export interface LoopTrace {
  trace_id: string;
  runs: LoopRun[];
  events: LoopEvent[];
}

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function http<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { "content-type": "application/json" },
    cache: "no-store",
    credentials: "same-origin",
    ...init,
  });
  if (!res.ok) {
    // 401 = no session, 403 = role too low. Surfaced so the UI can route to
    // sign-in or show a permission message instead of a generic failure.
    throw new ApiError(res.status, `${res.status} ${res.statusText}`);
  }
  return res.json() as Promise<T>;
}

export const api = {
  chat: (message: string, temporary_chat = false) =>
    http<ChatResponse>("/api/chat", {
      method: "POST",
      body: JSON.stringify({ message, temporary_chat }),
    }),

  memories: (filters?: { status?: string; memory_type?: string }) => {
    const qs = new URLSearchParams();
    if (filters?.status) qs.set("status", filters.status);
    if (filters?.memory_type) qs.set("memory_type", filters.memory_type);
    return http<MemoryRecord[]>(`/api/memories?${qs.toString()}`);
  },

  memory: (id: string) => http<MemoryRecord>(`/api/memories/${id}`),

  memoryAudit: (id: string) => http<AuditEvent[]>(`/api/memories/${id}/audit`),

  memoryProvenance: (id: string) =>
    http<MemoryProvenance>(`/api/memories/${id}/provenance`),

  patchMemory: (id: string, patch: Record<string, unknown>) =>
    http<MemoryRecord>(`/api/memories/${id}`, {
      method: "PATCH",
      body: JSON.stringify(patch),
    }),

  deleteMemory: (id: string) =>
    http<{ id: string; status: string }>(`/api/memories/${id}`, {
      method: "DELETE",
    }),

  audit: () => http<AuditEvent[]>("/api/audit"),

  metrics: () =>
    http<{
      total_memories: number;
      by_status: Record<string, number>;
      audit_events: number;
      by_action: Record<string, number>;
      loops?: {
        total_runs: number;
        by_status: Record<string, number>;
        by_loop: Record<string, number>;
        failed: number;
        safe_degraded: number;
        most_common_failure_mode?: string | null;
      };
    }>("/api/metrics"),

  runEvals: () =>
    http<{
      total: number;
      passed: number;
      failed: number;
      pass_rate: number;
      loop_engineering?: Record<string, string>;
    }>("/api/evals/run", { method: "POST" }),

  loops: () => http<LoopDefinition[]>("/api/loops"),

  loopRuns: () => http<LoopRun[]>("/api/loops/runs"),

  loopEvents: () => http<LoopEvent[]>("/api/loops/events"),

  loopTrace: (traceId: string) => http<LoopTrace>(`/api/loops/trace/${traceId}`),

  ready: () =>
    http<{
      ready: boolean;
      storage: string;
      llm_provider: string;
      embeddings_provider: string;
      embedding_dim: number;
      degraded?: boolean;
      detail: string;
      checks?: Record<string, { status: string; reason_code?: string }>;
    }>("/readyz"),
};
