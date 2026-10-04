import { $, api, button, el, esc, gb, json, onPage } from "./core.js";

async function load() {
  const [s, st, h] = await Promise.all([api("/api/settings"), api("/api/storage"), api("/api/health")]);
  $("version").textContent = `Local AI ${h.version} · everything runs on this PC`;
  $("sysPrompt").value = s.system_prompt;
  $("ctx").value = String(s.ctx);
  $("temp").value = s.temperature;
  $("allowWeb").checked = !!s.allow_web;
  $("laya").checked = s.laya !== false;
  $("proxy").value = s.web_proxy || "";
  $("torOn").checked = s.tor !== false;
  torState();
  $("folders").innerHTML = "";
  s.model_dirs.forEach((f, i) => {
    const r = el("div", "job", `<div class="top"><span class="p mono">${esc(f)}</span></div>`);
    if (i > 0) r.firstChild.append(button("Remove", "sm danger", async () => {
      await api("/api/settings", json("PUT", { model_dirs: s.model_dirs.filter(x => x !== f) })); load();
    }));
    $("folders").append(r);
  });
  const files = await api("/api/storage/files");
  $("modelFiles").innerHTML = files.length ? "" : `<div class="muted small">Empty — models you download appear here.</div>`;
  for (const f of files) {
    const bad = f.what === "Not used by the app" || f.what === "Unfinished download";
    const r = el("div", "job", `<div class="top"><span class="p mono small">${esc(f.folder)} / ${esc(f.name)}</span>
      <span class="small mono ${bad ? "notice" : "muted"}">${esc(f.what)} · ${gb(f.size)}</span></div>`);
    r.firstChild.append(button("Delete", "sm danger", async () => {
      if (!confirm(`Delete ${f.name} (${gb(f.size)})?`)) return;
      try { await api("/api/models/file?path=" + encodeURIComponent(f.path), { method: "DELETE" }); } catch (e) { alert(e.message); }
      load();
    }));
    $("modelFiles").append(r);
  }
  $("disk").innerHTML = `<div class="bar"><i style="width:${Math.round((1 - st.disk.free / st.disk.total) * 100)}%"></i></div>
    <div class="muted small mono">${gb(st.disk.free)} free of ${gb(st.disk.total)} · app models ${gb(st.models)} · gallery ${gb(st.media)}</div>`;
}
const saved = (b) => { const t = b.textContent; b.textContent = "Saved ✓"; setTimeout(() => b.textContent = t, 1200); };
async function saveWith(b, fn) {  // a failed save says so (before, nothing happened)
  b.disabled = true;
  try { await fn(); saved(b); } catch (e) { alert("Couldn't save: " + e.message); }
  b.disabled = false;
}
$("saveAssistant").onclick = () => saveWith($("saveAssistant"), async () => {
  const before = (await api("/api/settings")).ctx;
  await api("/api/settings", json("PUT", { system_prompt: $("sysPrompt").value, ctx: +$("ctx").value, temperature: +$("temp").value }));
  if (before !== +$("ctx").value) await api("/api/llm/unload", { method: "POST" });  // new memory length: reload
});
$("saveLaya").onclick = () => saveWith($("saveLaya"), () => api("/api/settings", json("PUT", { laya: $("laya").checked })));
$("saveWeb").onclick = () => saveWith($("saveWeb"), () => api("/api/settings", json("PUT", { allow_web: $("allowWeb").checked, tor: $("torOn").checked, web_proxy: $("proxy").value.trim() })));
$("allowWeb").onchange = () => $("saveWeb").click();
$("torOn").onchange = () => { $("saveWeb").click(); setTimeout(torState, 800); };
let torT;
async function torState() {  // "connecting 45%" -> "connected"
  clearTimeout(torT);
  const t = await api("/api/tor").catch(() => null);
  if (!t) return;
  $("torState").textContent = !t.available ? "— Tor is missing from engines\\tor" : !t.on ? (t.running ? "" : "— off") :
    t.progress >= 100 ? "— connected" : `— connecting ${t.progress}%`;
  if (t.on && t.progress < 100 && document.getElementById("p-settings")?.offsetParent) torT = setTimeout(torState, 1500);
}
$("folderAdd").onclick = async () => {
  const f = $("folderIn").value.trim(); if (!f) return;
  const s = await api("/api/settings");
  if (!s.model_dirs.includes(f)) await api("/api/settings", json("PUT", { model_dirs: [...s.model_dirs, f] }));
  $("folderIn").value = ""; load();
};
document.querySelectorAll("[data-open]").forEach(b => b.onclick = () => api("/api/storage/open", json("POST", { what: b.dataset.open })));
$("unload").onclick = async () => { await api("/api/llm/unload", { method: "POST" }); saved($("unload")); };
$("importOld").onclick = async () => {
  try { const r = await api("/api/import-v01", { method: "POST" }); alert(`Imported ${r.chats} chats, ${r.facts} memories and ${r.media} gallery files.`); }
  catch (e) { alert(e.message); }
};
// ---------- Security: what the AI may do (fixed in the app — the AI can't change it), attack tests, the log
const LEVEL = { green: "🟢 allowed", yellow: "🟡 asks / only what you added", red: "🔴 asks before every step" };
async function loadSecurity() {
  let s;
  try { s = await api("/api/security"); } catch { return; }
  $("secPolicy").innerHTML = `<div class="sectable">${s.policy.map(p => `<div><span class="mono">${esc(p.tool)}</span>`
    + `<span>${LEVEL[p.level] || esc(p.level)}</span><span class="muted small">${esc(p.rule)}</span></div>`).join("")}</div>`
    + `<div class="muted small" style="margin-top:8px">🚫 The AI can never: ${esc(s.never.join(" · "))}.</div>`;
  $("secSum").textContent = `Sandbox: ${s.files} file(s) · ${s.recent.length} recent security event(s)`;
  $("secLog").innerHTML = s.recent.length ? s.recent.map(e => `<div>${esc(e.time)} · <b>${esc(e.event)}</b> `
    + `${esc(Object.entries(e).filter(([k]) => !["time", "event"].includes(k)).map(([k, v]) => `${k}=${typeof v === "string" ? v : JSON.stringify(v)}`).join(" ").slice(0, 260))}</div>`).join("")
    : `<div class="muted">Nothing yet.</div>`;
}
$("secTest").onclick = async () => {
  const b = $("secTest"); b.disabled = true; b.textContent = "Attacking the app…";
  try {
    const { results } = await api("/api/security/test", { method: "POST" });
    const ok = results.filter(r => r.pass).length;
    $("secTests").innerHTML = `<div class="${ok === results.length ? "" : "notice"}"><b>${ok} of ${results.length} attacks stopped</b></div>`
      + results.map(r => `<div class="small">${r.pass ? "✅" : "❌"} ${esc(r.test)}${r.detail ? ` <span class="muted">— ${esc(r.detail.slice(0, 160))}</span>` : ""}</div>`).join("");
    loadSecurity();
  } catch (e) { alert(e.message); }
  b.disabled = false; b.textContent = "Run attack tests";
};
// ---------- This PC: the setup check (opens by itself once after a move / on a new PC)
const MARK = { ok: "✅", warn: "🟡", bad: "❌" };
const FIX = { shortcut: "Create the desktop + Start menu shortcut", drop_dirs: "Forget the missing folders" };
function paintSetup(r) {
  $("setupList").innerHTML = "";
  for (const i of r.items) {
    const row = el("div", `srow ${i.state}`, `<span>${MARK[i.state]}</span><b>${esc(i.name)}</b><span class="muted small">${esc(i.detail)}`
      + `${i.hint ? ` — <i>${esc(i.hint)}</i>` : ""}</span>`);
    if (i.fix) row.append(button(FIX[i.fix] || "Fix", "sm primary", async () => {
      try { paintSetup((await api(`/api/setup/${i.fix}`, { method: "POST" })).check); } catch (e) { alert(e.message); }
    }));
    $("setupList").append(row);
  }
  $("setupSum").textContent = r.bad ? `${r.bad} thing(s) to fix, ${r.warn} note(s)` : r.warn ? `Works — ${r.warn} note(s)` : "Everything is ready on this PC";
  if (r.pending) {
    $("setupBanner").hidden = false;
    $("setupBanner").innerHTML = (r.moved_from ? `The app folder moved (from ${esc(r.moved_from)}) — its saved paths were updated. ` : "")
      + "This looks like a new place or a new PC: here is what works and what to fix. ";
    $("setupBanner").append(button("Got it", "sm", async () => { await api("/api/setup/seen", { method: "POST" }); $("setupBanner").hidden = true; }));
  }
}
async function loadSetup() {
  $("setupSum").textContent = "Checking this PC…";
  try { paintSetup(await api("/api/setup")); } catch (e) { $("setupSum").textContent = e.message; }
}
$("setupRecheck").onclick = loadSetup;
onPage("settings", () => { load(); loadSecurity(); loadSetup(); });  // one loader per page (a second onPage replaces the first)
