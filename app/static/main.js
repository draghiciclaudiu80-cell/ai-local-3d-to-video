import { $, api, esc, json, mmss, show, store } from "./core.js";
import { initChat } from "./chat.js";
import "./create.js";
import "./gallery.js";
import "./computer.js";
import "./memory.js";
import "./models.js";
import "./settings.js";

// ---------- updated while open: the window keeps running its old page code until it reloads (Ctrl+click
// multi-select "didn't work" — it wasn't loaded yet). A bar offers the reload; nothing reloads by itself (unsaved work).
const pageVer = (import.meta.url.match(/\/v\/(\d+)\//) || [])[1];
if (pageVer) setInterval(async () => {
  if (document.getElementById("updbar")) return;
  try {
    const { v } = await (await fetch("/api/page_version")).json();
    if (v && v !== pageVer) {
      const bar = document.createElement("div");
      bar.id = "updbar";
      bar.innerHTML = `<span>🔄 The app was updated.</span><button class="btn sm primary">Reload</button><button class="btn sm ghost">Later</button>`;
      bar.querySelector(".primary").onclick = () => location.reload();
      bar.querySelector(".ghost").onclick = () => bar.remove();
      document.body.append(bar);
    }
  } catch { /* the app is restarting: next time */ }
}, 30000);

// ---------- navigation
document.querySelectorAll("[data-p]").forEach(b => b.addEventListener("click", () => show(b.dataset.p)));

// ---------- theme: system -> light -> dark
const THEMES = ["system", "light", "dark"];
function applyTheme(t) {
  if (t === "system") delete document.documentElement.dataset.theme; else document.documentElement.dataset.theme = t;
  $("themeText").textContent = "Theme: " + t[0].toUpperCase() + t.slice(1);
}
$("themeBtn").onclick = () => {
  const next = THEMES[(THEMES.indexOf(store.get("theme", "system")) + 1) % 3];
  store.set("theme", next); applyTheme(next);
};
applyTheme(store.get("theme", "system"));

// ---------- model status (bottom-left) + app-offline guard
let setupShown = false;
async function health() {
  try {
    const h = await api("/api/health");
    const l = h.llm;
    const only = h.laya?.only;  // "Laya only": the main model is off, Laya writes the answers
    $("llmDot").className = "dot" + (l.running ? (only ? " laya" : l.gpu ? " on" : " cpu") : "");
    $("llmText").textContent = only ? (l.running ? "Small model only · main model off" : "Small model only · loads when you chat")
      : l.running ? `${l.model}${l.gpu ? "" : " · CPU"}` : "Model idle";
    $("llmStatus").title = l.running ? `Loaded: ${l.model} (${l.gpu ? "graphics card" : "processor, while a render runs"})` : "Loads when you chat";
    $("chatModel").textContent = only ? "Small model (Qwen3 1.7B)" : l.running ? l.model : "";
    const m3 = h.making3d || [];  // 3D designs / builds count too (they said "Nothing is being made")
    $("stopAll").classList.toggle("on", !!(h.rendering || m3.length));
    const aw = h.awake?.on;  // the app keeps the PC out of idle sleep while it works (it slept after 3 min and froze a job)
    $("stopAllText").textContent = (h.rendering || m3.length ? "Stop everything" : aw ? "☕ Working" : "Nothing is being made")
      + (aw ? " · PC kept awake" : "");
    $("stopAll").title = [...m3.map(x => "🧊 " + x.text), ...(aw ? ["☕ The PC won't go to sleep while it's " + h.awake.why.join(", ")
      + " (the screen may turn off; the power button still sleeps it)"] : [])].join(" · ");
    layaShow(h.laya);
    // Linux: computer use isn't available (Wayland lets no app see / control the screen) — its menu item goes
    document.querySelector('nav [data-p="computer"], [data-p="computer"]')?.toggleAttribute("hidden", h.platform === "linux");
    if (h.setup_pending && !setupShown) {  // moved / new PC: the setup check opens once by itself
      setupShown = true;
      show("settings");
      setTimeout(() => $("setupCard")?.scrollIntoView({ block: "start" }), 400);
    }
  } catch {
    $("llmDot").className = "dot"; $("llmText").textContent = "App not running";
  }
}
setInterval(() => { if (!document.hidden) health(); }, 5000);
// heartbeat, also while hidden: on Linux in a normal browser tab the app stops some minutes after the page is gone
setInterval(() => { fetch("/api/ping").catch(() => {}); }, 60000);

// ---------- Laya helper switch (experimental): Laya helps the main model on every message
function layaShow(l) {
  if (!l) return;
  $("layaBtn").classList.toggle("on", !!l.assist);
  $("layaBtn").dataset.on = l.assist ? "1" : "";
  $("layaText").textContent = !l.ok ? "Laya helper: model missing" : !l.assist ? "Laya helper: off"
    : l.running ? "Laya helper: on" : "Laya helper: on (starts with your next message)";
  $("layaOnly").classList.toggle("on", !!l.only);
  $("layaOnly").dataset.on = l.only ? "1" : "";
  $("layaOnlyText").textContent = !l.small_ok ? "Small model only: model missing" : l.only ? "Small model only: on (main model off)" : "Small model only: off";
}
$("layaOnly").onclick = async () => {  // chat with Laya instead of the main model
  const on = !$("layaOnly").dataset.on;
  $("layaOnly").classList.toggle("on", on); $("layaOnly").dataset.on = on ? "1" : "";
  $("layaOnlyText").textContent = on ? "Small model only: switching…" : "Small model only: off — main model loading…";
  await api("/api/settings", json("PUT", { laya_only: on }));
  setTimeout(health, 2000); setTimeout(health, 8000);
};
$("layaBtn").onclick = async () => {
  const on = !$("layaBtn").dataset.on;
  layaShow({ assist: on, running: false, ok: true });
  await api("/api/settings", json("PUT", { laya_assist: on }));
  setTimeout(health, 1500); setTimeout(health, 5000);
};

// ---------- live progress dock (every page)
let dockJob = null, dock3d = null;
async function dock() {
  let r;
  try { r = await api("/api/jobs"); } catch { return; }
  const run = r.jobs.find(j => j.status === "running");
  const mv = run?.movie ? r.movies.find(m => m.id === run.movie) : r.movies.find(m => ["rendering", "adding sound"].includes(m.status));
  const m3 = (r.making3d || [])[0];  // a 3D design / build: shown when no picture / video is being made
  $("dock").hidden = !run && !mv && !r.waiting && !m3;
  dockJob = run?.id || null;
  dock3d = !run && !mv && m3 ? m3.id : null;
  if ($("dock").hidden) return;
  if (dock3d) {
    $("dockWhat").textContent = $("dockWhat").title = "🧊 3D model";
    $("dockBar").style.width = Math.round(m3.pct * 100) + "%";
    $("dockPhase").textContent = m3.text;
    $("dockNums").textContent = `${Math.round(m3.pct * 100)}% · ${mmss(m3.elapsed)} elapsed`;
    $("dockCancel").hidden = false;
    return;
  }
  const scene = run && mv ? mv.jobs.indexOf(run.id) + 1 : 0;
  const what = run && mv ? `🎞 Movie “${mv.title}” — scene ${scene} of ${mv.scenes}: ${run.prompt}`
    : run ? `${run.kind === "video" ? "🎬" : "🖼"} ${run.prompt}` : mv ? `🎞 Movie “${mv.title}” — ${mv.status}` : "Starting…";
  $("dockWhat").textContent = what; $("dockWhat").title = what;
  const p = mv ? mv.progress : run ? run.progress : 0;
  $("dockBar").style.width = Math.round(p * 100) + "%";
  $("dockPhase").textContent = run ? `${run.note ? "⚠ " + run.note + " · " : ""}${run.phase || "Starting"}` : mv?.status || "";
  const nums = [`${Math.round(p * 100)}%`];
  if (run?.elapsed != null) nums.push(`${mmss(run.elapsed)} elapsed`);
  if (run?.eta != null) nums.push(`~${mmss(run.eta)} left${mv ? " for this scene" : ""}`);
  if (r.waiting) nums.push(`${r.waiting} waiting`);
  $("dockNums").textContent = nums.join(" · ");
  $("dockCancel").hidden = !run;
}
export async function stopEverything() {
  if (!confirm("Stop everything that's being made (pictures, videos, merges, movies, 3D models)?")) return;
  try { await api("/api/stop-all", { method: "POST" }); } catch (e) { alert(e.message); }
  health(); dock();
}
$("stopAll").onclick = stopEverything;
$("dockCancel").onclick = async () => {
  if (dock3d && confirm("Stop the 3D model that's being made?")) {
    await api(`/api/plugin-runs/${dock3d}/stop`, { method: "POST" }); dock(); health(); return;
  }
  if (dockJob && confirm("Stop what's being made right now? (For a movie: the whole movie stops.)")) {
    await api(`/api/jobs/${dockJob}`, { method: "DELETE" }); dock(); health();
  }
};
setInterval(() => { if (!document.hidden) dock(); }, 2000);

(async () => {
  await initChat();
  health(); dock();
  show(store.get("page", "chat"));
})();
