import { $, api, button, el, esc, json, onPage, show, store } from "./core.js";
import { refreshTasks } from "./tasks.js";

// ---------- Computer use: the task + its steps on the left, the app's browser / the PC screen on the right
const LABEL = { thinking: "Looking…", waiting: "Waiting for your OK", running: "Doing it…",
  done: "Finished ✓", failed: "Couldn't finish", stopped: "Stopped" };
const LIVE = ["thinking", "waiting", "running"];
let timer, taskId = null, where = store.get("cuWhere", "browser"), view = "browser", lastTarget = "";

const visible = () => $("p-computer").classList.contains("on");
const decideRow = (t, after) => {
  const row = el("div", "row");
  const go = async (approve, auto) => {
    row.querySelectorAll("button").forEach(b => b.disabled = true);
    await api(`/api/computer/${t.id}/decide`, json("POST", { approve, auto })).catch(e => alert(e.message)); after();
  };
  row.append(button("Approve", "primary sm", () => go(true, false)), button("Skip", "sm", () => go(false, false)),
    button("Approve all steps", "sm", () => { if (confirm("Let it do the rest of this task without asking? You can still press Stop.")) go(true, true); }));
  return row;
};
const stepHtml = (s, n) => `<b>${n}.</b> ${esc(s.desc)} ${s.result === "skipped" ? "<span class='muted'>(skipped)</span>" : ""}`
  + (s.thought ? `<div class="muted small">${esc(s.thought)}</div>` : "");

function setWhere(w) {
  where = w; store.set("cuWhere", w);
  $("cuWhere").querySelectorAll("button").forEach(b => b.classList.toggle("on", b.dataset.w === w));
  $("cuHint").textContent = w === "browser"
    ? "Works in the app's own browser (on the right): your desktop isn't touched and this window stays open."
    : "Works on your real screen with the mouse and keyboard: this window shrinks into a small panel in the corner (you approve each step there) and comes back when it's done.";
  $("cuTask").placeholder = w === "browser" ? "Find the opening hours of the Cluj botanical garden" : "Open Notepad and write a shopping list: milk, eggs, bread";
}
function setView(v) {
  view = v;
  $("cuView").querySelectorAll("button").forEach(b => b.classList.toggle("on", b.dataset.v === v));
  $("vBrowser").hidden = v !== "browser"; $("vScreen").hidden = v !== "screen"; $("vTasks").hidden = v !== "tasks";
  if (v === "browser") pump();
  if (v === "tasks") refreshTasks();  // ⏳ Background tasks: the list of everything working on its own
}

async function load() {
  const [tasks, vision] = await Promise.all([api("/api/computer/tasks"), api("/api/models/vision")]);
  const m = vision.installed.find(x => x.active);
  $("cuModel").textContent = m ? m.name : "none — get one in Models › Computer use";
  const t = tasks[0];
  clearTimeout(timer);
  if (!t) { $("cuLive").hidden = true; return; }
  taskId = t.id;
  $("cuLive").hidden = false;
  const live = LIVE.includes(t.status);
  if (live && t.target !== lastTarget) setView(t.target === "browser" ? "browser" : "screen");  // follow what the AI uses
  lastTarget = live ? t.target : "";
  $("cuStatus").textContent = `${t.target === "browser" ? "🌐" : "🖥"} ${LABEL[t.status] || t.status} — ${t.goal}`;
  $("cuStop").hidden = !live;
  if (t.target !== "browser") $("cuShot").src = `/media/${t.shot}?t=${Date.now()}`;
  const p = t.pending;
  $("cuMark").hidden = !(p && p.x != null && t.target !== "browser" && ["click", "double_click", "right_click"].includes(p.action));
  if (p && p.x != null) { $("cuMark").style.left = p.x / 10 + "%"; $("cuMark").style.top = p.y / 10 + "%"; }
  const box = $("cuProposal");
  box.innerHTML = "";
  if (t.status === "waiting" && p) {
    const prop = el("div", "proposal", `<div><b class="mono">Next step:</b> ${esc(p.desc)}</div><div class="muted small">${esc(p.thought || "")}</div>`);
    prop.append(decideRow(t, load)); box.append(prop);
  } else if (t.error) box.append(el("div", "notice", esc(t.error)));
  const steps = $("cuSteps");
  steps.innerHTML = t.steps.length ? "" : `<div class="muted small">${live ? "Looking at the first step…" : "No steps."}</div>`;
  t.steps.forEach((s, i) => steps.append(el("div", "step", stepHtml(s, i + 1))));
  steps.scrollTop = steps.scrollHeight;
  if (live) timer = setTimeout(() => { if (visible()) load(); }, 1200);
}

$("cuWhere").onclick = e => { const b = e.target.closest("button"); if (b) setWhere(b.dataset.w); };
$("cuView").onclick = e => { const b = e.target.closest("button"); if (b) setView(b.dataset.v); };
$("cuGo").onclick = async () => {
  const task = $("cuTask").value.trim();
  if (!task) return $("cuTask").focus();
  try { await api("/api/computer/start", json("POST", { task, target: where })); $("cuTask").value = ""; load(); }
  catch (e) { alert(e.message); }
};
$("cuTask").addEventListener("keydown", e => { if (e.key === "Enter") $("cuGo").click(); });
$("cuStop").onclick = async () => { if (taskId) { await api(`/api/computer/${taskId}/stop`, { method: "POST" }); load(); } };

// ---------- the app's own browser: live picture of the shown tab, your clicks / wheel / keys go into it
let pumping = false, shotUrl = null, state = { running: false, tabs: [] }, lastState = 0;
async function refreshState() {
  try { state = await api("/api/browser"); } catch { state = { running: false, tabs: [] }; }
  lastState = Date.now();
  $("bTor").checked = state.running ? state.tor : $("bTor").checked;
  const tabs = $("bTabs"); tabs.innerHTML = "";
  for (const t of state.tabs) {
    const b = el("div", "btab" + (t.active ? " on" : ""), `<span>${esc(t.title || "New tab")}</span><i title="Close tab">×</i>`);
    b.title = t.url;
    b.onclick = async ev => {
      await api(`/api/browser/tab/${t.id}/${ev.target.tagName === "I" ? "close" : "show"}`, { method: "POST" }).catch(() => {});
      refreshState();
    };
    tabs.append(b);
  }
  tabs.append(button("+", "sm ghost", () => open("", true)));
  const act = state.tabs.find(t => t.active);
  if (act && document.activeElement !== $("bUrl")) $("bUrl").value = act.url === "about:blank" ? "" : act.url;
  $("bEmpty").hidden = state.running; $("bImg").hidden = !state.running;
}
async function pump() {
  if (pumping) return;
  pumping = true;
  try {
    while (visible() && view === "browser") {
      if (Date.now() - lastState > 1500) await refreshState();
      if (state.running && state.tabs.length) {
        try {
          const r = await fetch("/api/browser/shot", { cache: "no-store" });
          if (r.ok) { const u = URL.createObjectURL(await r.blob()); $("bImg").src = u; if (shotUrl) URL.revokeObjectURL(shotUrl); shotUrl = u; }
        } catch {}
        await new Promise(res => setTimeout(res, 350));
      } else await new Promise(res => setTimeout(res, 1500));
    }
  } finally { pumping = false; }
}
async function open(url, newTab = false) {
  $("bEmpty").textContent = $("bTor").checked ? "Starting the browser through Tor… (the first time ~20 s)" : "Starting the browser…";
  try { await api("/api/browser/open", json("POST", { url, new_tab: newTab, tor: $("bTor").checked })); }
  catch (e) { $("bEmpty").textContent = e.message; }
  await refreshState(); pump();
}
const input = body => api("/api/browser/input", json("POST", body)).catch(() => {});
const at = e => { const r = $("bImg").getBoundingClientRect(); return { x: (e.clientX - r.left) / r.width, y: (e.clientY - r.top) / r.height }; };

$("bUrl").addEventListener("keydown", e => { if (e.key === "Enter") { open($("bUrl").value); $("bView").focus(); } });
$("bBack").onclick = () => api("/api/browser/nav/back", { method: "POST" }).catch(() => {});
$("bFwd").onclick = () => api("/api/browser/nav/forward", { method: "POST" }).catch(() => {});
$("bReload").onclick = () => api("/api/browser/nav/reload", { method: "POST" }).catch(() => {});
$("bTor").onchange = () => { if (state.running) open(null); };
$("bClear").onclick = async () => {
  if (!confirm("Close the app's browser and delete its cookies, history and logins?")) return;
  await api("/api/browser/clear", { method: "POST" }).catch(e => alert(e.message)); refreshState();
};
$("bView").addEventListener("mousedown", e => { if (e.target === $("bImg")) { $("bView").focus(); e.preventDefault(); } });
$("bImg").addEventListener("click", e => input({ type: "click", ...at(e) }));
$("bImg").addEventListener("dblclick", e => input({ type: "click", count: 2, ...at(e) }));
$("bImg").addEventListener("contextmenu", e => { e.preventDefault(); input({ type: "click", button: "right", ...at(e) }); });
let wheelT = 0, wheelDy = 0;
$("bView").addEventListener("wheel", e => {
  e.preventDefault(); wheelDy += e.deltaY;
  if (wheelT) return;
  const p = at(e);
  wheelT = setTimeout(() => { input({ type: "scroll", ...p, dy: wheelDy }); wheelDy = 0; wheelT = 0; }, 80);
}, { passive: false });
let typed = "", typeT = 0;
const flush = () => { if (typed) input({ type: "text", text: typed }); typed = ""; typeT = 0; };
$("bView").addEventListener("keydown", e => {
  if (e.key.length === 1 && !e.ctrlKey && !e.metaKey && !e.altKey) {  // letters are sent in small batches
    typed += e.key; clearTimeout(typeT); typeT = setTimeout(flush, 120); e.preventDefault(); return;
  }
  const named = { Enter: "enter", Backspace: "backspace", Tab: "tab", Escape: "escape", Delete: "delete", ArrowUp: "up",
    ArrowDown: "down", ArrowLeft: "left", ArrowRight: "right", Home: "home", End: "end", PageUp: "pageup", PageDown: "pagedown" }[e.key];
  const combo = (e.ctrlKey || e.metaKey) && e.key.length === 1 ? `ctrl+${e.key.toLowerCase()}` : named;
  if (!combo) return;
  e.preventDefault(); flush(); input({ type: "key", key: (e.shiftKey && named === "tab" ? "shift+" : "") + combo });
});

/** A live computer-use card for the CHAT: status, the latest picture, approve / skip / stop — you stay in the chat. */
export function liveCard(id) {
  const card = el("div", "cucard");
  const head = el("div", "row"), status = el("b", "grow", "Starting…"), img = el("img"), prop = el("div"), last = el("div", "muted small");
  img.hidden = true;
  const stop = button("Stop", "sm danger", async () => { await api(`/api/computer/${id}/stop`, { method: "POST" }).catch(() => {}); tick(); });
  head.append(status, stop, button("Open Computer use", "sm ghost", () => show("computer")));
  card.append(head, img, prop, last);
  async function tick() {
    if (!card.isConnected && card.dataset.seen) return;  // the chat moved on: stop asking
    if (card.isConnected) card.dataset.seen = "1";
    let t;
    try { t = (await api("/api/computer/tasks")).find(x => x.id === id); } catch {}
    if (!t) { setTimeout(tick, 2000); return; }
    const live = LIVE.includes(t.status);
    status.textContent = `${t.target === "browser" ? "🌐" : "🖥"} ${LABEL[t.status] || t.status} — step ${t.steps.length}`;
    stop.hidden = !live;
    if (t.shot) { img.src = `/media/${t.shot}?t=${t.steps.length}`; img.hidden = false; }
    prop.innerHTML = "";
    if (t.status === "waiting" && t.pending) {
      prop.append(el("div", null, `<b>Next:</b> ${esc(t.pending.desc)} <span class="muted small">${esc(t.pending.thought || "")}</span>`), decideRow(t, tick));
    } else if (t.error) prop.append(el("div", "notice", esc(t.error)));
    const s = t.steps[t.steps.length - 1];
    last.innerHTML = s ? stepHtml(s, t.steps.length) : "";
    if (live) setTimeout(tick, 1500);
  }
  tick();
  return card;
}

onPage("computer", () => { setWhere(where); setView(view); load(); refreshState(); });
