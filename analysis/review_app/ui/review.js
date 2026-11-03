// Review screen: queue (left), one conversation (center), notes (right).
// A click on a user message, tool card, or reply sets the note's anchor;
// selecting text inside that step also captures a quote.

import { postJSON } from "./api.js";
import { clear, el, isTyping, short, toast } from "./dom.js";
import {
  LANGFUSE_TRACE_URL, S, WORLD_DATE, batchOf, bySession, notesFor,
  pendingSuggestionsFor, queueConversations, reviewedSessions, stepLabel,
} from "./model.js";

let ctx;

export function initReview(context) {
  ctx = context;
  document.getElementById("batch-filter").addEventListener("change", (e) => {
    S.queue = e.target.value;
    const first = queueConversations()[0];
    if (first) open(first.session_id);
    renderReview();
  });
  document.addEventListener("keydown", onKey);
  document.addEventListener("mouseup", captureQuote);
}

export function renderReview() {
  renderQueue();
  renderConversation();
  renderNotes();
}

function open(sessionId) {
  if (sessionId !== S.current) S.draft = "";
  S.current = sessionId;
  S.anchor = null;
  S.quote = null;
  S.showReference = false;
}

export function openConversation(sessionId) {
  open(sessionId);
  ctx.show("review");
}

// -- queue ------------------------------------------------------------------

function renderQueue() {
  const select = clear(document.getElementById("batch-filter"));
  select.append(el("option", { value: "all", text: `All conversations (${S.conversations.length})` }));
  for (const b of S.server.manifest.batches || []) {
    select.append(el("option", { value: b.id, text: `${b.label || b.id} (${b.items.length})` }));
  }
  select.value = S.queue;
  const reviewed = reviewedSessions();
  const list = clear(document.getElementById("queue-list"));
  for (const conv of queueConversations()) {
    const done = reviewed.has(conv.session_id);
    const pending = pendingSuggestionsFor(conv.session_id).length;
    list.append(el("li", {
      class: conv.session_id === S.current ? "current" : "",
      onclick: () => { open(conv.session_id); renderReview(); },
    },
    el("span", { class: `dot${done ? " done" : ""}`, text: done ? "✓" : "○" }),
    conv.scenario_id.replace("support-", ""),
    el("span", { class: "meta", text: `${conv.role} · ${conv.turns.length}t${pending ? ` · ${pending} AI` : ""}` })));
  }
}

function move(delta) {
  const queue = queueConversations();
  const i = queue.findIndex((c) => c.session_id === S.current);
  const next = queue[Math.min(queue.length - 1, Math.max(0, i + delta))];
  if (next) { open(next.session_id); renderReview(); window.scrollTo(0, 0); }
}

// -- conversation -----------------------------------------------------------

function renderConversation() {
  const root = clear(document.getElementById("conversation"));
  const conv = bySession().get(S.current);
  if (!conv) { root.append(el("p", { class: "empty", text: "Pick a conversation from the queue." })); return; }
  root.append(header(conv));
  if (S.showReference) root.append(reference(conv));
  if (conv.system_prompt) {
    root.append(el("details", { class: "sys" }, el("summary", { text: "System prompt (same in every call)" }), el("pre", { text: conv.system_prompt })));
  }
  const anchored = new Set(notesFor(conv.session_id).map((a) => `${a.trace_id}|${a.step}`));
  for (const turn of conv.turns) root.append(renderTurn(conv, turn, anchored));
}

function header(conv) {
  const tuple = conv.reference?.tuple || {};
  const target = tuple.order_id ? `order ${tuple.order_id}` : tuple.product_id ? `product ${tuple.product_id}` : null;
  return el("div", { class: "conv-head" },
    el("strong", { text: conv.scenario_id }),
    el("span", { class: "chip", text: `${conv.role} · user ${conv.user_id ?? "?"}` }),
    tuple.intent && el("span", { class: "chip", text: tuple.intent }),
    target && el("span", { class: "chip", text: target }),
    el("span", { class: "chip", text: `world date ${WORLD_DATE}` }),
    conv.reference?.data_quality_case_id && el("span", { class: "chip dq", text: `damaged record ${conv.reference.data_quality_case_id}` }),
    el("button", { class: "small", onclick: toggleReference, text: S.showReference ? "Hide reference (r)" : "Show reference (r)" }));
}

function reference(conv) {
  if (!S.showReference) return null;
  const ref = conv.reference;
  if (!ref) return el("div", { class: "reference", text: "No HW3 scenario record for this conversation." });
  const exp = ref.expected || {};
  const t = ref.tuple || {};
  const rows = [
    ["Expected", exp.outcome], ["Why", exp.reason], ["Source", exp.source && `${exp.source.type}: ${exp.source.reference}`],
    ["Evaluation", exp.evaluation], ["Record state", t.record_state], ["Policy", t.applicable_policy],
    ["Difficulty", t.difficulty], ["User style", t.user_style], ["Group", ref.scenario_group],
  ].filter(([, v]) => v);
  return el("div", { class: "reference" }, el("dl", {}, rows.flatMap(([k, v]) => [el("dt", { text: k }), el("dd", { text: v })])));
}

function toggleReference() {
  S.showReference = !S.showReference;
  renderConversation();
}

function renderTurn(conv, turn, anchored) {
  const box = el("section", { class: "turn" },
    el("div", { class: "turn-label" },
      `Turn ${turn.index} of ${conv.turns.length}`,
      el("span", { text: `· ${turn.model_calls} model call${turn.model_calls === 1 ? "" : "s"}` }),
      el("a", { href: LANGFUSE_TRACE_URL + turn.trace_id, target: "_blank", rel: "noopener", text: `trace ${turn.trace_id.slice(0, 8)}` })));
  box.append(step(turn, "user", anchored, el("span", { class: "who", text: "User" }), el("div", { class: "body", text: turn.user_text })));
  if (!turn.steps.length) box.append(el("div", { class: "no-tools", text: "No tool calls in this turn." }));
  turn.steps.forEach((s, i) => box.append(toolCard(turn, s, i, anchored)));
  box.append(step(turn, "reply", anchored, el("span", { class: "who", text: "Agent" }), el("div", { class: "body", text: turn.reply_text })));
  return box;
}

function toolCard(turn, s, i, anchored) {
  const status = s.ok === false ? el("span", { class: "badge err", text: "error" }) : el("span", { class: "badge ok", text: "ok" });
  return step(turn, `tool:${i}`, anchored,
    el("div", {}, el("span", { class: "tool-name", text: s.name }), " ", el("span", { class: "args", text: short(JSON.stringify(s.input), 110) }), status),
    el("div", { class: "summary", text: s.summary }),
    el("details", { onclick: (e) => e.stopPropagation() }, el("summary", { text: "full result" }), el("pre", { text: JSON.stringify(s.output, null, 2) })));
}

function step(turn, name, anchored, ...children) {
  const isAnchor = S.anchor && S.anchor.trace_id === turn.trace_id && S.anchor.step === name;
  const classes = ["step", name.startsWith("tool") ? "tool" : name, isAnchor && "anchor", anchored.has(`${turn.trace_id}|${name}`) && "has-note"];
  return el("div", {
    class: classes.filter(Boolean).join(" "), tabindex: 0,
    "data-trace": turn.trace_id, "data-step": name, "data-turn": turn.index,
    onclick: () => setAnchor({ trace_id: turn.trace_id, turn: turn.index, step: name }),
  }, ...children);
}

function setAnchor(anchor) {
  const same = S.anchor && S.anchor.trace_id === anchor.trace_id && S.anchor.step === anchor.step;
  if (!same) S.quote = null;
  S.anchor = anchor;
  renderConversation();
  renderNotes();
}

function captureQuote() {
  const sel = window.getSelection();
  const text = sel?.toString().trim();
  if (!text) return;
  const node = sel.anchorNode?.parentElement?.closest(".step");
  if (!node || !document.getElementById("conversation").contains(node)) return;
  S.anchor = { trace_id: node.dataset.trace, turn: Number(node.dataset.turn), step: node.dataset.step };
  S.quote = short(text, 300);
  renderNotes();
}

// -- notes ------------------------------------------------------------------

function renderNotes() {
  const root = clear(document.getElementById("notes"));
  const conv = bySession().get(S.current);
  if (!conv) return;
  root.append(el("h3", { text: "First failure (open code)" }), composer(conv));
  const suggestions = pendingSuggestionsFor(conv.session_id);
  if (suggestions.length) root.append(el("h3", { text: "AI suggestions (not yours until accepted)" }), ...suggestions.map(suggestionCard));
  const notes = notesFor(conv.session_id);
  root.append(el("h3", { text: `Your notes (${notes.length})` }));
  if (!notes.length) root.append(el("p", { class: "empty", text: "Nothing saved for this conversation yet." }));
  root.append(...notes.map(noteCard));
}

function composer(conv) {
  const where = S.anchor ? `Turn ${S.anchor.turn} · ${stepLabel(S.anchor.step)}` : "Click the step where the first failure happens.";
  const box = el("textarea", { id: "note-input", placeholder: "the reply reports a completed refund even though the tool only queued it", "aria-label": "Open code" });
  box.value = S.draft || "";
  box.addEventListener("input", () => { S.draft = box.value; });
  box.addEventListener("keydown", (e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) saveNote(conv, "open_code"); });
  return el("div", {},
    el("div", { class: "anchor-line", text: where }),
    S.quote && el("div", { class: "quote", text: `“${S.quote}”` }),
    box,
    el("div", { class: "row" },
      el("button", { class: "primary", onclick: () => saveNote(conv, "open_code"), text: "Save note (⌘↵)" }),
      el("button", { onclick: () => saveNote(conv, "no_failure"), text: "No failure observed (0)" })));
}

async function saveNote(conv, kind) {
  const note = document.getElementById("note-input")?.value.trim() || "";
  const last = conv.turns[conv.turns.length - 1];
  const anchor = S.anchor || (kind === "no_failure" ? { trace_id: last.trace_id, turn: last.index, step: "reply" } : null);
  if (!anchor) return toast("Click the step where the failure happens first.", true);
  if (kind === "open_code" && !note) return toast("Write what went wrong, in your own words.", true);
  try {
    await postJSON("/api/annotations", {
      ...anchor, session_id: conv.session_id, scenario_id: conv.scenario_id,
      note, kind, quote: S.quote, batch: batchOf(conv.session_id),
    });
    S.quote = null;
    S.draft = "";
    toast(kind === "no_failure" ? "Marked: no failure observed" : "Note saved");
    await ctx.refresh();
  } catch (err) { toast(err.message, true); }
}

function noteCard(a) {
  const edit = () => {
    const next = window.prompt("Edit note (the original stays in history):", a.note);
    if (next && next.trim() && next.trim() !== a.note) {
      postJSON(`/api/annotations/${a.id}`, { note: next }).then(ctx.refresh).catch((e) => toast(e.message, true));
    }
  };
  return el("div", { class: `note${a.kind === "no_failure" ? " nofail" : ""}`, onmouseenter: () => link(a, true), onmouseleave: () => link(a, false) },
    el("div", { class: "where", text: `Turn ${a.turn} · ${stepLabel(a.step)}${a.batch ? ` · ${a.batch}` : ""}${a.accepted_from ? " · from AI suggestion" : ""}` }),
    a.quote && el("div", { class: "quote", text: `“${a.quote}”` }),
    el("div", { text: a.note }),
    ...(a.history || []).map((h) => el("div", { class: "old", text: h.note })),
    el("div", { class: "row" }, el("button", { class: "small", onclick: edit, text: "Edit" })));
}

function suggestionCard(s) {
  const reason = el("input", { placeholder: "Reason to reject", "aria-label": "Rejection reason" });
  const decide = async (verb) => {
    try {
      const body = verb === "accept" ? { batch: batchOf(s.session_id) } : { reason: reason.value };
      await postJSON(`/api/suggestions/${s.id}/${verb}`, body);
      toast(verb === "accept" ? "Accepted as your note" : "Rejected");
      await ctx.refresh();
    } catch (err) { toast(err.message, true); }
  };
  return el("div", { class: "suggestion", onmouseenter: () => link(s, true), onmouseleave: () => link(s, false) },
    el("div", { class: "where" }, el("span", { class: "badge ai", text: "AI" }), ` Turn ${s.turn} · ${stepLabel(s.step)} · ${s.source}`),
    el("div", { text: s.note }),
    el("div", { class: "row" }, el("button", { class: "small", onclick: () => decide("accept"), text: "Accept" }), reason,
      el("button", { class: "small", onclick: () => decide("reject"), text: "Reject" })));
}

function link(item, on) {
  const node = document.querySelector(`.step[data-trace="${item.trace_id}"][data-step="${item.step}"]`);
  node?.classList.toggle("linked", on);
  if (on) node?.scrollIntoView({ block: "nearest", behavior: "smooth" });
}

// -- keyboard ---------------------------------------------------------------

function onKey(e) {
  if (S.view !== "review" || isTyping(e) || e.metaKey || e.ctrlKey || e.altKey) return;
  const conv = bySession().get(S.current);
  const actions = {
    j: () => move(1), k: () => move(-1),
    n: () => document.getElementById("note-input")?.focus(),
    r: toggleReference,
    0: () => conv && saveNote(conv, "no_failure"),
  };
  if (actions[e.key]) { e.preventDefault(); actions[e.key](); }
}
