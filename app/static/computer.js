import { $, api, button, el, esc, json, onPage } from "./core.js";

let timer, taskId = null;
const LABEL = { thinking: "Looking at the screen…", waiting: "Waiting for your OK", running: "Doing it…",
  done: "Finished ✓", failed: "Couldn't finish", stopped: "Stopped" };

async function load() {
  const [tasks, vision] = await Promise.all([api("/api/computer/tasks"), api("/api/models/vision")]);
  const m = vision.installed.find(x => x.active);
  $("cuModel").textContent = m ? m.name : "none — get one in Models › Computer use";
  const t = tasks[0];
  clearTimeout(timer);
  if (!t) { $("cuLive").hidden = true; return; }
  taskId = t.id;
  $("cuLive").hidden = false;
  const live = ["thinking", "waiting", "running"].includes(t.status);
  $("cuStatus").textContent = `${LABEL[t.status] || t.status} — ${t.goal}`;
  $("cuStop").hidden = !live;
  $("cuShot").src = `/media/${t.shot}?t=${Date.now()}`;
  const p = t.pending;
  $("cuMark").hidden = !(p && p.x != null && ["click", "double_click", "right_click"].includes(p.action));
  if (p && p.x != null) { $("cuMark").style.left = p.x / 10 + "%"; $("cuMark").style.top = p.y / 10 + "%"; }
  const box = $("cuProposal");
  box.innerHTML = "";
  if (t.status === "waiting" && p) {
    const prop = el("div", "proposal", `<div><b class="mono">Next step:</b> ${esc(p.desc)}</div><div class="muted small">${esc(p.thought || "")}</div>`);
    const row = el("div", "row");
    const decide = async (approve, auto) => { row.querySelectorAll("button").forEach(b => b.disabled = true);
      await api(`/api/computer/${t.id}/decide`, json("POST", { approve, auto })); load(); };
    row.append(button("Approve", "primary", () => decide(true, false)), button("Skip", "", () => decide(false, false)),
      button("Approve all steps", "", () => { if (confirm("Let it run the rest of this task without asking? You can still press Stop.")) decide(true, true); }));
    prop.append(row); box.append(prop);
  } else if (t.error) box.append(el("div", "notice", esc(t.error)));
  $("cuSteps").innerHTML = t.steps.length ? "" : `<div class="muted small">No steps yet.</div>`;
  t.steps.slice().reverse().forEach((s, i) => $("cuSteps").append(el("div", "step",
    `<b>${t.steps.length - i}.</b> ${esc(s.desc)} ${s.result === "skipped" ? "<span class='muted'>(skipped)</span>" : ""}<div class="muted small">${esc(s.thought || "")}</div>`)));
  if (live) timer = setTimeout(() => { if ($("p-computer").classList.contains("on")) load(); }, 1200);
}

$("cuGo").onclick = async () => {
  const task = $("cuTask").value.trim();
  if (!task) return $("cuTask").focus();
  try { await api("/api/computer/start", json("POST", { task })); $("cuTask").value = ""; load(); }
  catch (e) { alert(e.message); }
};
$("cuStop").onclick = async () => { if (taskId) { await api(`/api/computer/${taskId}/stop`, { method: "POST" }); load(); } };

onPage("computer", load);
