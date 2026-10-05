import { $, api, button, el, esc, json, onPage, show } from "./core.js";
import { inline, openChat } from "./chat.js";

// ---------- the agent team (OpenDots-style): experts that work on one job together — off until switched on
const STATUS = { waiting: "Waiting…", queued: "⏳ Queued — starts when the job before it is done", planning: "🧭 The Planner splits the job…", working: "⚙️ The experts are working…",
  reviewing: "🧐 The Reviewer checks it…", done: "✓ Done", failed: "✕ Couldn't finish", stopped: "■ Stopped" };
const TOOLS = { "": "talks only", web: "🔎 searches the web (Tor)", calc: "🧮 uses the calculators", "3d": "🧊 builds 3D models", app: "💻 builds apps" };
let state = null, timer, agents = [];
const visible = () => $("p-team").classList.contains("on");

async function load() {
  try { state = await api("/api/team"); } catch { return; }
  $("teamOn").checked = state.on;
  $("teamGo").disabled = !state.on;  // busy: the new job waits in the queue
  $("teamWhy").textContent = state.on ? "On: jobs run one at a time; the experts work one after another on this PC's model."
    : "Off: a job runs several AI turns one after another — turn it on when you have the computing power (a strong PC or a fast model).";
  if (!agents.length || !$("teamAgents").contains(document.activeElement)) { agents = state.agents.map(a => ({ ...a })); renderAgents(); }
  renderJobs();
  clearTimeout(timer);
  if (state.running.length) timer = setTimeout(() => { if (visible()) load(); }, 2000);
}

function renderAgents() {
  const box = $("teamAgents"); box.innerHTML = "";
  agents.forEach((a, i) => {
    const c = el("div", "tagent");
    c.innerHTML = `<div class="row"><input type="checkbox" ${a.on ? "checked" : ""} title="On / off" style="min-height:0">
        <input class="temoji" value="${esc(a.emoji)}" maxlength="4"><input class="grow tname" value="${esc(a.name)}" placeholder="Name">
        <select class="ttool">${Object.entries(TOOLS).map(([k, v]) => `<option value="${k}" ${a.tool === k ? "selected" : ""}>${v}</option>`).join("")}</select></div>
      <textarea rows="2" placeholder="What this expert does">${esc(a.role)}</textarea>`;
    const [on, emoji, name] = c.querySelectorAll("input"), tool = c.querySelector("select"), role = c.querySelector("textarea");
    const sync = () => Object.assign(agents[i], { on: on.checked, emoji: emoji.value, name: name.value, tool: tool.value, role: role.value });
    [on, emoji, name, tool, role].forEach(x => x.addEventListener("input", sync));
    c.querySelector(".row").append(button("✕", "sm ghost", () => { agents.splice(i, 1); renderAgents(); }));
    box.append(c);
  });
}

const opened = new Set();  // finished jobs fold to one line; the ones you opened stay open while the list refreshes
async function remove(j) {
  if (!confirm(`Delete the job “${j.goal.slice(0, 80)}”? (Its chat stays in Chat.)`)) return;
  await api(`/api/team/jobs/${j.id}`, { method: "DELETE" }).catch(e => alert(e.message));
  load();
}

function renderJobs() {
  const box = $("teamJobs"); box.innerHTML = "";
  if (!state.jobs.length) box.append(el("div", "muted small", state.on ? "No jobs yet — give the team one." : "Switch the team on to give it jobs."));
  const finished = state.jobs.filter(j => !state.running.includes(j.id) && !(state.queued || []).includes(j.id));
  $("teamClear").hidden = !finished.length;
  for (const j of state.jobs) {
    const live = state.running.includes(j.id) || (state.queued || []).includes(j.id);
    const c = el("details", "tjob" + (live ? " live" : ""));
    c.open = live || opened.has(j.id);
    c.addEventListener("toggle", () => { if (c.open) opened.add(j.id); else opened.delete(j.id); });
    const head = el("summary", "row", `<b class="grow">${esc(j.goal)}</b><span class="small">${STATUS[j.status] || j.status}</span>`);
    if (!live) head.append(button("🗑", "sm ghost", ev => { ev.preventDefault(); remove(j); }));  // on the line: always in reach
    head.lastChild.title = live ? "" : "Delete this job";
    c.append(head);
    if (j.daily) c.append(el("div", "muted small", `🔁 every day at ${esc(j.daily)}`));
    for (const s of j.steps || []) {
      const ag = (state.agents.find(a => a.name === s.agent) || {}).emoji || "🤖";
      const st = { waiting: "…", working: "⚙️", done: "✓", failed: "✕" }[s.status] || "";
      const d = el("details", "tstep", `<summary>${ag} <b>${esc(s.agent)}</b> ${st}${s.tries > 1 ? " (2nd try)" : ""} — ${esc(s.task)}`
        + (s.status === "failed" && s.judge ? ` <span class="fitbad small">— the judge: ${esc(s.judge)}</span>` : "")
        + `</summary><div class="small">${s.done_when ? `<i>Done when: ${esc(s.done_when)}</i>\n` : ""}${esc(s.result || "")}</div>`);
      if (s.status === "working") d.open = true;
      c.append(d);
      for (const o of s.outputs || []) {  // what the expert really made, one click away
        const out = el("div", "tout row");
        if (o.kind === "model3d") {
          if (o.png) out.append(el("img", null)), out.querySelector("img").src = o.png;
          out.append(el("span", "grow small", `🧊 ${esc(o.label)}${o.collisions ? ` — ⚠ ${o.collisions} collision(s)` : " — fit check: nothing collides"}`),
            button("Open in Gallery", "sm", () => show("gallery")));
        } else if (o.kind === "app") {
          out.append(el("span", "grow small", `💻 ${esc(o.label)} — ${o.ok ? "tested ✓" : "⚠ has errors"}${o.folder ? ` · 📁 ${esc(o.folder)}` : ""}`),
            button("Open in Apps", "sm", () => { show("apps"); window.dispatchEvent(new CustomEvent("open-app", { detail: o.id })); }));
        } else out.append(el("span", "small muted", `🔗 ${esc(o.label)}`));
        c.append(out);
      }
    }
    if (j.final) c.append(el("div", "tfinal", inline(j.final)));  // bold, lists… like in the chat (not raw ** marks)
    if (j.error) c.append(el("div", "notice", esc(j.error)));
    const row = el("div", "row");
    if (j.chat) row.append(button("💬 Open the team's chat", "sm", () => { show("chat"); openChat(j.chat); }));
    if (live) row.append(button("Stop", "sm danger", async () => { await api(`/api/team/jobs/${j.id}/stop`, { method: "POST" }); load(); }));
    else row.append(button("Run again", "sm", () => start(j.goal, j.daily || "")), button("Delete", "sm ghost", () => remove(j)));
    c.append(row);
    box.append(c);
  }
}

async function start(goal, daily) {
  try { await api("/api/team/jobs", json("POST", { goal, daily })); } catch (e) { return alert(e.message); }
  load();
}

$("teamDaily").innerHTML = `<option value="">Once</option>` + ["07:00", "08:00", "09:00", "12:00", "18:00", "21:00"]
  .map(t => `<option value="${t}">Every day at ${t}</option>`).join("");
$("teamOn").onchange = async () => { await api("/api/team/toggle", json("POST", { on: $("teamOn").checked })).catch(e => alert(e.message)); load(); };
$("teamGo").onclick = () => {
  const g = $("teamGoal").value.trim();
  if (!g) return $("teamGoal").focus();
  start(g, $("teamDaily").value); $("teamGoal").value = "";
};
$("teamClear").onclick = async () => {  // every finished job off the list at once (running / queued ones stay)
  const done = state.jobs.filter(j => !state.running.includes(j.id) && !(state.queued || []).includes(j.id));
  if (!done.length || !confirm(`Delete ${done.length} finished job(s) from the list? (Their chats stay in Chat.)`)) return;
  for (const j of done) await api(`/api/team/jobs/${j.id}`, { method: "DELETE" }).catch(() => {});
  opened.clear(); load();
};
$("teamAdd").onclick = () => { agents.push({ id: "", name: "", emoji: "🤖", tool: "", role: "", on: true }); renderAgents(); };
$("teamSave").onclick = async () => {
  try { agents = (await api("/api/team/agents", json("POST", { agents }))).agents; renderAgents(); $("teamSave").textContent = "Saved ✓"; }
  catch (e) { alert(e.message); }
  setTimeout(() => { $("teamSave").textContent = "Save the team"; }, 1500);
};

onPage("team", load);
