// Thin API client for the MemoryOps AI backend.

export const API_URL =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

// Demo identity. In production these come from auth/session.
export const DEMO_TENANT = "tenant_demo";
export const DEMO_USER = "user_demo";

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

async function http<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    headers: { "content-type": "application/json" },
    cache: "no-store",
    ...init,
  });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json() as Promise<T>;
}

export const api = {
  chat: (message: string, temporary_chat = false) =>
    http<ChatResponse>("/api/chat", {
      method: "POST",
      body: JSON.stringify({
        tenant_id: DEMO_TENANT,
        user_id: DEMO_USER,
        message,
        temporary_chat,
      }),
    }),

  memories: (filters?: { status?: string; memory_type?: string }) => {
    const qs = new URLSearchParams({ tenant_id: DEMO_TENANT, user_id: DEMO_USER });
    if (filters?.status) qs.set("status", filters.status);
    if (filters?.memory_type) qs.set("memory_type", filters.memory_type);
    return http<MemoryRecord[]>(`/api/memories?${qs.toString()}`);
  },

  memory: (id: string) =>
    http<MemoryRecord>(
      `/api/memories/${id}?tenant_id=${DEMO_TENANT}&user_id=${DEMO_USER}`
    ),

  memoryAudit: (id: string) =>
    http<AuditEvent[]>(
      `/api/memories/${id}/audit?tenant_id=${DEMO_TENANT}&user_id=${DEMO_USER}`
    ),

  memoryProvenance: (id: string) =>
    http<MemoryProvenance>(
      `/api/memories/${id}/provenance?tenant_id=${DEMO_TENANT}&user_id=${DEMO_USER}`
    ),

  patchMemory: (id: string, patch: Record<string, unknown>) =>
    http<MemoryRecord>(`/api/memories/${id}`, {
      method: "PATCH",
      body: JSON.stringify({ tenant_id: DEMO_TENANT, user_id: DEMO_USER, ...patch }),
    }),

  deleteMemory: (id: string) =>
    http<{ id: string; status: string }>(`/api/memories/${id}`, {
      method: "DELETE",
      body: JSON.stringify({ tenant_id: DEMO_TENANT, user_id: DEMO_USER }),
    }),

  audit: () => http<AuditEvent[]>(`/api/audit?tenant_id=${DEMO_TENANT}`),

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
    }>(`/api/metrics?tenant_id=${DEMO_TENANT}`),

  runEvals: () =>
    http<{
      total: number;
      passed: number;
      failed: number;
      pass_rate: number;
      loop_engineering?: Record<string, string>;
    }>("/api/evals/run", { method: "POST" }),

  loops: () => http<LoopDefinition[]>("/api/loops"),

  loopRuns: () => http<LoopRun[]>(`/api/loops/runs?tenant_id=${DEMO_TENANT}`),

  loopEvents: () => http<LoopEvent[]>("/api/loops/events"),

  loopTrace: (traceId: string) => http<LoopTrace>(`/api/loops/trace/${traceId}`),

  ready: () =>
    http<{
      ready: boolean;
      storage: string;
      llm_provider: string;
      embeddings_provider: string;
      embedding_dim: number;
      detail: string;
    }>("/readyz"),
};
