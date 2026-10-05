import { $, api, button, el, esc, json, onPage } from "./core.js";
import { watchTask } from "./tasks.js";

// ---------- the Forge: new skills the local AI writes for itself — sandboxed drafts you try, then turn on (or not)
let current = null, making = false;

function busy(on, text = "") {
  making = on;
  $("forgeMake").disabled = on; $("forgeChangeGo").disabled = on; $("forgeStop").hidden = !on;
  $("forgeStatus").textContent = text;
}

async function list() {
  let r;
  try { r = await api("/api/forge"); } catch { return; }
  const box = $("forgeList"); box.innerHTML = "";
  if (!r.skills.length) box.append(el("div", "muted small", "None yet — describe one above."));
  for (const k of r.skills) {
    const on = k.active ? `<span class="chip ok">on · v${k.active}</span>` : `<span class="chip">draft</span>`;
    const row = el("div", "mrow approw" + (current?.id === k.id ? " on" : ""), `<span class="grow">${esc(k.name)}</span>${on}`);
    row.onclick = () => open(k.id);
    box.append(row);
  }
  if (r.making.length && !making) busy(true, "A skill is being made…");
}

function inputsFor(k) {
  const box = $("forgeInputs"); box.innerHTML = "";
  for (const [name, spec] of Object.entries(k.inputs || {})) {
    const t = spec.type === "boolean" ? "checkbox" : spec.type === "number" || spec.type === "integer" ? "number" : "text";
    const lab = el("label", "forge-input", `<span>${esc(name)}<span class="muted small"> — ${esc(spec.description || "")}</span></span>`);
    const inp = el("input"); inp.type = t; inp.dataset.name = name; inp.dataset.kind = spec.type || "string";
    if (t === "checkbox") inp.checked = !!spec.default; else if (spec.default !== undefined) inp.value = spec.default;
    if (t === "number") inp.step = "any";
    lab.append(inp); box.append(lab);
  }
}

function params() {
  const out = {};
  $("forgeInputs").querySelectorAll("input").forEach(i => {
    if (i.type === "checkbox") out[i.dataset.name] = i.checked;
    else if (i.value !== "") out[i.dataset.name] = i.dataset.kind === "number" || i.dataset.kind === "integer" ? Number(i.value) : i.value;
  });
  return out;
}

function showSkill(k) {
  current = k;
  $("forgeTitle").textContent = k ? k.name : "No skill open";
  for (const id of ["forgeCodeBtn", "forgeDel", "forgeRunRow", "forgeChangeRow"]) $(id).hidden = !k;
  $("forgeOut").hidden = true; $("forgeCode").hidden = true;
  if (!k) { $("forgeState").innerHTML = ""; $("forgeDesc").textContent = ""; $("forgeInputs").innerHTML = ""; $("forgeVersions").textContent = ""; return; }
  const newest = k.versions, passed = !!(k.tests || {})[String(newest)];
  $("forgeState").innerHTML = k.active === newest ? `<span class="chip ok">✓ On — the chat can use it (version ${newest})</span>`
    : k.active ? `<span class="chip ok">On: version ${k.active}</span> <span class="chip">version ${newest} is a draft — try it, then Turn on</span>`
    : `<span class="chip">Draft — the chat doesn't use it until you turn it on</span>`;
  $("forgeDesc").innerHTML = `${esc(k.description || "")}<br><span class="${passed ? "" : "fitbad"}">Self-test: ${esc(k.receipt || "")}</span>`;
  inputsFor(k);
  $("forgeOn").hidden = k.active === newest || !passed;
  $("forgeOn").textContent = k.active ? `Turn on version ${newest}` : "Turn on";
  $("forgeOff").hidden = !k.active;
  $("forgeUndo").hidden = newest < 2;
  $("forgeCode").textContent = k.code;
  const vs = [];
  for (let v = newest; v >= 1 && vs.length < 8; v--) vs.push(v);
  const vbox = $("forgeVersions"); vbox.innerHTML = `Versions (each one kept as a backup): `;
  vs.forEach(v => {
    const ok = (k.tests || {})[String(v)];
    const b = button(`v${v}${v === k.active ? " ✓" : ""}`, "sm ghost" + (ok ? "" : " fitbad"), async () => {
      if (v === k.active || !ok) return;
      if (!confirm(`Use version ${v} in the chat?`)) return;
      try { showSkill(await api(`/api/forge/${k.id}/on`, json("POST", { version: v }))); } catch (e) { alert(e.message); }
      list();
    });
    b.title = ok ? (v === k.active ? "This version is on" : "Turn this version on") : "It didn't pass its self-test";
    vbox.append(b);
  });
}

async function open(id) {
  try { showSkill(await api(`/api/forge/${id}`)); } catch (e) { alert(e.message); }
  list();
}

let pending = null;  // the background job this page waits for
async function make(prompt, id) {
  let job;
  try { job = await api("/api/forge/jobs", json("POST", { prompt, id })); } catch (e) { return busy(false, e.message); }
  pending = job.id; watchTask(job.id);
  busy(true, `${id ? "Changing the skill" : "Making the skill"} in the background (writing → code check → self-test in the `
    + "sandbox → fixing). Use other pages meanwhile — it opens here when it's ready (⏳ Background tasks).");
}
window.addEventListener("task-done", e => {  // our background job finished (tasks.js noticed)
  const t = e.detail;
  if (t.id !== pending) return;
  pending = null;
  busy(false, t.status === "done" ? `Done — ${t.note || "try it on the right"}.` : t.status === "failed" ? t.error || "It failed" : "Stopped");
  if (t.open?.skill) open(t.open.skill); else list();
});

$("forgeMake").onclick = () => {
  const p = $("forgePrompt").value.trim();
  if (!p) return $("forgePrompt").focus();
  make(p, null); $("forgePrompt").value = "";
};
$("forgeChangeGo").onclick = () => {
  const p = $("forgeChange").value.trim();
  if (!p || !current) return $("forgeChange").focus();
  make(p, current.id); $("forgeChange").value = "";
};
$("forgeChange").addEventListener("keydown", e => { if (e.key === "Enter") $("forgeChangeGo").click(); });
$("forgeStop").onclick = () => api(pending ? `/api/tasks/${pending}/stop` : "/api/forge/stop", { method: "POST" }).catch(() => {});
$("forgeCodeBtn").onclick = () => { $("forgeCode").hidden = !$("forgeCode").hidden; };
$("forgeRun").onclick = async () => {
  if (!current) return;
  const out = $("forgeOut"); out.hidden = false; out.textContent = "Running in the sandbox…";
  try {
    const r = await api(`/api/forge/${current.id}/run`, json("POST", { params: params() }));
    out.textContent = (r.ok ? JSON.stringify(r.result, null, 2) : "✕ " + r.error) + (r.printed ? `\n\nprinted:\n${r.printed}` : "")
      + `\n\n(${r.seconds ?? "?"} s in the sandbox)`;
  } catch (e) { out.textContent = "✕ " + e.message; }
};
$("forgeOn").onclick = async () => {
  if (!current) return;
  try { showSkill(await api(`/api/forge/${current.id}/on`, json("POST", {}))); } catch (e) { alert(e.message); }
  list();
};
$("forgeOff").onclick = async () => {
  if (!current) return;
  try { showSkill(await api(`/api/forge/${current.id}/off`, { method: "POST" })); } catch (e) { alert(e.message); }
  list();
};
$("forgeUndo").onclick = async () => {
  if (!current || !confirm("Remove the newest version and go back to the one before it?")) return;
  try { showSkill(await api(`/api/forge/${current.id}/undo`, { method: "POST" })); } catch (e) { alert(e.message); }
  list();
};
$("forgeDel").onclick = async () => {
  if (!current || !confirm(`Delete the skill “${current.name}” and all its versions?`)) return;
  await api(`/api/forge/${current.id}`, { method: "DELETE" }).catch(e => alert(e.message));
  showSkill(null); list();
};
window.addEventListener("open-skill", e => open(e.detail));  // "Open in Forge" on a chat's skill card

onPage("forge", list);
