// Progress screen: reviewed traces per batch, incomplete judgments, AI
// suggestion decisions, sample fractions, and new modes in the final batch.

import { clear, el } from "./dom.js";
import { S, bySession, finalModes, humanNotes, liveLabel, reviewedSessions, reviewedTraces } from "./model.js";

const TARGET = 100;

export function renderProgress() {
  const root = clear(document.getElementById("view-progress"));
  const traces = reviewedTraces();
  const unsynced = Object.values(S.server.labels).flat().filter((r) => !r.langfuse_synced).length;
  const sugg = S.server.suggestions;
  root.append(
    el("div", { class: "metrics" },
      metric("Reviewed traces", `${traces.length} / ${TARGET}`),
      metric("Reviewed conversations", reviewedSessions().size),
      metric("Open codes", humanNotes().filter((a) => a.kind === "open_code").length),
      metric("AI suggestions decided", `${sugg.filter((s) => s.status !== "pending").length} / ${sugg.length}`),
      metric("Labels not in Langfuse", unsynced)),
    el("h3", { text: "Batches" }), batchTable(),
    el("h3", { text: "Final modes: judgments and sample fractions" }), modeTable(traces),
    el("h3", { text: "Taxonomy stability" }), stability());
}

function metric(label, value) {
  return el("div", { class: "metric" }, el("div", { class: "label", text: label }), el("div", { class: "value", text: String(value) }));
}

function batchTable() {
  const reviewed = reviewedSessions();
  const index = bySession();
  const rows = (S.server.manifest.batches || []).map((b) => {
    const convs = b.items.map((i) => index.get(i.session_id)).filter(Boolean);
    const traces = convs.reduce((n, c) => n + c.turns.length, 0);
    const done = convs.filter((c) => reviewed.has(c.session_id));
    const doneTraces = done.reduce((n, c) => n + c.turns.length, 0);
    return el("tr", {}, ...[b.label || b.id, b.method || "", `${done.length} / ${convs.length}`, `${doneTraces} / ${traces}`].map((v) => el("td", { text: v })));
  });
  if (!rows.length) return el("p", { class: "empty", text: "No batches yet. The sample manifest is written when Part B starts." });
  return el("table", {}, el("thead", {}, el("tr", {}, ...["Batch", "Selection method", "Conversations reviewed", "Traces reviewed"].map((h) => el("th", { text: h })))), el("tbody", {}, rows));
}

function modeTable(traces) {
  const modes = finalModes();
  if (!modes.length) return el("p", { class: "empty", text: "No final modes yet." });
  const rows = modes.map((m) => {
    const labels = traces.map(({ turn }) => liveLabel(m.name, turn.trace_id)).filter(Boolean);
    const fails = labels.filter((l) => l.label === 1).length;
    const missing = traces.length - labels.length;
    const fraction = labels.length ? `${fails} / ${labels.length} (${((100 * fails) / labels.length).toFixed(1)}%)` : "—";
    return el("tr", {}, ...[m.name, `${labels.length} / ${traces.length}`, String(missing), fraction, String((m.example_trace_ids || []).length), String((m.close_negative_trace_ids || []).length)].map((v) => el("td", { text: v })));
  });
  return el("table", {}, el("thead", {}, el("tr", {}, ...["Mode", "Judged", "Missing", "Fail count / sample fraction", "Positives", "Close negatives"].map((h) => el("th", { text: h })))), el("tbody", {}, rows));
}

// A mode is "new in the final batch" when every open code it was created
// from came from the batch flagged final_check in the manifest.
function stability() {
  const finalBatch = (S.server.manifest.batches || []).find((b) => b.final_check);
  if (!finalBatch) return el("p", { class: "empty", text: "The final uniform batch has not been drawn yet." });
  const byId = new Map(humanNotes().map((a) => [a.id, a]));
  const fresh = (S.server.patterns.modes || []).filter((m) => m.status !== "rejected" && (m.created_from || []).length
    && m.created_from.every((id) => byId.get(id)?.batch === finalBatch.id));
  return el("p", { text: `Modes first seen in ${finalBatch.label || finalBatch.id}: ${fresh.length}${fresh.length ? ` (${fresh.map((m) => m.name).join(", ")})` : ""}` });
}
