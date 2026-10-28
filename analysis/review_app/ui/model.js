// Shared UI state plus pure derivations over it. Views read from here and
// never compute review status on their own, so every screen agrees.

export const LANGFUSE_TRACE_URL = "http://localhost:3000/project/cartwheel-dev/traces/";
export const WORLD_DATE = "2026-07-01";

export const S = {
  conversations: [],
  server: { annotations: [], suggestions: [], patterns: { modes: [] }, manifest: { batches: [] }, labels: {} },
  view: "review",
  queue: "all",
  current: null,      // session_id on screen
  anchor: null,       // { trace_id, turn, step }
  quote: null,
  draft: "",          // unsaved note text, kept across re-renders
  showReference: false,
  selectedMode: null, // taxonomy editor
  labelMode: null,
};

export const bySession = () => new Map(S.conversations.map((c) => [c.session_id, c]));

export function batchOf(sessionId) {
  for (const batch of S.server.manifest.batches || []) {
    if ((batch.items || []).some((item) => item.session_id === sessionId)) return batch.id;
  }
  return null;
}

export function queueConversations() {
  if (S.queue === "all") return S.conversations;
  const batch = (S.server.manifest.batches || []).find((b) => b.id === S.queue);
  if (!batch) return [];
  const index = bySession();
  return batch.items.map((item) => index.get(item.session_id)).filter(Boolean);
}

export const humanNotes = () => S.server.annotations.filter((a) => a.author === "human");

export const notesFor = (sessionId) => humanNotes().filter((a) => a.session_id === sessionId);

export const pendingSuggestionsFor = (sessionId) =>
  S.server.suggestions.filter((s) => s.session_id === sessionId && s.status === "pending");

// A conversation counts as reviewed once it has an open code or a
// "no failure" note; every turn (trace) in it then counts toward the total.
export function reviewedSessions() {
  return new Set(humanNotes().map((a) => a.session_id));
}

export function reviewedTraces() {
  const reviewed = reviewedSessions();
  return S.conversations
    .filter((c) => reviewed.has(c.session_id))
    .flatMap((c) => c.turns.map((t) => ({ conv: c, turn: t })));
}

export const activeModes = () => (S.server.patterns.modes || []).filter((m) => m.status !== "rejected");

export const finalModes = () => (S.server.patterns.modes || []).filter((m) => m.status === "final");

export function liveLabel(mode, traceId) {
  return (S.server.labels[mode] || []).find((row) => row.trace_id === traceId) || null;
}

export function stepLabel(step) {
  if (step === "user") return "user message";
  if (step === "reply") return "agent reply";
  return `tool call ${Number(step.split(":")[1]) + 1}`;
}
