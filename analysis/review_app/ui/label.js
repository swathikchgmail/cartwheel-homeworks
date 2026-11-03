// Label screen: one Pass/Fail judgment per reviewed trace for the chosen
// mode. Fail means the failure is present (stored as 1) and needs evidence.
// Each judgment is written to Langfuse as a score and to labels/<mode>.jsonl.

import { postJSON } from "./api.js";
import { clear, el, short, toast } from "./dom.js";
import { S, activeModes, humanNotes, liveLabel, reviewedTraces } from "./model.js";
import { openConversation } from "./review.js";

let ctx;
let onlyMissing = false;

export function initLabel(context) { ctx = context; }

export function renderLabel() {
  const root = clear(document.getElementById("view-label"));
  const modes = activeModes();
  if (!modes.length) { root.append(el("p", { class: "empty", text: "Define modes in Taxonomy first." })); return; }
  if (!modes.some((m) => m.name === S.labelMode)) S.labelMode = modes[0].name;
  const mode = modes.find((m) => m.name === S.labelMode);
  const rows = reviewedTraces().filter(({ turn }) => !onlyMissing || !liveLabel(mode.name, turn.trace_id));
  const done = reviewedTraces().filter(({ turn }) => liveLabel(mode.name, turn.trace_id)).length;
  root.append(toolbar(modes, mode, done), el("p", { class: "history", text: mode.definition || "No definition yet." }), table(mode, rows));
}

function toolbar(modes, mode, done) {
  const pick = el("select", { "aria-label": "Mode" }, ...modes.map((m) => el("option", { value: m.name, text: `${m.name}${m.status === "final" ? "" : " (candidate)"}` })));
  pick.value = mode.name;
  pick.addEventListener("change", () => { S.labelMode = pick.value; renderLabel(); });
  const missing = el("input", { type: "checkbox", id: "only-missing", checked: onlyMissing, onchange: (e) => { onlyMissing = e.target.checked; renderLabel(); } });
  return el("div", { class: "toolbar" }, pick, el("span", { text: `${done} / ${reviewedTraces().length} reviewed traces labeled` }),
    el("label", {}, missing, " unlabeled only"));
}

function table(mode, rows) {
  const notes = new Map(humanNotes().map((a) => [a.trace_id, a]));
  const body = el("tbody", {}, ...rows.map(({ conv, turn }) => row(mode, conv, turn, notes.get(turn.trace_id))));
  return el("table", {}, el("thead", {}, el("tr", {}, ...["Trace", "Your first-failure note", "Agent reply", "Judgment", "Evidence"].map((h) => el("th", { text: h })))), body);
}

function row(mode, conv, turn, note) {
  const current = liveLabel(mode.name, turn.trace_id);
  const evidence = el("input", { value: current?.evidence || "", placeholder: "tool result or quote", "aria-label": "Evidence" });
  const mark = (label) => save(mode.name, turn.trace_id, label, evidence.value.trim());
  return el("tr", {},
    el("td", {}, el("button", { class: "small", onclick: () => openConversation(conv.session_id), text: `${conv.scenario_id} t${turn.index}` })),
    el("td", { text: note ? short(note.note, 120) : "—" }),
    el("td", { class: "reply-cell", text: short(turn.reply_text, 200) }),
    el("td", {},
      el("div", { class: "pf" },
        el("button", { class: `small${current?.label === 1 ? " on-fail" : ""}`, onclick: () => mark(1), text: "Fail (present)" }),
        el("button", { class: `small${current?.label === 0 ? " on-pass" : ""}`, onclick: () => mark(0), text: "Pass (absent)" })),
      current && !current.langfuse_synced && el("div", { class: "unsynced", text: "not in Langfuse yet" })),
    el("td", {}, evidence));
}

async function save(mode, traceId, label, evidence) {
  if (label === 1 && !evidence) return toast("A Fail needs evidence: the tool result or a quote.", true);
  try {
    const result = await postJSON("/api/labels", { mode, trace_id: traceId, label, evidence });
    toast(result.synced ? "Saved to Langfuse and local file" : `Saved locally only. ${result.error || ""}`, !result.synced);
    await ctx.refresh();
  } catch (err) { toast(err.message, true); }
}
