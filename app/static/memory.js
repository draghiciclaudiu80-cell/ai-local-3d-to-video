import { $, api, button, el, esc, json, onPage } from "./core.js";

// One line per item (the page was too crowded): icon, text, small note, a ✕ at the end.
// Skills and plugins live in the chat's Skills / Plugins menus only (the user's wish).
function line(icon, text, note, actions = []) {
  const r = el("div", "mrow", `<span class="mic">${icon}</span><span class="mtext">${esc(text)}</span>`
    + (note ? `<span class="muted small mnote">${esc(note)}</span>` : ""));
  r.append(...actions);
  return r;
}
function forget(title, onClick) {
  const b = button("✕", "sm ghost mx", onClick);
  b.title = title;
  return b;
}

// ---------- sandbox: downloaded files (never opened or run by the app)
function paintSandbox({ files }) {
  $("sbList").innerHTML = files.length ? "" : `<div class="muted small mempty">Empty. Downloads land here.</div>`;
  for (const f of files) {
    const kb = f.size > 1048576 ? `${(f.size / 1048576).toFixed(1)} MB` : `${Math.max(1, Math.round(f.size / 1024))} KB`;
    const acts = [];
    if (f.kind === "stl") acts.push(button("Show in 3D", "sm", async () => {
      try { await api(`/api/sandbox/${encodeURIComponent(f.name)}/show3d`, { method: "POST" }); alert("Added to Gallery › 3D."); } catch (e) { alert(e.message); }
    }));
    acts.push(forget("Delete for good", async () => {
      if (confirm(`Delete “${f.name}” for good?`)) paintSandbox(await api(`/api/sandbox/${encodeURIComponent(f.name)}`, { method: "DELETE" }));
    }));
    const r = line("📄", f.name, [kb, f.host ? "from " + f.host : "", f.flags?.length ? "⚠ " + f.flags.join(", ") : ""].filter(Boolean).join(" · "), acts);
    if (f.flags?.length) r.title = "Text inside tries to command an AI — it's only ever read as data";
    $("sbList").append(r);
  }
}
$("sbGet").onclick = async () => {
  const url = $("sbUrl").value.trim(); if (!url) return $("sbUrl").focus();
  const b = $("sbGet"); b.disabled = true; b.textContent = "Downloading…";
  try { const r = await api("/api/sandbox/download", json("POST", { url })); paintSandbox(r); $("sbUrl").value = ""; }
  catch (e) { alert(e.message); }
  b.disabled = false; b.textContent = "Download";
};
$("sbOpen").onclick = () => api("/api/sandbox/open", { method: "POST" }).catch(e => alert(e.message));

function paint({ facts, documents, persona, summaries, auto, meaning, lessons = [], rated = [] }) {
  $("persona").innerHTML = persona ? esc(persona)
    : `<span class="muted small">Not built yet — it's made from the facts below (automatically after chats).</span>`;
  $("memAuto").checked = auto !== false;
  const rules = facts.filter(f => f.kind === "rule"), about = facts.filter(f => f.kind !== "rule");
  const learned = about.filter(f => f.kind === "auto").length;
  $("memStats").textContent = `${about.length} facts (${learned} learned from chats) · ${rules.length} rules · ${lessons.length} lessons · `
    + `${summaries} long chat(s) summarized · meaning search ${meaning ? "on" : "off (model missing)"}`;
  const del = (f) => forget("Forget", async () => paint(await api(`/api/memory/${f.id}`, { method: "DELETE" })));
  const day = (t) => t ? new Date(t * 1000).toLocaleDateString() : "";
  $("nRules").textContent = `(${rules.length})`;
  $("rulesList").innerHTML = rules.length ? "" : `<div class="muted small mempty">None. Type “/rule …” in the chat.</div>`;
  for (const f of rules) $("rulesList").append(line("📌", f.text, "", [del(f)]));
  $("nFacts").textContent = `(${about.length})`;
  $("facts").innerHTML = about.length ? "" : `<div class="muted small mempty">Nothing yet. Tell the chat “remember …”, add it above, or just chat — it learns.</div>`;
  for (const f of about) $("facts").append(line(f.kind === "auto" ? "🧠" : "👤", f.text, `${f.kind === "auto" ? "learned" : "you said"} · ${day(f.created)}`, [del(f)]));
  $("nLessons").textContent = `(${lessons.length})`;
  $("lessonList").innerHTML = lessons.length ? "" : `<div class="muted small mempty">None yet: it saves one when a later try fixes what its test found.</div>`;
  for (const l of lessons) $("lessonList").append(line("💡", l.text, l.seen > 1 ? `seen ${l.seen}×` : "",
    [forget("Forget this lesson", async () => paint(await api(`/api/lessons/${l.id}`, { method: "DELETE" })))]));
  const good = rated.filter(r => r.rating > 0).length;
  $("nRated").textContent = `(${good} 👍 · ${rated.length - good} 👎)`;
  $("ratedList").innerHTML = rated.length ? "" : `<div class="muted small mempty">None yet. Press 👍 or 👎 under an answer: it's shown these on similar questions.</div>`;
  for (const r of rated) $("ratedList").append(line(r.rating > 0 ? "👍" : "👎", `${r.question || "(no question)"} → ${r.answer}`,
    [r.reason, day(r.created)].filter(Boolean).join(" · "),
    [forget("Forget this example", async () => paint(await api(`/api/feedback/${r.msg_id}`, { method: "DELETE" })))]));
  $("docs").innerHTML = documents.length ? "" : `<div class="muted small mempty">No documents yet.</div>`;
  for (const d of documents) $("docs").append(line("📄", d.name, `${(d.chars / 1000).toFixed(1)}k characters`,
    [forget("Remove", async () => paint(await api(`/api/documents/${d.id}`, { method: "DELETE" })))]));
}
$("factAdd").onclick = async () => {
  const text = $("factIn").value.trim(); if (!text) return;
  paint(await api("/api/memory", json("POST", { text }))); $("factIn").value = "";
};
$("factIn").onkeydown = (e) => { if (e.key === "Enter") $("factAdd").click(); };
$("docUp").onclick = async () => {
  for (const f of $("docFile").files) {
    const fd = new FormData(); fd.append("file", f);
    try { paint(await api("/api/documents", { method: "POST", body: fd })); } catch (e) { alert(f.name + ": " + e.message); }
  }
  $("docFile").value = "";
};
$("personaRebuild").onclick = async () => {
  const b = $("personaRebuild"); b.disabled = true; b.textContent = "Building…";
  try { paint(await api("/api/memory/persona", { method: "POST" })); } catch (e) { alert(e.message); }
  b.disabled = false; b.textContent = "Rebuild profile";
};
$("memAuto").onchange = async () => { await api("/api/settings", json("PUT", { memory_auto: $("memAuto").checked })); };
onPage("memory", async () => {
  paint(await api("/api/memory"));
  paintSandbox(await api("/api/sandbox"));
});
