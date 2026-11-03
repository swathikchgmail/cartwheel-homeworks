// Taxonomy screen: open codes on the left, the selected mode's definition on
// the right. Ticking a code links it to the mode (created_from). Every saved
// change to a status, definition, or boundary needs a reason and is appended
// to the mode's history, which is the taxonomy revision record. A saved mode
// keeps its name; to rename, reject it and create the new mode.

import { postJSON } from "./api.js";
import { clear, el, short, toast } from "./dom.js";
import { S, humanNotes, reviewedTraces } from "./model.js";
import { openConversation } from "./review.js";

const TRACKED = ["status", "definition", "boundary"];
let ctx;
let draft = null;   // working copy of the modes list
let filter = "";

export function initTaxonomy(context) { ctx = context; }

export function renderTaxonomy() {
  if (!draft) draft = structuredClone(S.server.patterns.modes || []);
  const root = clear(document.getElementById("view-taxonomy"));
  root.append(codesPanel(), modePanel());
}

export function resetTaxonomyDraft() { draft = null; }

const selected = () => draft.find((m) => m.name === S.selectedMode) || null;
const savedNames = () => new Set((S.server.patterns.modes || []).map((m) => m.name));

// -- open codes -------------------------------------------------------------

function codesPanel() {
  const mode = selected();
  const codes = humanNotes().filter((a) => a.kind === "open_code" && a.note.toLowerCase().includes(filter));
  const search = el("input", { placeholder: "Filter notes", value: filter, "aria-label": "Filter notes" });
  search.addEventListener("change", () => { filter = search.value.toLowerCase(); renderTaxonomy(); });
  const list = el("ul", { class: "code-list" });
  for (const a of codes) {
    const members = draft.filter((m) => (m.created_from || []).includes(a.id)).map((m) => m.name);
    const box = mode && el("input", { type: "checkbox", checked: members.includes(mode.name), "aria-label": `Link to ${mode.name}`, onchange: (e) => toggleCode(mode, a.id, e.target.checked) });
    list.append(el("li", {}, box,
      el("div", {},
        el("div", { text: a.note }),
        el("div", { class: "tags" },
          el("button", { class: "small", onclick: () => openConversation(a.session_id), text: `${a.scenario_id} t${a.turn}` }),
          ...members.map((name) => el("span", { class: "chip", text: name }))))));
  }
  return el("div", { class: "panel" },
    el("h3", { text: `Open codes (${codes.length})${mode ? ` · tick to link to ${mode.name}` : " · select a mode to link codes"}` }),
    search, list);
}

function toggleCode(mode, id, on) {
  const set = new Set(mode.created_from || []);
  if (on) set.add(id); else set.delete(id);
  mode.created_from = [...set];
  renderTaxonomy();
}

// -- mode editor ------------------------------------------------------------

function modePanel() {
  const tabs = el("div", { class: "mode-tabs" },
    ...draft.map((m) => el("button", { class: `${m.name === S.selectedMode ? "sel" : ""} ${m.status === "rejected" ? "rejected" : ""}`, onclick: () => { S.selectedMode = m.name; renderTaxonomy(); }, text: `${m.name} (${(m.created_from || []).length})` })),
    el("button", { class: "small", onclick: addMode, text: "+ New mode" }));
  const mode = selected();
  return el("div", { class: "panel" }, el("h3", { text: "Failure modes" }), tabs,
    mode ? editor(mode) : el("p", { class: "empty", text: "Create a mode, then tick the open codes it groups." }));
}

function addMode() {
  const name = window.prompt("snake_case name for the new mode:");
  if (!name) return;
  if (!/^[a-z][a-z0-9]*(_[a-z0-9]+)*$/.test(name)) return toast("Use snake_case, for example unconfirmed_write", true);
  if (draft.some((m) => m.name === name)) return toast("That name exists already", true);
  draft.push({ name, status: "candidate", definition: "", boundary: "", nearest_mode: "", requirement_source: "", evaluator_type: null, created_from: [], example_trace_ids: [], close_negative_trace_ids: [], history: [], notes: "" });
  S.selectedMode = name;
  renderTaxonomy();
}

function editor(mode) {
  const field = (key, input) => { input.addEventListener("input", () => { mode[key] = input.value; }); return input; };
  const select = (key, options) => {
    const node = el("select", { "aria-label": key }, ...options.map(([v, t]) => el("option", { value: v, text: t })));
    node.value = mode[key] ?? "";
    node.addEventListener("change", () => { mode[key] = node.value || null; });
    return node;
  };
  const reason = el("input", { id: "change-reason", placeholder: "Why did this change? (required when status, definition, or boundary changes)" });
  return el("div", {},
    el("div", { class: "form-grid" },
      el("label", { text: "Name" }), el("input", { value: mode.name, disabled: true }),
      el("label", { text: "Status" }), select("status", [["candidate", "candidate"], ["final", "final"], ["rejected", "rejected"]]),
      el("label", { text: "Binary definition" }), field("definition", el("textarea", {}, mode.definition || "")),
      el("label", { text: "Boundary" }), field("boundary", el("textarea", { placeholder: "Not this mode when … (that is <nearest mode>)" }, mode.boundary || "")),
      el("label", { text: "Nearest mode" }), field("nearest_mode", el("input", { value: mode.nearest_mode || "" })),
      el("label", { text: "Requirement source" }), field("requirement_source", el("input", { value: mode.requirement_source || "", placeholder: "RESP-2, or SPEC revision: …" })),
      el("label", { text: "Likely evaluator" }), select("evaluator_type", [["", "undecided"], ["code", "code check"], ["judge", "LLM judge"]]),
      el("label", { text: "Notes" }), field("notes", el("textarea", {}, mode.notes || ""))),
    !(mode.created_from || []).length && el("p", { class: "warn", text: "No supporting open codes linked yet." }),
    traceList(mode, "example_trace_ids", "Confirmed positives (failure present)"),
    traceList(mode, "close_negative_trace_ids", "Close negatives (looks similar, failure absent)"),
    el("div", { class: "row" }, reason, el("button", { class: "primary", onclick: save, text: "Save taxonomy" })),
    history(mode));
}

function traceList(mode, key, title) {
  const ids = mode[key] || [];
  const names = new Map(reviewedTraces().map(({ conv, turn }) => [turn.trace_id, `${conv.scenario_id} · turn ${turn.index}`]));
  const picker = el("select", { "aria-label": `Add to ${title}` }, el("option", { value: "", text: "Add a reviewed trace…" }),
    ...[...names].filter(([id]) => !ids.includes(id)).map(([id, label]) => el("option", { value: id, text: label })));
  picker.addEventListener("change", () => { if (picker.value) { mode[key] = [...ids, picker.value]; renderTaxonomy(); } });
  return el("div", {},
    el("h3", { text: `${title}: ${ids.length}` }),
    ids.length < 3 && el("p", { class: "warn", text: "At least 3 needed (if the reviewed data permits)." }),
    el("div", { class: "row" }, ...ids.map((id) => el("span", { class: "chip" }, names.get(id) || id.slice(0, 8), " ",
      el("button", { class: "small", "aria-label": "Remove", onclick: () => { mode[key] = ids.filter((x) => x !== id); renderTaxonomy(); }, text: "×" })))),
    picker);
}

function history(mode) {
  const rows = mode.history || [];
  if (!rows.length) return null;
  return el("div", { class: "history" }, el("h3", { text: "Revision history" }),
    ...rows.map((h) => el("div", { text: `${h.ts.slice(0, 16)} · ${h.field}: “${short(h.from, 60)}” → “${short(h.to, 60)}” · ${h.reason}` })));
}

async function save() {
  const reason = document.getElementById("change-reason")?.value.trim() || "";
  const before = new Map((S.server.patterns.modes || []).map((m) => [m.name, m]));
  const saved = savedNames();
  const ts = new Date().toISOString();
  const next = structuredClone(draft);
  for (const mode of next) {
    if (!saved.has(mode.name)) continue;
    const old = before.get(mode.name);
    const changes = TRACKED.filter((k) => (old[k] || "") !== (mode[k] || ""));
    if (changes.length && !reason) return toast(`Give a reason for changing ${mode.name}: ${changes.join(", ")}`, true);
    mode.history = [...(mode.history || []), ...changes.map((field) => ({ ts, field, from: old[field] || "", to: mode[field] || "", reason }))];
  }
  try {
    await postJSON("/api/patterns", { modes: next });
    toast("Taxonomy saved");
    draft = null;
    await ctx.refresh();
  } catch (err) { toast(err.message, true); }
}
