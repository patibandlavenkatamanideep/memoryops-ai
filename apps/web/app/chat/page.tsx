"use client";

import { useState } from "react";
import { api, ChatResponse } from "@/lib/api";

const decisionColor: Record<string, string> = {
  SAVE: "border-emerald-600 text-emerald-400",
  UPDATE_EXISTING: "border-emerald-600 text-emerald-400",
  PENDING_APPROVAL: "border-amber-600 text-amber-400",
  BLOCK: "border-rose-600 text-rose-400",
  DROP_LOW_UTILITY: "border-slate-600 text-slate-400",
  MERGE_WITH_EXISTING: "border-emerald-600 text-emerald-400",
};

interface Turn {
  user: string;
  resp: ChatResponse;
}

export default function ChatPage() {
  const [message, setMessage] = useState("");
  const [temporary, setTemporary] = useState(false);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function send() {
    if (!message.trim()) return;
    setLoading(true);
    setError("");
    try {
      const resp = await api.chat(message, temporary);
      setTurns((t) => [{ user: message, resp }, ...t]);
      setMessage("");
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-white">Chat</h1>
        <label className="flex items-center gap-2 text-sm text-slate-400">
          <input
            type="checkbox"
            checked={temporary}
            onChange={(e) => setTemporary(e.target.checked)}
          />
          Temporary chat (no memory)
        </label>
      </div>

      <div className="card space-y-3">
        <textarea
          className="w-full rounded-lg border border-slate-700 bg-ink p-3 text-sm"
          rows={3}
          placeholder="Try: Remember that I prefer enterprise-style explanations with no emojis."
          value={message}
          onChange={(e) => setMessage(e.target.value)}
        />
        <div className="flex items-center gap-3">
          <button className="btn" onClick={send} disabled={loading}>
            {loading ? "Sending…" : "Send"}
          </button>
          {error && <span className="text-sm text-rose-400">{error}</span>}
        </div>
      </div>

      <div className="space-y-4">
        {turns.map((t, i) => (
          <div key={i} className="card space-y-3">
            <p className="text-sm text-slate-400">
              <span className="font-semibold text-white">You:</span> {t.user}
            </p>
            <p className="text-sm">
              <span className="font-semibold text-accent">Assistant:</span>{" "}
              {t.resp.assistant_message}
            </p>

            {t.resp.temporary_chat && (
              <span className="chip border-amber-600 text-amber-400">
                temporary — no memory written or read
              </span>
            )}

            {!t.resp.temporary_chat && t.resp.retrieval_mode && (
              <span
                className={`chip ${
                  t.resp.retrieval_mode === "hybrid"
                    ? "border-accent text-accent"
                    : t.resp.retrieval_mode === "fallback"
                    ? "border-amber-600 text-amber-400"
                    : "border-slate-600 text-slate-400"
                }`}
                title="hybrid = vector + keyword · fallback = keyword-only (embedding failure) · none = memory bypassed"
              >
                retrieval mode: {t.resp.retrieval_mode}
              </span>
            )}

            {t.resp.loop_evidence && (
              <div className="flex flex-wrap gap-2">
                {Object.entries(t.resp.loop_evidence).map(([loop, status]) => (
                  <span
                    key={loop}
                    className={`chip ${
                      status === "completed"
                        ? "border-emerald-600 text-emerald-400"
                        : status === "safe_degraded"
                        ? "border-amber-600 text-amber-400"
                        : "border-slate-600 text-slate-400"
                    }`}
                  >
                    {loop}: {status}
                  </span>
                ))}
              </div>
            )}

            {t.resp.used_memories.length > 0 && (
              <div>
                <p className="text-xs uppercase tracking-wide text-slate-500">Memory used</p>
                <div className="mt-2 space-y-2">
                  {t.resp.used_memories.map((u) => (
                    <div
                      key={u.memory_id}
                      className="rounded-lg border border-slate-800 p-2 text-sm"
                    >
                      <div className="flex items-center justify-between gap-2">
                        <span className="text-slate-200">{u.content}</span>
                        <span className="chip border-accent text-accent shrink-0">
                          {u.memory_type ?? "memory"} · {u.score.toFixed(2)}
                        </span>
                      </div>
                      {u.score_breakdown && (
                        <div className="mt-2 flex flex-wrap gap-1">
                          {Object.entries(u.score_breakdown).map(([k, v]) => (
                            <span
                              key={k}
                              className="rounded bg-ink px-1.5 py-0.5 text-[11px] text-slate-400"
                              title={k}
                            >
                              {k.replace(/_/g, " ")}: {Number(v).toFixed(2)}
                            </span>
                          ))}
                        </div>
                      )}
                      {u.source?.kind && (
                        <p className="mt-1 text-[11px] text-slate-500">source: {u.source.kind}</p>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            )}

            {t.resp.candidate_memories.length > 0 && (
              <div>
                <p className="text-xs uppercase tracking-wide text-slate-500">
                  Policy broker decisions
                </p>
                <div className="mt-1 space-y-2">
                  {t.resp.candidate_memories.map((c, j) => (
                    <div key={j} className="rounded-lg border border-slate-800 p-2 text-sm">
                      <span
                        className={`chip ${decisionColor[c.decision] ?? "border-slate-600"}`}
                      >
                        {c.decision}
                      </span>{" "}
                      <span className="text-slate-400">
                        {c.type} · {c.reason}
                      </span>
                      <p className="mt-1">{c.content}</p>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
