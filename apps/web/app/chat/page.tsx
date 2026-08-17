"use client";

import { useState } from "react";

import ChatTurn from "@/components/chat/ChatTurn";
import {
  ApiError,
  api,
  type ChatResponse,
} from "@/lib/api";
import {
  Button,
  Checkbox,
  EmptyState,
  ErrorState,
  Field,
  PageHeader,
  Panel,
  PanelBody,
  TextArea,
} from "@/components/ui";

interface Turn {
  user: string;
  resp: ChatResponse;
}

/**
 * Turn a raw failure into something an operator can act on.
 *
 * `String(e)` produced "ApiError: 401 Unauthorized" in the UI, which says nothing
 * about what to do. The BFF's status codes are meaningful — 401 is no session, 403 is
 * a persona that may not attempt this — so they are worth translating.
 */
function describeError(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 401) return "Your session is not valid. Sign in and try again.";
    if (error.status === 403) return "Your role may not start a governed chat session.";
    if (error.status === 502) return "The MemoryOps API is unreachable.";
    return `The API returned ${error.status}.`;
  }
  return error instanceof Error ? error.message : String(error);
}

export default function ChatPage() {
  const [message, setMessage] = useState("");
  const [temporary, setTemporary] = useState(false);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function send() {
    const trimmed = message.trim();
    if (!trimmed || loading) return;
    setLoading(true);
    setError("");
    try {
      const resp = await api.chat(trimmed, temporary);
      setTurns((t) => [{ user: trimmed, resp }, ...t]);
      setMessage("");
    } catch (e) {
      setError(describeError(e));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Runtime"
        title="Chat"
        description="A governed session. Every turn shows the candidate memories the extractor produced, what the policy broker decided about each, and which stored memories entered the model's context."
      />

      <Panel>
        <PanelBody className="space-y-3">
          <form
            onSubmit={(event) => {
              event.preventDefault();
              void send();
            }}
            className="space-y-3"
          >
            <Field label="Message" hideLabel>
              <TextArea
                rows={3}
                placeholder="Try: Remember that I prefer enterprise-style explanations with no emojis."
                value={message}
                onChange={(e) => setMessage(e.target.value)}
                onKeyDown={(e) => {
                  // Enter sends; Shift+Enter is a newline. A control plane's composer
                  // should not need a mouse round-trip for every turn.
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    void send();
                  }
                }}
                disabled={loading}
              />
            </Field>
            <div className="flex flex-wrap items-center justify-between gap-3">
              <Checkbox
                label="Temporary chat — writes and reads no memory"
                checked={temporary}
                onChange={(e) => setTemporary(e.target.checked)}
                disabled={loading}
              />
              <Button
                type="submit"
                variant="primary"
                disabled={loading || message.trim().length === 0}
              >
                {loading ? "Sending…" : "Send"}
              </Button>
            </div>
          </form>
          <p className="text-xs text-fg-muted">
            Press Enter to send, Shift + Enter for a new line.
          </p>
        </PanelBody>
      </Panel>

      {error ? <ErrorState detail={error} /> : null}

      {turns.length === 0 && !loading ? (
        <EmptyState
          title="No turns in this session yet"
          description="Send a message to see the write path (extraction → policy decision) and the read path (retrieval → ranking → context admission) for that turn."
        />
      ) : (
        <div className="space-y-4">
          {turns.map((turn, i) => (
            <ChatTurn
              key={`${turn.resp.trace_id}-${i}`}
              userMessage={turn.user}
              response={turn.resp}
            />
          ))}
        </div>
      )}
    </div>
  );
}
