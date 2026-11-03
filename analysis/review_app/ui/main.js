// Boot, view switching, and polling. The server state is polled every 5 s so
// AI suggestions written by the coding agent appear without a reload; a poll
// never re-renders while you are typing.

import { getJSON } from "./api.js";
import { isTyping, toast } from "./dom.js";
import { S, queueConversations, reviewedTraces } from "./model.js";
import { initLabel, renderLabel } from "./label.js";
import { renderProgress } from "./progress.js";
import { initReview, renderReview } from "./review.js";
import { initTaxonomy, renderTaxonomy, resetTaxonomyDraft } from "./taxonomy.js";

const RENDER = { review: renderReview, taxonomy: renderTaxonomy, label: renderLabel, progress: renderProgress };
const POLL_MS = 5000;
let signature = "";

function show(view) {
  S.view = view;
  for (const tab of document.querySelectorAll(".tab")) tab.classList.toggle("active", tab.dataset.view === view);
  for (const section of document.querySelectorAll(".view")) section.classList.toggle("active", section.id === `view-${view}`);
  if (view !== "taxonomy") resetTaxonomyDraft();
  RENDER[view]();
}

function updateStatus() {
  const pending = S.server.suggestions.filter((s) => s.status === "pending").length;
  document.getElementById("status").textContent =
    `${reviewedTraces().length} traces reviewed${pending ? ` · ${pending} AI suggestion${pending === 1 ? "" : "s"} pending` : ""}`;
}

async function refresh() {
  const next = await getJSON("/api/state");
  const sig = JSON.stringify(next);
  if (sig === signature) return;
  const hadPending = S.server.suggestions.filter((s) => s.status === "pending").length;
  signature = sig;
  S.server = next;
  updateStatus();
  RENDER[S.view]();
  const nowPending = next.suggestions.filter((s) => s.status === "pending").length;
  if (nowPending > hadPending) toast(`${nowPending - hadPending} new AI suggestion(s)`);
}

async function poll() {
  try {
    if (!isTyping({ target: document.activeElement })) await refresh();
  } catch (err) {
    document.getElementById("status").textContent = `Server unreachable: ${err.message}`;
  }
}

async function boot() {
  const context = { refresh, show };
  initReview(context);
  initTaxonomy(context);
  initLabel(context);
  for (const tab of document.querySelectorAll(".tab")) tab.addEventListener("click", () => show(tab.dataset.view));
  S.conversations = await getJSON("/api/conversations");
  await refresh();
  S.current = queueConversations()[0]?.session_id ?? null;
  show("review");
  setInterval(poll, POLL_MS);
}

boot().catch((err) => toast(`Could not load: ${err.message}`, true));
