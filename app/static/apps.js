import { $, api, button, el, esc, json, onPage } from "./core.js";
import { watchTask } from "./tasks.js";

// ---------- the app maker: describe -> the local AI writes one HTML file -> it runs sealed in the frame -> change it
let current = null, making = false;

function busy(on, text = "") {
  making = on;
  $("appMake").disabled = on; $("appChangeGo").disabled = on; $("appStop").hidden = !on;
  $("appStatus").textContent = text;
}

async function list() {
  let r;
  try { r = await api("/api/apps"); } catch { return; }
  const box = $("appList"); box.innerHTML = "";
  if (!r.apps.length) box.append(el("div", "muted small", "None yet — describe one above."));
  for (const a of r.apps) {
    const row = el("div", "mrow approw" + (current?.id === a.id ? " on" : ""),
      `<span class="grow">${esc(a.name)}</span><span class="muted small">v${a.versions || 1}</span>`);
    row.onclick = () => open(a.id);
    row.append(button("✕", "sm ghost", async ev => {
      ev.stopPropagation();
      if (!confirm(`Delete “${a.name}”?`)) return;
      await api(`/api/apps/${a.id}`, { method: "DELETE" }).catch(e => alert(e.message));
      if (current?.id === a.id) showApp(null);
      list();
    }));
    box.append(row);
  }
  if (r.making.length && !making) busy(true, "An app is being made…");
}

function showApp(a) {
  current = a;
  $("appTitle").textContent = a ? a.name : "No app open";
  for (const id of ["appFull", "appCodeBtn", "appSave", "appExport", "appChangeRow"]) $(id).hidden = !a;
  $("appReceipt").textContent = a ? (a.receipt || "") + ((a.exports || []).length ? ` · 📁 ${a.exports[a.exports.length - 1]}` : "") : "";
  $("appUndo").hidden = !a || (a.versions || 1) < 2;
  $("appFrame").srcdoc = a ? a.sealed : "";
  $("appCode").textContent = a ? a.html : "";
  $("appCode").hidden = true; $("appFrame").hidden = false;
}

async function open(id) {
  try { showApp(await api(`/api/apps/${id}`)); } catch (e) { alert(e.message); }
  list();
}

let pending = null;  // the background job this page waits for
async function make(prompt, id) {
  let job;
  try { job = await api("/api/apps/jobs", json("POST", { prompt, id })); } catch (e) { return busy(false, e.message); }
  pending = job.id; watchTask(job.id);
  busy(true, `${id ? "Changing the app" : "Making the app"} in the background (writing → checking the code → using it in the `
    + "browser → fixing). Use other pages meanwhile — it opens here when it's ready (⏳ Background tasks).");
}
window.addEventListener("task-done", e => {  // our background job finished (tasks.js noticed)
  const t = e.detail;
  if (t.id !== pending) return;
  pending = null;
  busy(false, t.status === "done" ? `Done — ${t.note || "try it on the right"}.` : t.status === "failed" ? t.error || "It failed" : "Stopped");
  if (t.open?.app) open(t.open.app); else list();
});

$("appMake").onclick = () => {
  const p = $("appPrompt").value.trim();
  if (!p) return $("appPrompt").focus();
  make(p, null); $("appPrompt").value = "";
};
$("appChangeGo").onclick = () => {
  const p = $("appChange").value.trim();
  if (!p || !current) return $("appChange").focus();
  make(p, current.id); $("appChange").value = "";
};
$("appChange").addEventListener("keydown", e => { if (e.key === "Enter") $("appChangeGo").click(); });
$("appStop").onclick = () => api(pending ? `/api/tasks/${pending}/stop` : "/api/apps/stop", { method: "POST" }).catch(() => {});
$("appCodeBtn").onclick = () => { const code = $("appCode").hidden; $("appCode").hidden = !code; $("appFrame").hidden = code; };
$("appFull").onclick = () => $("appFrame").requestFullscreen?.();
$("appUndo").onclick = async () => {
  if (!current || !confirm("Go back to the version before the last change?")) return;
  try { showApp(await api(`/api/apps/${current.id}/undo`, { method: "POST" })); } catch (e) { alert(e.message); }
  list();
};
$("appSave").onclick = () => {
  if (!current) return;
  const a = el("a"); a.href = URL.createObjectURL(new Blob([current.html], { type: "text/html" }));
  a.download = (current.name.replace(/[^\w\- ]+/g, "").trim() || "app") + ".html"; a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 2000);
};

$("appExport").onclick = async () => {
  if (!current) return;
  const name = prompt("Folder name on your Desktop (a new folder — nothing is overwritten):", current.name);
  if (!name) return;
  try {
    const r = await api(`/api/apps/${current.id}/export`, json("POST", { name }));
    if (confirm(`Saved in ${r.folder}\n\nOpen the folder?`)) await api(`/api/apps/${current.id}/open-folder`, { method: "POST" });
    open(current.id);
  } catch (e) { alert(e.message); }
};
window.addEventListener("open-app", e => open(e.detail));  // "Open in Apps" on a chat's app card

onPage("apps", list);
