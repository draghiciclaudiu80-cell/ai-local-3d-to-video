import { $, api, button, el, esc, show } from "./core.js";

// ---------- Background tasks (like Claude Code's panel; Computer use › ⏳ Background tasks): everything working on its
// own — apps, skills, the team, computer use, 3D builds, pictures / videos, downloads — with Stop and Open; the count
// shows on the Computer use button; a notice when one finishes, and the chat it belongs to refreshes by itself
// (chat.js listens to "task-done").
const KIND = { app: "💻", skill: "🛠", team: "👥", computer: "🖥", "3d": "🧊", picture: "🎨", video: "🎬", download: "⬇" };
const LIVE = ["running", "queued", "waiting"];
const known = new Map();  // task id -> last status seen
let first = true, timer;

const ago = s => { s = Math.max(0, Math.round(s)); return s < 60 ? `${s}s` : s < 3600 ? `${Math.floor(s / 60)}m ${s % 60}s` : `${Math.floor(s / 3600)}h ${Math.floor(s % 3600 / 60)}m`; };

/** Pages that start a job call this, so its end is noticed even if it ends before the next look. */
export function watchTask(id) { known.set(id, "running"); poll(); }

export function openTask(t) {
  const o = t.open || {};
  if (t.chat && (t.kind === "app" || t.kind === "skill")) o.page = "chat", o.chat = t.chat;  // asked in a chat: its card is there
  if (o.page === "chat" && o.chat) { show("chat"); import("./chat.js").then(m => m.openChat(o.chat)); }
  else if (o.page === "apps") { show("apps"); if (o.app) window.dispatchEvent(new CustomEvent("open-app", { detail: o.app })); }
  else if (o.page === "forge") { show("forge"); if (o.skill) window.dispatchEvent(new CustomEvent("open-skill", { detail: o.skill })); }
  else if (o.page) show(o.page);
  else if (t.chat) { show("chat"); import("./chat.js").then(m => m.openChat(t.chat)); }
}

function statusLine(t, now) {
  const took = (t.ended || now) - (t.started || now);
  return t.status === "running" ? `⚙️ Running · ${ago(took)}${t.note ? " · " + esc(t.note) : ""}`
    : t.status === "waiting" ? `✋ Needs your OK${t.note ? " · " + esc(t.note) : ""}`
    : t.status === "queued" ? "⏳ Queued — starts when the one before it is done"
    : t.status === "done" ? `✓ Done${t.ended ? " · took " + ago(took) : ""}${t.note ? " · " + esc(t.note) : ""}`
    : t.status === "failed" ? `<span class="fitbad">✕ Failed${t.error ? ": " + esc(t.error) : ""}</span>` : "■ Stopped";
}

function render(list) {
  const box = $("bgList"); box.innerHTML = "";
  if (!list.length) { box.append(el("div", "muted small", "Nothing yet. Apps, skills, team jobs, computer use, 3D builds and pictures you start show up here while they work.")); return; }
  const now = Date.now() / 1000;
  for (const t of list) {
    const c = el("div", "bgtask" + (LIVE.includes(t.status) ? " live" : ""),
      `<div class="row"><span>${KIND[t.kind] || "•"}</span><b class="grow">${esc(t.title || t.kind)}</b></div><div class="small">${statusLine(t, now)}</div>`);
    const row = el("div", "row");
    if (LIVE.includes(t.status)) row.append(button("Stop", "sm danger", async () => { await api(`/api/tasks/${encodeURIComponent(t.id)}/stop`, { method: "POST" }).catch(() => {}); poll(); }));
    if (t.open || t.chat) row.append(button(t.status === "waiting" ? "Open — it needs you" : "Open", "sm", () => openTask(t)));
    if (row.children.length) c.append(row);
    box.append(c);
  }
}

function toast(t) {
  const ok = t.status === "done";
  const n = el("div", "toast" + (ok ? "" : " bad"), `<div>${ok ? "✓ Ready" : t.status === "failed" ? "✕ Failed" : "■ Stopped"}: <b>${esc(t.title || t.kind)}</b></div>`);
  if (t.open || t.chat) n.append(button("Open", "sm", () => { openTask(t); n.remove(); }));
  n.append(button("✕", "sm ghost", () => n.remove()));
  $("toasts").append(n);
  setTimeout(() => n.remove(), 12000);
}

const shown = () => $("p-computer").classList.contains("on") && !$("vTasks").hidden;

/** Computer use › Background tasks was opened: fresh list now. */
export function refreshTasks() { poll(); }

async function poll() {
  clearTimeout(timer);
  let list = [];
  try { list = (await api("/api/tasks")).tasks; } catch { timer = setTimeout(poll, 6000); return; }
  for (const t of list) {
    const before = known.get(t.id);
    if (!first && before && LIVE.includes(before) && !LIVE.includes(t.status)) {  // it just finished
      toast(t);
      window.dispatchEvent(new CustomEvent("task-done", { detail: t }));
    }
    known.set(t.id, t.status);
  }
  first = false;
  const live = list.filter(t => LIVE.includes(t.status)), needs = list.filter(t => t.status === "waiting").length;
  for (const id of ["bgCount", "bgCount2"]) {  // on the Computer use button and on its Background tasks tab
    $(id).hidden = !live.length; $(id).textContent = needs ? `${live.length} · ${needs} need you` : live.length;
    $(id).classList.toggle("needs", needs > 0);
  }
  if (shown()) render(list);
  timer = setTimeout(poll, live.length || shown() ? 2500 : 6000);
}

poll();
