import { $, api, button, el, esc, icon, isSpeaking, json, onPage, show, speak, speech, stopSpeaking, store, talker } from "./core.js";
import { model3dCard } from "./viewer3d.js";
import { liveCard } from "./computer.js";
import { openPaper, paperCard, printCard } from "./print3d.js";
import { calcCard } from "./calc.js";
import { putProject } from "./project.js";

const projHandlers = {
  next: () => send("build the next part"),
  assemble: () => send("assemble the project"),
  close: async () => { try { await api(`/api/projects/${chatId}`, { method: "DELETE" }); } catch { /* gone */ } if (chatId) openChat(chatId); },
};

let chatId = null, busy = false, images = [];
let turn = null;  // the reply being written: { ctl, stopped, text, imgs, userMsgId, usedTool }
let toolsOn = store.get("tools", "1") === "1";
let thinking = true;

// ---------- conversation list
function when(t) {
  const d = (Date.now() / 1000 - t) / 86400;
  return d < 1 ? "Today" : d < 7 ? "This week" : d < 31 ? "This month" : "Older";
}
let convCount = 0;
async function loadConvs() {
  const q = $("convSearch").value.trim();
  const list = await api("/api/chats" + (q ? "?q=" + encodeURIComponent(q) : ""));
  if (!q) convCount = list.length;
  $("clearChats").hidden = !!q || !list.length;  // hidden while searching, so it's clear it deletes ALL chats
  const box = $("convList");
  box.innerHTML = list.length ? "" : `<div class="muted small" style="padding:10px">${q ? "No matches." : "No chats yet."}</div>`;
  let group = "";
  for (const c of list) {
    if (when(c.updated) !== group) { group = when(c.updated); box.append(el("div", "sect", group)); }
    const row = el("div", "conv" + (c.id === chatId ? " on" : ""));
    const open = el("button", "open", `<span class="t">${esc(c.title || "Untitled")}</span>`);
    open.onclick = () => openChat(c.id);
    const x = el("button", "x", "✕");
    x.title = "Delete chat";
    x.onclick = async () => { if (!confirm("Delete this chat?")) return; await api(`/api/chats/${c.id}`, { method: "DELETE" }); if (c.id === chatId) newChat(); loadConvs(); };
    row.append(open, x);
    box.append(row);
  }
}
let searchT;
$("convSearch").oninput = () => { clearTimeout(searchT); searchT = setTimeout(loadConvs, 250); };
$("clearChats").onclick = async () => {
  if (busy) return alert("Wait until the reply is finished (or press Stop), then try again.");
  if (!confirm(`Delete all ${convCount >= 200 ? "200+" : convCount} chats permanently? What memory learned about you, your documents and the gallery are kept.`)) return;
  await api("/api/chats", { method: "DELETE" });
  newChat();
};

// ---------- rendering
// Links are clickable (they open in your normal browser); ![pictures](…) and found pictures are shown.
const LINK = /!\[([^\]]*)\]\((https?:\/\/[^\s)]+)\)|\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)|(https?:\/\/[^\s<]+)/g;
function shortUrl(u) {
  try {
    const x = new URL(u.replace(/&amp;/g, "&")), p = x.pathname.length > 1 ? x.pathname : "";
    return x.hostname.replace(/^www\./, "") + (p.length > 28 ? p.slice(0, 27) + "…" : p);
  } catch { return u; }
}
function links(html) {  // html = already-escaped text
  return html.replace(LINK, (all, alt, src, label, href, bare) => {
    if (src) return `<img class="web" src="${src}" alt="${alt}" loading="lazy" referrerpolicy="no-referrer">`;
    let u = href || bare, tail = "";
    if (bare) { const m = u.match(/(&quot;|&#39;|[.,;:!?)\]])+$/); if (m) { tail = m[0]; u = u.slice(0, -tail.length); } }
    const shown = label && !/^https?:\/\//.test(label) ? label : shortUrl(u);
    return `<a href="${u}" title="${u}">${shown}</a>${tail}`;
  });
}
export function inline(text) {
  return links(esc(text).replace(/^#{1,6}\s+(.+)$/gm, "<b>$1</b>").replace(/\*\*(.+?)\*\*/g, "<b>$1</b>")
    .replace(/(?<![*\w])\*(?!\s)([^*\n]+?)(?<!\s)\*(?![*\w])/g, "<i>$1</i>").replace(/`([^`\n]+)`/g, "<code>$1</code>"));
}
function pictureGrid(pics) {
  const g = el("div", "pics");
  for (const p of pics) {
    const img = Object.assign(el("img"), { src: p.thumb, alt: p.title || "", title: p.title || "" });
    img.onclick = () => viewPicture(p);
    g.append(img);
  }
  return g;
}
// Pictures / clips asked for in the chat appear in it when they're ready (with progress while they're made).
const making = new Map();  // job id -> its box in the chat
let makingTimer = null;
function jobBox(jid) {
  const box = el("div", "made", `<span class="muted small">⏳ Waiting for its turn…</span>`);
  const stop = button(`${icon("stop")}Stop`, "sm danger", async () => {
    stop.disabled = true;
    try { await api(`/api/jobs/${jid}`, { method: "DELETE" }); } catch {}
    pollMaking();
  });
  box.append(" ", stop);
  making.set(jid, box);
  clearTimeout(makingTimer); makingTimer = setTimeout(pollMaking, 300);
  return box;
}
async function pollMaking() {
  try {
    const { jobs } = await api("/api/jobs");
    for (const [jid, box] of making) {
      const j = jobs.find(x => x.id === jid);
      if (!box.isConnected || !j) {
        if (box.isConnected) box.innerHTML = `<span class="muted small">Stopped.</span>`;
        making.delete(jid);
      } else if (j.status === "done" && j.file) {
        const src = "/media/" + encodeURIComponent(j.file);
        if (j.kind === "image") {
          const img = Object.assign(el("img"), { src, alt: j.prompt, title: j.prompt });
          img.onclick = () => viewPicture({ image: src, title: j.prompt });
          box.replaceChildren(img);
        } else box.innerHTML = `<video src="${src}" controls loop playsinline></video>`;
        making.delete(jid);
        $("log").scrollTop = $("log").scrollHeight;
      } else if (j.status === "error" || j.status === "cancelled") {
        box.innerHTML = `<span class="notice">${j.status === "cancelled" ? "Cancelled." : "It didn't work: " + esc((j.error || "").split("\n").pop())}</span>`;
        making.delete(jid);
      } else if (j.status === "running") {
        box.firstChild.textContent = `⏳ ${j.phase || "Making it"}… ${Math.round((j.progress || 0) * 100)}% `;
      }
    }
  } catch {}
  clearTimeout(makingTimer);
  if (making.size) makingTimer = setTimeout(pollMaking, 3000);
}
// A 3D model being built (PicoGK): a bar with the step ("Building part 3 of 9"), %, time, and Stop — like pictures/clips.
const mmss = s => `${Math.floor(s / 60)}:${String(Math.round(s) % 60).padStart(2, "0")}`;
export function progress3dBox(rid, onEnd) {
  const box = el("div", "made prog3d", `<div class="muted small">🧊 <span class="t">The AI is planning the design…</span> <span class="p"></span></div>`
    + `<div class="bar"><i style="width:2%"></i></div>`);
  const stop = button(`${icon("stop")}Stop`, "sm danger", async () => {
    stop.disabled = true;
    box.querySelector(".t").textContent = "Stopping…";
    try { await api(`/api/plugin-runs/${rid}/stop`, { method: "POST" }); } catch {}
  });
  box.append(stop);
  const tick = async () => {
    if (!box.isConnected) return;
    let r = null;
    try { r = await api(`/api/plugin-runs/${rid}`); } catch {}
    if (r && !r.pending) {
      box.querySelector(".t").textContent = r.stopped ? "Stopped." : r.text;
      box.querySelector(".p").textContent = r.done ? "" : `· ${Math.round(r.pct * 100)}% · ${mmss(r.elapsed)}`;
      box.querySelector(".bar i").style.width = `${Math.round(r.pct * 100)}%`;
      if (r.done || r.stopped) {
        stop.remove();
        if (onEnd) onEnd(r); else setTimeout(() => box.remove(), r.stopped ? 5000 : 600);
        if (r.done) return;
      }
    }
    setTimeout(tick, 800);
  };
  setTimeout(tick, 300);
  return box;
}
// What the AI used / decided, shown above its answer: a saved rule (with Undo), the skills it loaded, its plan.
function ruleChip(r) {
  const c = el("div", "tool rule", `📌 Saved as a rule — followed in every chat: “${esc(r.text)}” `);
  const undo = button("Undo", "sm", async () => {
    undo.disabled = true;
    try { await api(`/api/memory/${r.id}`, { method: "DELETE" }); c.textContent = "📌 Rule removed."; } catch (e) { alert(e.message); }
  });
  c.append(undo);
  return c;
}
function skillChip(names) {
  return el("div", "tool", `📚 Skills: ${esc(names.join(", "))}`);
}
function planBox(text, open) {
  const p = el("details", "plan", `<summary>📝 The plan (how it thought it through)</summary><div class="pbody"></div>`);
  p.open = !!open;
  renderText(p.querySelector(".pbody"), text);
  return p;
}
function lockChoices(keepLast) {  // buttons already answered (or from an old message) can't be pressed again
  const last = $("log").lastElementChild;  // only the newest message's buttons stay usable when a chat opens
  [...document.querySelectorAll("#log .choices:not(.done)")].filter(b => !(keepLast && last?.contains(b))).forEach(b => { b.classList.add("done"); b.querySelectorAll("button").forEach(x => { x.disabled = true; }); });
}
function clipBox(src) {  // a finished video with sound (e.g. after "add a narrator")
  return el("div", "made", `<video src="${esc(src)}" controls playsinline></video>`);
}
function linkList(items) {  // web results: numbered, clickable ("open the second link" works too)
  const box = el("div", "links");
  items.forEach((x, i) => {
    const a = el("a", null, `<span class="n">${i + 1}</span><span class="t">${esc(x.title || x.url)}</span><span class="site">${esc(shortUrl(x.url))}</span>`);
    a.href = x.url; a.title = x.url;
    box.append(a);
  });
  return box;
}
function videoGrid(vids) {  // found videos: preview + length + title; a click plays it in your web browser
  const g = el("div", "vids");
  for (const v of vids) {
    const c = el("button", "vid", `<span class="th"><img alt="" src="${esc(v.thumb)}"><span class="len">${esc(v.length || "")}</span>`
      + `<span class="play">▶</span></span><span class="t">${esc(v.title)}</span><span class="ch">${esc(v.channel || "")}</span>`);
    c.title = "Watch it in your web browser";
    c.onclick = () => openLink(v.url);
    g.append(c);
  }
  return g;
}
function viewPicture(p) {  // big picture: loads the full size from its site (the saved preview if that fails)
  const v = el("div", "picview", `<figure><img alt="" referrerpolicy="no-referrer"><figcaption></figcaption></figure>`);
  const img = v.querySelector("img"), cap = v.querySelector("figcaption");
  img.src = p.image || p.thumb;
  img.onerror = () => { if (p.thumb && img.src !== location.origin + p.thumb) img.src = p.thumb; };
  cap.append(el("span", null, esc(p.title || "") + (p.credit ? ` <span style="opacity:.7">· ${esc(p.credit)}</span>` : "")));
  if (p.page) cap.append(button("Open the page", "sm", (e) => { e.stopPropagation(); openLink(p.page); }));
  if (String(p.image || "").startsWith("/media/")) cap.append(button(`${icon("print")}Print`, "sm", (e) => {  // a picture made here
    e.stopPropagation(); v.remove(); openPaper({ kind: "image", url: p.image, name: (p.title || "picture").slice(0, 40) });
  }));
  cap.append(button("Close", "sm", () => v.remove()));
  v.onclick = (e) => { if (e.target === v || e.target === img) v.remove(); };
  document.body.append(v);
}
function openLink(url) {
  api("/api/open", json("POST", { url })).catch(() => window.open(url, "_blank", "noopener"));
}
$("log").addEventListener("click", (e) => {
  const a = e.target.closest("a[href]");
  if (a && /^https?:/i.test(a.getAttribute("href"))) { e.preventDefault(); openLink(a.href); return; }
  const img = e.target.closest("img.web");
  if (img) viewPicture({ image: img.src, title: img.alt });
});
document.addEventListener("keydown", (e) => {  // Esc closes the picture first (and doesn't also stop the reply)
  const v = document.querySelector(".picview");
  if (e.key === "Escape" && v) { v.remove(); e.stopImmediatePropagation(); }
});

function renderText(body, text) {
  body.innerHTML = "";
  for (const part of text.split(/(```[\w-]*\n[\s\S]*?```)/g)) {
    const m = part.match(/^```([\w-]*)\n([\s\S]*?)```$/);
    if (!m) {
      body.append(el("span", null, inline(part)));
      continue;
    }
    body.append(el("pre", null, esc(m[2])));
    const bar = el("div", "acts");
    bar.append(actBtn("copy", "Copy", () => navigator.clipboard.writeText(m[2])));
    if (/html|svg|xml/i.test(m[1]) || /^\s*<(!doctype|html|svg)/i.test(m[2])) {
      const pv = actBtn("play", "Preview", () => {
        const f = el("iframe"); f.sandbox = "allow-scripts"; f.srcdoc = m[2]; bar.after(f); pv.remove();
      });
      bar.append(pv);
    }
    body.append(bar);
  }
}
function actBtn(ic, label, fn) { const b = el("button", null, `${icon(ic)}${label}`); b.onclick = fn; return b; }

// 👍 / 👎 under every answer: a liked answer is kept as a good example, a disliked one as a bad example (and why) —
// on similar questions later the AI is shown them (feedback.py). Clicking the pressed one again takes it back.
const WHY = [["wrong", "Wrong facts"], ["made_up", "Made things up"], ["not_asked", "Didn't do what I asked"],
  ["off_topic", "Mixed in wrong things"], ["long", "Too long"], ["short", "Too short"]];
function rateBtns(d, extra) {
  const up = actBtn("like", "", () => rate(d, up.classList.contains("on") ? 0 : 1));
  const down = actBtn("dislike", "", () => rate(d, down.classList.contains("on") ? 0 : -1));
  up.className = down.className = "rate";
  up.title = "Good answer: keep it as a good example";
  down.title = "Bad answer: keep it as a bad example" + (extra.reason ? ` (${extra.reason})` : "");
  up.classList.toggle("on", extra.rating === 1);
  down.classList.toggle("on", extra.rating === -1);
  d._rate = { up, down };
  return [up, down];
}
async function rate(d, rating, reason = "") {
  if (!chatId || !d.dataset.id) return alert("Wait until the answer has finished.");
  let r;
  try { r = await api(`/api/chats/${chatId}/rate`, json("POST", { msg_id: +d.dataset.id, rating, reason })); }
  catch (e) { return alert(e.message); }
  d._rate.up.classList.toggle("on", r.rating === 1);
  d._rate.down.classList.toggle("on", r.rating === -1);
  d._rate.down.title = "Bad answer: keep it as a bad example" + (r.reason ? ` (${r.reason})` : "");
  d.querySelector(".whybox")?.remove();
  if (r.rating === -1 && !reason) return d.append(whyBox(d));  // one more click says why (optional)
  if (r.rating) rateNote(d, r.rating === 1 ? "👍 Kept as a good example: it answers like this on similar questions."
    : "👎 Kept as a bad example: it won't do that again on similar questions.");
}
function whyBox(d) {
  const box = el("div", "whybox", `<span class="muted small">What was wrong? (optional)</span>`);
  for (const [k, label] of WHY) box.append(button(label, "chip", () => rate(d, -1, k)));
  const inp = el("input", "whyin");
  inp.placeholder = "or say why, then Enter";
  inp.onkeydown = (e) => { if (e.key === "Enter" && inp.value.trim()) rate(d, -1, inp.value.trim()); };
  box.append(inp, button("✕", "sm ghost", () => { box.remove(); rateNote(d, "👎 Kept as a bad example."); }));
  return box;
}
function rateNote(d, text) {
  d.querySelector(".ratenote")?.remove();
  const n = el("div", "muted small ratenote", esc(text));
  d.append(n);
  setTimeout(() => n.remove(), 5000);
}

function hello() {
  $("log").innerHTML = `<div class="hello"><h2>What shall we make?</h2><div class="muted">Everything runs on this PC — nothing leaves it.</div>
    <div class="chips"><button class="chip">Make a 20-second movie about a fox in the snow, with a narrator</button>
    <button class="chip">Draw a cozy cabin in the mountains at night</button><button class="chip">Open Notepad and write a shopping list</button>
    <button class="chip">Search the web for today's weather in Bucharest</button></div></div>`;
  $("log").querySelectorAll(".hello .chip").forEach(c => c.onclick = () => { $("input").value = c.textContent; $("input").focus(); });
}

// ---------- choice buttons: when Laya / the model isn't sure (or a 3D design failed), the user picks — and it's learned
function choiceBox(c) {
  const box = el("div", "choices");
  for (const o of c.options || []) {
    box.append(button(esc(o.label), "chip", () => {
      box.querySelectorAll("button").forEach(b => { b.disabled = true; });
      box.classList.add("done");
      if (o.action === "open3d") return window.dispatchEvent(new CustomEvent("open3dask", { detail: c.for }));
      send(o.send || c.for, [], { route: o.route });
    }));
  }
  return box;
}

function addMsg(m) {
  if ($("log").querySelector(".hello")) $("log").innerHTML = "";
  const d = el("div", "msg " + m.role);
  if (m.id) d.dataset.id = m.id;
  d.dataset.text = m.content || "";
  const body = el("div", "body");
  (m.imgs || []).forEach(src => d.append(Object.assign(el("img", "att"), { src })));
  d.append(body);
  if (m.role === "assistant") renderText(body, m.content || ""); else body.innerHTML = links(esc(m.content || ""));
  const extra = typeof m.extra === "string" ? JSON.parse(m.extra || "{}") : (m.extra || {});
  if (extra.pictures?.length) d.insertBefore(pictureGrid(extra.pictures), body);
  if (extra.videos?.length) d.insertBefore(videoGrid(extra.videos), body);
  if (extra.links?.length) d.insertBefore(linkList(extra.links), body);
  (extra.jobs || []).forEach(jid => d.insertBefore(jobBox(jid), body));
  (extra.clips || []).forEach(src => d.insertBefore(clipBox(src), body));
  if (extra.opened) d.insertBefore(extra.kind === "videos" ? videoGrid([extra.opened])
    : extra.kind === "links" ? linkList([extra.opened]) : pictureGrid([extra.opened]), body);
  (extra.laya || []).forEach(x => d.insertBefore(el("div", "tool laya", `${icon("spark")} Laya ${esc(x)}`), body));
  if (extra.rule) d.insertBefore(ruleChip(extra.rule), body);
  if (extra.skills?.length) d.insertBefore(skillChip(extra.skills), body);
  if (extra.plan) d.insertBefore(planBox(extra.plan, false), body);
  if (extra.code) d.insertBefore(codeBox(extra.code), body);
  if (extra.fixed?.length) d.insertBefore(el("div", "tool", `🔧 Checked and fixed: ${esc(extra.fixed.join("; "))}`), body);
  (extra.models3d || []).forEach(m => d.insertBefore(model3dCard(m, esc), body));
  (extra.prints || []).forEach(r => d.insertBefore(printCard(r), body));  // "print it": G-code for the user's printer
  (extra.calcs || []).forEach(c => d.insertBefore(calcCard(c), body));  // a calculator's exact numbers
  if (extra.team) d.insertBefore(teamCard(extra.team), body);  // the agent team working on this chat's job
  if (extra.computer) d.insertBefore(liveCard(extra.computer), body);  // computer use: watch + Allow each step right here
  if (extra.forge) d.insertBefore(forgeCard(extra.forge), body);  // a new skill (a draft): try it, turn it on
  if (extra.bg) d.insertBefore(bgCard(extra.bg), body);  // an app / skill being made in the background for this chat
  if (extra.geo) d.insertBefore(geoCard(extra.geo), body);  // 📐 the answer's working: computed in the sandbox
  if (extra.apps?.length) d.insertBefore(appCards(extra.apps), body);  // apps the app maker / the Coder built
  if (extra.project) putProject(d, extra.project, body, projHandlers);  // a build project: the part-by-part checklist
  if (extra.paper) d.insertBefore(paperCard(extra.paper), body);  // "print this picture / text" on paper
  if (extra.tools?.length) d.insertBefore(el("div", "tool", `${icon("tool")} Used: ${esc(extra.tools.join(", "))}`), body);
  if (extra.choices) setTimeout(() => d.append(choiceBox(extra.choices)), 0);
  if (extra.images && m.role === "user") d.insertBefore(el("div", "muted small mono attimgs", `🖼 ${extra.images} image(s) attached`), body);
  if (extra.attachments?.length && m.role === "user") {  // files / a folder / a video: shown, and kept for Resend
    d.insertBefore(attList(extra.attachments), body);
    d.dataset.att = JSON.stringify(extra.attIds || extra.attachments.map(a => a.id).filter(Boolean));
    d.dataset.attinfo = JSON.stringify(extra.attachments);
  }
  const acts = el("div", "acts");
  if (m.role === "assistant") {
    acts.append(actBtn("speak", "Speak", () => isSpeaking() ? stopSpeaking()
      : speak(m.content || body.innerText, $("voicePick")?.value).catch(e => alert(e.message))),
      actBtn("copy", "Copy", () => navigator.clipboard.writeText(m.content || body.innerText)),
      actBtn("print", "Print", () => openPaper({ kind: "text", text: body.innerText || m.content || "", name: "answer" })),
      actBtn("redo", "Regenerate", () => regenerate(d)), ...rateBtns(d, extra));
  } else if (m.role === "user") {
    acts.append(actBtn("copy", "Copy", () => navigator.clipboard.writeText(m.content)),
      actBtn("edit", "Edit", () => editMsg(d, m.content)), actBtn("redo", "Resend", () => resend(d, m.content)));
  }
  d.append(acts);
  $("log").append(d);
  $("log").scrollTop = $("log").scrollHeight;
  return { d, body, acts };
}

// ⇋ Mirror copy from a 3D card's right-click menu (viewer3d.js): in a chat the copy comes in as a new answer there;
// from the Gallery it's saved in Gallery › 3D
window.addEventListener("mirror3d", async e => {
  const { model, axis, inChat } = e.detail || {}, cid = inChat ? chatId : null;
  if (cid && busy) return alert("Wait until the answer has finished.");
  try {
    const r = await api("/api/model3d/mirror", json("POST", { model, axis, chat: cid }));
    if (cid && cid === chatId) await openChat(cid);
    else alert(`Saved in Gallery › 3D: “${r.model3d?.name || "mirrored model"}”.`);
  } catch (err) { alert(err.message); }
});

function detachTurn(toChat) {
  // Another chat is opened while an answer is being made: that answer keeps going on the server (and is saved);
  // this page lets go of it so you can use the other chat — coming back shows it working / finished.
  if (turn && !turn.detached && turn.chatId !== toChat) {
    turn.detached = true;
    turn = null;
    setBusy(false);
  }
}
let workingPoll = null;
export const currentChat = () => chatId;  // Create › 3D: which chat "Edit in 3D" came from ("Send to chat")
export async function openChat(id, keepScroll) {
  detachTurn(id);
  const c = await api(`/api/chats/${id}`);
  chatId = id;
  $("log").innerHTML = "";
  c.messages.forEach(addMsg);
  setTimeout(() => lockChoices(true), 0);  // after the choice boxes are added (they're added a tick later)
  if (!c.messages.length) hello();
  clearTimeout(workingPoll);
  if (c.working && !(turn && turn.chatId === id)) {  // still being answered in the background: show it live
    const { d, body } = addMsg({ role: "assistant", content: "" });
    d.classList.add("working");
    body.innerHTML = `<span class="muted">⏳ Still working on this —${esc(c.working.status || "")} (${c.working.since} s so far). `
      + `You can use other chats meanwhile; the answer appears here by itself.</span>`;
    if (c.working.progress3d) d.insertBefore(progress3dBox(c.working.progress3d), body);
    d.append(button("Stop it", "sm danger", async () => { try { await api("/api/chat/stop", json("POST", { chat_id: id })); } catch {} }));
    const check = async () => {
      if (chatId !== id) return;
      let n;
      try { n = await api(`/api/chats/${id}`); } catch { n = null; }
      if (n && !n.working) return openChat(id, true);
      workingPoll = setTimeout(check, 2500);
    };
    workingPoll = setTimeout(check, 2500);
  }
  if (!keepScroll) $("log").scrollTop = $("log").scrollHeight;
  loadConvs();
}
function newChat() { detachTurn(null); chatId = null; hello(); loadConvs(); show("chat"); $("input").focus(); }
$("newChat").onclick = newChat;

// ---------- regenerate / edit / resend: cut the chat at a message and send again
async function cutFrom(msgEl) {
  if (!chatId || !msgEl.dataset.id) return false;
  await api(`/api/chats/${chatId}/truncate`, json("POST", { from_id: +msgEl.dataset.id }));
  return true;
}
async function regenerate(assistantEl) {
  if (busy) return;
  let u = assistantEl.previousElementSibling;
  while (u && !u.classList.contains("user")) u = u.previousElementSibling;
  if (!u || !(await cutFrom(u))) return;
  const text = u.dataset.text || u.querySelector(".body").textContent;
  await openChat(chatId); send(text, [], keptFiles(u));
}
function keptFiles(userEl) {  // the files attached to a message go with it on Regenerate / Edit / Resend
  const ids = JSON.parse(userEl.dataset.att || "[]");
  return ids.length ? { attachments: ids, attInfo: JSON.parse(userEl.dataset.attinfo || "[]") } : {};
}
async function editMsg(userEl, old) {
  if (busy) return;
  const text = prompt("Edit your message:", old);
  if (text == null || !text.trim() || !(await cutFrom(userEl))) return;
  await openChat(chatId); send(text.trim(), [], keptFiles(userEl));
}
async function resend(userEl, text) {
  if (busy || !(await cutFrom(userEl))) return;
  await openChat(chatId); send(text, [], keptFiles(userEl));
}

// ---------- sending + streaming
function toolCard(e) {
  const r = e.result || {};
  const names = { create_image: "Image", create_video: "Video clip", make_movie: "Movie", web_search: "Web search",
    read_webpage: "Read page", search_images: "Picture search", search_videos: "Video search", add_sound: "Voice & music", join_videos: "Join videos", use_computer: "Computer use", check_progress: "Progress", list_options: "Options", remember: "Memory" };
  const card = el("div", "tool" + (r.error || r.denied ? " bad" : ""));
  const label = e.tool.startsWith("skill_") ? `🛠 Skill: ${r.skill || "your skill"}` : names[e.tool] || e.tool;  // a Forge skill
  let text = `${icon("tool")} <b>${esc(label)}</b> `;
  if (r.error) text += `— failed: ${esc(r.error)}`;
  else if (r.denied) text += "— you said no";
  else if (r.started) text += `— started${r.scenes ? ` · ${r.scenes} scenes` : ""}${r.takes ? ` · ${r.takes}` : r.minutes ? ` · about ${r.minutes} min` : ""}`;
  else if (r.results) text += `— ${r.results.length} results`;
  else if (r.clip) text += "— added to the video";
  else if (r.videos) text += `— “${esc(r.query || "")}”: ${r.videos.length} videos`;
  else if (r.pictures) text += `— “${esc(r.query || "")}”: ${r.pictures.length} of ${r.found ?? r.pictures.length} found really show it`
    + (r.checked === "looked" ? " (checked by looking at each)" : "");
  else if (r.title !== undefined && r.url) text += `— read “${esc(r.title || r.url)}”`;
  else if (r.saved) text += `— saved “${esc(r.saved)}”`;
  else text += "— done";
  card.innerHTML = text;
  if (r.started && e.tool !== "use_computer") card.append(button("Open queue", "sm", () => show("create")));
  if (e.tool === "use_computer" && r.task) card.append(liveCard(r.task));  // watch + approve right here: you stay in the chat

  return card;
}

/** The agent team on this chat's job: live steps (✓ / ⚙️ / ✕ with the judge's reason), Stop, and the chat refreshes
 *  as the experts post their work (3D models, apps, sources, the reviewer's result) below. */
function teamCard(jid) {
  const card = el("div", "teamcard");
  let shown = -1;
  const ICON = { waiting: "…", working: "⚙️", done: "✓", failed: "✕" };
  async function tick() {
    if (!card.isConnected && card.dataset.seen) return;  // the chat moved on
    if (card.isConnected) card.dataset.seen = "1";
    let st;
    try { st = await api("/api/team"); } catch { setTimeout(tick, 3000); return; }
    const j = st.jobs.find(x => x.id === jid), live = st.running.includes(jid) || (st.queued || []).includes(jid);
    if (!j) { card.innerHTML = `<span class="muted small">👥 This team job was deleted.</span>`; return; }
    const emo = Object.fromEntries(st.agents.map(a => [a.name, a.emoji]));
    card.innerHTML = `<div class="row"><b class="grow">👥 Team — ${esc({ waiting: "starting…", queued: "queued — starts after the job before it", planning: "planning…", working: "working…",
      reviewing: "reviewing…", done: "done ✓", failed: "couldn't finish", stopped: "stopped" }[j.status] || j.status)}</b></div>`
      + (j.steps || []).map(s => `<div class="small">${emo[s.agent] || "🤖"} <b>${esc(s.agent)}</b> ${ICON[s.status] || ""}${s.tries > 1 ? " (2nd try)" : ""} — ${esc(s.task)}`
        + (s.status === "failed" && s.judge ? ` <span class="fitbad">— ${esc(s.judge)}</span>` : "") + `</div>`).join("");
    if (live) card.querySelector(".row").append(button("Stop", "sm danger", async () => { await api(`/api/team/jobs/${jid}/stop`, { method: "POST" }); tick(); }));
    const done = (j.steps || []).filter(s => ["done", "failed"].includes(s.status)).length + (j.final ? 1 : 0);
    if (shown >= 0 && done !== shown && chatId) openChat(chatId, true);  // new expert work was posted in this chat
    shown = done;
    if (live) setTimeout(tick, 2500);
  }
  tick();
  return card;
}

/** An app / skill being made in the BACKGROUND for this chat: its live state + Stop. The result is posted into the chat
 *  when it's ready (the chat refreshes by itself on the "task-done" notice). */
function bgCard(id) {
  const c = el("div", "bgcard small");
  const t0 = Date.now();
  async function tick() {
    if (!c.isConnected && c.dataset.seen) return;  // the chat moved on
    if (c.isConnected) c.dataset.seen = "1";
    let t;
    try { t = (await api("/api/tasks")).tasks.find(x => x.id === id); } catch {}
    c.hidden = !t;  // an old message: its task left the list long ago
    if (!t) { if (Date.now() - t0 < 8000) setTimeout(tick, 2500); return; }
    const secs = Math.round((t.ended || Date.now() / 1000) - t.started);
    const live = t.status === "running";
    c.innerHTML = live ? `⚙️ Working on it in the background · ${secs < 60 ? secs + "s" : Math.floor(secs / 60) + "m " + (secs % 60) + "s"} — you can keep chatting`
      : t.status === "done" ? "✓ Ready — the result is below." : t.status === "failed" ? `<span class="fitbad">✕ ${esc(t.error || "failed")}</span>` : "■ Stopped";
    if (live) {
      c.append(" ", button("Stop", "sm danger", async () => { await api(`/api/tasks/${id}/stop`, { method: "POST" }).catch(() => {}); tick(); }));
      setTimeout(tick, 2500);
    }
  }
  tick();
  return c;
}
window.addEventListener("task-done", e => { if (e.detail.chat && e.detail.chat === chatId) openChat(chatId, true); });

/** 📐 Geometric reasoning: the answer was worked out by a program in the sandbox (and re-run with other numbers). */
function geoCard(g) {
  const val = v => typeof v === "number" ? +v.toFixed(6) : esc(String(v));
  const ins = Object.entries(g.inputs || {}).map(([k, v]) => `${esc(k)} = ${val(v)}`).join(", ");
  const steps = Object.entries(g.steps || {}).map(([k, v]) => `<div>${esc(k)} = <b>${val(v)}</b></div>`).join("");
  const changed = Object.entries(g.changed || {}).map(([k, [a, b]]) => `${esc(k)} ${val(a)} → <b>${val(b)}</b>`).join(", ");
  const c = el("details", "tool geocard", `<summary>📐 <b>${changed ? "Changed: " + changed + " —" : "Worked out with code —"}</b> answer: <b>${val(g.answer)} ${esc(g.unit || "")}</b>
    · <span class="${String(g.check).startsWith("⚠") || String(g.check).startsWith("failed") ? "fitbad" : ""}">${esc(g.check || "")}</span></summary>
    <div class="small">${ins ? `<div class="muted">Inputs: ${ins}</div>` : ""}${steps}
    ${g.perturbed ? `<div class="muted">Changed numbers: ${esc(Object.entries(g.perturbed.inputs).map(([k, v]) => k + " = " + v).join(", "))} → ${val(g.perturbed.answer)}</div>` : ""}</div>
    <pre class="mono small">${esc(g.code || "")}</pre>`);
  return c;
}

/** A skill the Forge made in this chat: a DRAFT — try it here (in the sandbox), turn it on, or open it in Forge. */
function forgeCard(k) {
  const c = el("div", "forgecard", `<div class="row"><b class="grow">🛠 ${esc(k.name)}</b><span class="small ${k.ok ? "" : "fitbad"}">${k.ok ? "✓ passed its test" : "⚠ fails its test"}</span></div>`);
  const out = el("pre", "mono small"); out.hidden = true;
  const state = el("span", "muted small grow");
  const row = el("div", "row");
  const refresh = async () => {
    try {
      const s = await api(`/api/forge/${k.id}`);
      state.textContent = s.active ? `On (version ${s.active}) — I can use it in chats` : "Draft — not used until you turn it on";
      on.hidden = !k.ok || s.active === s.versions;
    } catch { state.textContent = "This skill was deleted."; row.querySelectorAll("button").forEach(b => b.disabled = true); }
  };
  const on = button("✓ Turn on", "sm primary", async () => {
    try { await api(`/api/forge/${k.id}/on`, json("POST", {})); } catch (e) { alert(e.message); }
    refresh();
  });
  row.append(button("▶ Try it", "sm", async () => {
    out.hidden = false; out.textContent = "Running in the sandbox…";
    try {
      const r = await api(`/api/forge/${k.id}/run`, json("POST", { params: {} }));
      out.textContent = r.ok ? JSON.stringify(r.result, null, 2) : "✕ " + r.error;
    } catch (e) { out.textContent = "✕ " + e.message; }
  }), on, button("Open in Forge", "sm ghost", () => { show("forge"); window.dispatchEvent(new CustomEvent("open-skill", { detail: k.id })); }));
  c.append(state, row, out);
  refresh();
  return c;
}

/** Apps the app maker built for this chat: try it right here (sealed), open it in Apps, open its project folder. */
function appCards(list) {
  const box = el("div", "appcards");
  for (const a of list) {
    const c = el("div", "appcard", `<div class="row"><b class="grow">💻 ${esc(a.label)}</b><span class="small ${a.ok ? "" : "fitbad"}">${a.ok ? "✓ tested" : "⚠ check it"}</span></div>`);
    const frame = el("iframe", "appframe mini"); frame.setAttribute("sandbox", "allow-scripts allow-pointer-lock allow-modals"); frame.hidden = true;
    const row = el("div", "row");
    row.append(button("▶ Try it here", "sm primary", async () => {
      if (!frame.hidden) { frame.hidden = true; return; }
      try { frame.srcdoc = (await api(`/api/apps/${a.id}`)).sealed; frame.hidden = false; } catch (e) { alert(e.message); }
    }), button("Open in Apps", "sm", () => { show("apps"); window.dispatchEvent(new CustomEvent("open-app", { detail: a.id })); }));
    if (a.folder) row.append(button("📁 Open folder", "sm ghost", () => api(`/api/apps/${a.id}/open-folder`, { method: "POST" }).catch(e => alert(e.message))));
    c.append(row, frame);
    box.append(c);
  }
  return box;
}

function askCard(a) {
  const what = { web_search: `search the web for “${esc(a.args.query)}”`, search_images: `find pictures of “${esc(a.args.query)}” on the web`,
    search_videos: `find videos of “${esc(a.args.query)}” on YouTube`, read_webpage: `open and read ${esc(a.args.url)}`,
    use_computer: `use your mouse and keyboard to: “${esc(a.args.task)}”`,
    download_file: `download “${esc(a.info?.file || a.args.url)}” from ${esc(a.info?.host || "the web")} into the sandbox` }[a.tool] || esc(a.tool);
  const extra = a.tool === "download_file" ? `<div class="muted small">Why: ${esc(a.args.why || "—")} · Risk: ${esc(a.info?.risk || "checked after download")}
    · through Tor · programs and scripts are blocked · nothing is opened or run<br><span class="mono">${esc(a.args.url)}</span></div>` : "";
  const card = el("div", "ask", `<div>🔐 The assistant wants to <b>${what}</b>. Allow it?</div>${extra}`);
  const row = el("div", "row");
  const decide = async (ok, always) => {
    row.querySelectorAll("button").forEach(b => b.disabled = true);
    try { await api(`/api/approve/${a.id}`, json("POST", { ok, always })); } catch (e) { alert(e.message); }
    card.firstChild.innerHTML += ok ? " <b>— allowed</b>" : " <b>— declined</b>";
  };
  row.append(button("Allow", "primary sm", () => decide(true, false)));
  if (!["use_computer", "download_file"].includes(a.tool)) row.append(button("Always allow web", "sm", () => decide(true, true)));
  row.append(button("No", "sm danger", () => decide(false, false)));
  card.append(row);
  return card;
}

// ---------- Stop: the send button turns into a Stop button while a reply is being written (Esc works too)
function setBusy(on) {
  busy = on;
  const b = $("send");
  b.classList.toggle("primary", !on); b.classList.toggle("stop", on);
  b.title = on ? "Stop (Esc)" : "Send";
  b.innerHTML = on ? icon("stop") : icon("up");
}
export function stopChat() {
  stopSpeaking();
  if (!turn || turn.stopped) return;
  turn.stopped = true;
  api("/api/chat/stop", json("POST", { chat_id: turn.chatId || chatId })).catch(() => {});  // THAT chat, not the one on screen
  setTimeout(() => { if (turn?.stopped && busy) turn.ctl.abort(); }, 2500);  // e.g. still loading the model
}

export async function send(text, imgs = [], opts = {}) {
  if (busy) return;
  lockChoices(false);  // a new message answers (or skips) any open choice buttons
  stopSpeaking();  // a new message: stop reading the old answer
  setBusy(true);
  turn = { ctl: new AbortController(), stopped: false, text, imgs, userMsgId: null, usedTool: false };
  const t = turn;
  addMsg({ role: "user", content: text, imgs, extra: opts.attachments?.length ? { attachments: opts.attInfo || [], attIds: opts.attachments } : undefined });
  const { d, body } = addMsg({ role: "assistant", content: "" });
  body.innerHTML = `<span class="muted">…</span>`;
  let got = "", think = "", thinkEl = null;
  let voice = voiceMode() !== "off" ? talker(store.get("voice", "")) : null;  // she starts talking with the first sentence
  try {
    const res = await fetch("/api/chat", { ...json("POST", { message: text, chat_id: chatId, images: imgs, tools: toolsOn, voice: voiceMode() !== "off", route: opts.route || null, attachments: opts.attachments || [] }), signal: t.ctl.signal });
    if (!res.ok) throw new Error((await res.json()).detail);
    const reader = res.body.getReader(), dec = new TextDecoder();
    let buf = "";
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      const events = buf.split("\n\n"); buf = events.pop();
      for (const ev of events) {
        if (!ev.startsWith("data: ")) continue;
        const e = JSON.parse(ev.slice(6));
        if (e.chat_id) { t.chatId = e.chat_id; if (!t.detached) chatId = e.chat_id; }
        if (e.user_msg_id) t.userMsgId = e.user_msg_id;
        if (e.status && !got) body.innerHTML = `<span class="muted">${esc(e.status)}</span>`;
        if (e.notice) d.insertBefore(el("div", "notice", "⚠ " + esc(e.notice)), body);
        if (e.laya) d.insertBefore(el("div", "tool laya", `${icon("spark")} Laya ${esc(e.laya)}`), body);
        if (e.rule) d.insertBefore(ruleChip(e.rule), body);
        if (e.fixed) d.insertBefore(el("div", "tool", `🔧 Checked and fixed: ${esc(e.fixed.join("; "))}`), body);
        if (e.skills) d.insertBefore(skillChip(e.skills), body);
        if (e.plan) d.insertBefore(planBox(e.plan, true), d.querySelector(".prog3d") || body);
        if (e.code) d.insertBefore(codeBox(e.code), body);
        if (e.progress3d) d.insertBefore(progress3dBox(e.progress3d), body);
        if (e.model3d) { d.querySelector(".prog3d")?.remove(); d.insertBefore(model3dCard(e.model3d, esc), body); }
        if (e.print3d) d.insertBefore(printCard(e.print3d), body);
        if (e.calc) d.insertBefore(calcCard(e.calc), body);
        if (e.team) d.insertBefore(teamCard(e.team), body);
        if (e.apps?.length) d.insertBefore(appCards(e.apps), body);
        if (e.forge) d.insertBefore(forgeCard(e.forge), body);
        if (e.bg) d.insertBefore(bgCard(e.bg), body);
        if (e.geo) d.insertBefore(geoCard(e.geo), body);
        if (e.project) putProject(d, e.project, body, projHandlers);
        if (e.paper) d.insertBefore(paperCard(e.paper), body);
        if (e.choices) setTimeout(() => d.append(choiceBox(e.choices)), 0);
        if (e.think) {
          if (!thinkEl) { thinkEl = el("details", null, "<summary>Thinking…</summary><div></div>"); d.insertBefore(thinkEl, body); }
          think += e.think; thinkEl.lastChild.textContent = think;
        }
        if (e.approve) d.insertBefore(askCard(e.approve), body);
        if (e.open_picture) viewPicture(e.open_picture);  // "click on the third rabbit"
        if (e.tool) {
          t.usedTool = true; d.insertBefore(toolCard(e), body);
          if (e.result?.pictures?.length) d.insertBefore(pictureGrid(e.result.pictures), body);
          if (e.result?.videos?.length) d.insertBefore(videoGrid(e.result.videos), body);
          if (e.tool === "web_search" && e.result?.results?.length) d.insertBefore(linkList(e.result.results.slice(0, 6)), body);
          if (e.result?.job) d.insertBefore(jobBox(e.result.job), body);
          if (e.result?.clip) d.insertBefore(clipBox(e.result.clip), body);
        }
        if (e.replace !== undefined) {  // self-check: the answer claimed something false -> the true one replaces it
          got = e.replace; renderText(body, got);
          if (voice) voice = talker(store.get("voice", ""));
        }
        if (e.delta) { got += e.delta; if (!t.detached) { voice?.add(e.delta); renderText(body, got); $("log").scrollTop = $("log").scrollHeight; } }
        if (e.error) { d.classList.add("error"); body.textContent = e.error; }
      }
    }
    if (thinkEl) thinkEl.firstChild.textContent = "Reasoning";
    if (!got && !d.classList.contains("error") && !t.stopped) body.innerHTML = `<span class="muted">(no text reply)</span>`;
  } catch (e) {
    if (!t.stopped) { d.classList.add("error"); body.textContent = "Couldn't reach the app: " + e.message; }
  }
  if (turn === t) { setBusy(false); turn = null; }
  if (t.detached) {  // you moved to another chat meanwhile: the answer is saved; refresh only if that chat is open again
    if (chatId === t.chatId) await openChat(chatId, true); else loadConvs();
    return;
  }
  if (t.stopped && !got && !t.usedTool) {
    // Stopped before any answer: undo the send and put the message back in the box to fix it (in ITS chat only).
    if (t.chatId && t.userMsgId && t.chatId === chatId) {
      try {
        const r = await api(`/api/chats/${t.chatId}/truncate`, json("POST", { from_id: t.userMsgId }));
        if (r.deleted_chat) chatId = null;
      } catch {}
    }
    $("input").value = t.text === "What's in this image?" && t.imgs.length ? "" : t.text;
    images = t.imgs; paintThumbs();
    if (chatId) await openChat(chatId); else { hello(); loadConvs(); }
    hint("Stopped — your message is back in the box. Fix it and press Enter.");
    $("input").focus();
    return;
  }
  const reply = got;
  if (chatId) await openChat(chatId);  // refresh so every message gets its Edit/Regenerate id
  if (voice && !t.stopped) {
    voice.end();
    try { await voice.done; } catch {}
    if (voiceMode() === "hands" && reply) startListening();  // (not if you interrupted her: then it's already listening)
  }
}

function submit() {
  cancelVoiceSend();
  const t = $("input").value.trim();
  if ((!t && !images.length && !files.length) || busy) return;
  if (document.querySelector("#log .msg.working")) {  // this chat's last answer is still being made (in the background)
    return hint("Still working on the last message here — wait a moment, or press “Stop it”.");
  }
  if (files.some(f => f.busy)) return hint("Still reading the attached files — a moment…");
  $("input").value = ""; $("input").style.height = "";
  const imgs = images, att = files.filter(f => f.ids.length); images = []; files = []; paintThumbs();
  const ids = att.flatMap(f => f.ids);
  send(t || (ids.length ? "Look at what I attached and tell me what's in it." : "What's in this image?"), imgs,
    ids.length ? { attachments: ids, attInfo: att.map(f => ({ name: f.name, kind: f.kind, note: f.note })) } : {});
}
$("send").onclick = () => (busy ? stopChat() : submit());
document.addEventListener("keydown", (e) => {
  if (e.key !== "Escape" || !$("p-chat").classList.contains("on")) return;
  if (voiceTimer) { cancelVoiceSend(); hint("Not sent — edit the text, then press Enter."); $("input").focus(); }
  else if (busy) stopChat();
});
function hint(text) {
  const h = $("chatHint");
  h.textContent = text; h.hidden = !text;
  clearTimeout(hint.t);
  if (text) hint.t = setTimeout(() => { h.hidden = true; }, 6000);
}
// ---------- the Skills menu (next to Voice) and "/" commands — like Claude's skills, connectors and slash commands
let menuData = null;
async function menuLoad() {
  try { menuData = await api("/api/skills"); } catch { menuData = { skills: [], commands: [], plugins: [], rules: [] }; }
  return menuData;
}
function menuPick(word) {
  const inp = $("input");
  inp.value = `/${word} ` + inp.value.replace(/^\s*\/[\w-]*\s*/, "");
  $("skillMenu").hidden = true;
  inp.focus(); inp.setSelectionRange(inp.value.length, inp.value.length);
}
async function menuShow(filter = "") {
  const d = menuData || await menuLoad();
  const box = $("skillMenu"), f = filter.toLowerCase();
  const ok = (...xs) => !f || xs.some(x => (x || "").toLowerCase().includes(f));
  const row = (word, label, hint) => {
    const b = el("button", "mi", `<span class="mono">/${esc(word)}</span><b>${esc(label)}</b><span class="muted small">${esc(hint || "")}</span>`);
    b.type = "button"; b.title = hint || label;
    b.onclick = () => menuPick(word);
    return b;
  };
  const sec = (title, items) => { if (items.length) box.append(el("div", "mh", esc(title)), ...items); };
  box.innerHTML = "";
  sec("Commands", d.commands.filter(c => ok(c.cmd, c.label)).map(c => row(c.cmd, c.label, c.hint)));
  sec("Skills — used by themselves when a message needs them · pick one to force it · tick = on", d.skills
    .filter(s => ok(s.id, s.name, s.description)).map(s => {
      const b = row(s.id, s.name, s.description);
      const cb = Object.assign(el("input"), { type: "checkbox", checked: s.enabled, title: "On / off" });
      cb.onclick = (e) => e.stopPropagation();
      cb.onchange = async () => { menuData = await api(`/api/skills/${s.id}`, json("PUT", { enabled: cb.checked })); };
      b.append(cb);
      return b;
    }));
  sec("Plugins (tools)", d.plugins.filter(p => ok(p.id, p.name)).map(p => row(p.id, p.name, p.description)));
  if (!f && d.rules.length) sec(`Rules I always follow (${d.rules.length}) — change them in Memory`,
    d.rules.map(r => el("div", "mi rule", `📌 ${esc(r.text)}`)));
  if (!f) box.append(el("div", "mh", "Add your own skill (a folder with a SKILL.md)"), addRow("Skill folder, e.g. C:\\Users\\you\\my-skill",
    "Add skill", async (path) => { menuData = await api("/api/skills", json("POST", { path })); menuShow(); }));
  box.querySelector(".mi")?.classList.add("hot");
  box.hidden = !box.querySelector(".mi");
}
function addRow(placeholder, label, onAdd) {  // a folder path + button, inside a menu
  const r = el("div", "addrow");
  const inp = Object.assign(el("input"), { placeholder });
  const b = button(label, "sm", async () => {
    const path = inp.value.trim();
    if (!path) return inp.focus();
    b.disabled = true;
    try { await onAdd(path); } catch (e) { alert(e.message); } finally { b.disabled = false; }
  });
  inp.onkeydown = (e) => { e.stopPropagation(); if (e.key === "Enter") b.click(); };
  r.append(inp, b);
  return r;
}
// ---------- the Plugins menu (next to Skills): tools the AI can use — on/off, use one now, add your own folder
async function plugMenuShow() {
  let list = [];
  try { list = await api("/api/plugins"); } catch {}
  const box = $("skillMenu");
  box.innerHTML = "";
  box.append(el("div", "mh", "Plugins — tools the AI uses by itself when needed · pick one to use it now · tick = on"));
  for (const p of list) {
    const usable = p.enabled && p.ready;
    const b = el("button", "mi", `<span class="mono">/${esc(p.id)}</span><b>${esc(p.name || p.id)}</b>`
      + `<span class="muted small">${esc(p.ready ? (p.about || p.description || "") : "not set up yet")}</span>`);
    b.type = "button"; b.title = p.description || "";
    b.onclick = () => { if (usable) menuPick(p.id); else alert("Switch it on first (the tick box)."); };
    const cb = Object.assign(el("input"), { type: "checkbox", checked: p.enabled, title: "On / off" });
    cb.onclick = (e) => e.stopPropagation();
    cb.onchange = async () => { await api(`/api/plugins/${p.id}`, json("PUT", { enabled: cb.checked })); menuData = null; plugMenuShow(); };
    b.append(cb);
    if (!p.builtin) {
      const rm = button("Remove", "sm danger", async (e) => {
        e?.stopPropagation?.();
        if (!confirm(`Remove the plugin “${p.name || p.id}”? (Its folder stays on your PC.)`)) return;
        await api(`/api/plugins/${p.id}`, { method: "DELETE" }); menuData = null; plugMenuShow();
      });
      rm.addEventListener("click", (e) => e.stopPropagation());
      b.append(rm);
    }
    box.append(b);
  }
  box.append(el("div", "mh", "Add a plugin (a folder with a plugin.json — plugins run programs: only add ones you trust)"),
    addRow("Plugin folder, e.g. C:\\Users\\you\\MyPlugin", "Add plugin", async (path) => {
      if (!confirm("Add this plugin? Plugins run programs on this PC — only add ones you trust.")) return;
      await api("/api/plugins", json("POST", { path })); menuData = null; plugMenuShow();
    }));
  box.hidden = false;
}
$("plugChip").onclick = (e) => {
  e.stopPropagation();
  const open = !$("skillMenu").hidden && $("skillMenu").dataset.kind === "plugins";
  $("skillMenu").hidden = true;
  if (!open) { $("skillMenu").dataset.kind = "plugins"; plugMenuShow(); }
};
$("skillsChip").onclick = (e) => {
  e.stopPropagation();
  const open = !$("skillMenu").hidden && $("skillMenu").dataset.kind === "skills";
  $("skillMenu").hidden = true;
  if (!open) { $("skillMenu").dataset.kind = "skills"; menuData = null; menuShow(); }
};
document.addEventListener("click", (e) => { if (!$("skillMenu").contains(e.target)) $("skillMenu").hidden = true; });
$("input").addEventListener("input", () => {  // typing "/" (or "/des") opens the menu, filtered
  const m = $("input").value.match(/^\/([\w-]*)$/);
  if (m) { $("skillMenu").dataset.kind = "skills"; menuShow(m[1]); } else $("skillMenu").hidden = true;
});
$("input").addEventListener("keydown", (e) => {  // while the menu is open: Enter / Tab picks, arrows move, Esc closes
  const box = $("skillMenu");
  if (box.hidden) return;
  const items = [...box.querySelectorAll("button.mi")], i = items.findIndex(x => x.classList.contains("hot"));
  if (e.key === "Escape") { box.hidden = true; e.preventDefault(); e.stopImmediatePropagation(); }
  else if ((e.key === "Enter" || e.key === "Tab") && i >= 0 && /^\/[\w-]*$/.test($("input").value)) {
    e.preventDefault(); e.stopImmediatePropagation(); items[i].click();
  } else if (e.key === "ArrowDown" || e.key === "ArrowUp") {
    e.preventDefault();
    items[i]?.classList.remove("hot");
    const n = items[(i + (e.key === "ArrowDown" ? 1 : -1) + items.length) % items.length];
    n?.classList.add("hot"); n?.scrollIntoView({ block: "nearest" });
  }
});
$("input").addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); submit(); } });
$("input").addEventListener("input", (e) => { e.target.style.height = ""; e.target.style.height = Math.min(220, e.target.scrollHeight) + "px"; });

// ---------- the + menu (like Claude's): photos (shrunk here, keeps the model fast), any file, videos, a whole folder.
// Files are read by the app on this PC (/api/attachments): text, PDF, Word, Excel, code, 3D sizes, zip lists; a video
// becomes frames the vision model watches + what is said in it. Nothing is ever opened with another program or run.
let files = [];  // attached, not sent yet: { name, kind, note, ids, busy }
const KIND_ICON = { image: "🖼", video: "🎬", audio: "🎵", "3d": "🧊", doc: "📄", text: "📄", zip: "🗜", program: "⛔",
  other: "📎", folder: "📁" };
$("attach").onclick = (e) => {
  e.stopPropagation();
  const box = $("skillMenu");
  if (!box.hidden && box.querySelector(".attrows")) { box.hidden = true; return; }
  const row = (ic, label, hint, fn) => {
    const b = el("button", "mi att", `<span class="mono">${ic}</span><b>${esc(label)}</b><span class="muted small">${esc(hint)}</span>`);
    b.type = "button"; b.onclick = () => { box.hidden = true; fn(); };
    return b;
  };
  box.innerHTML = "";
  box.append(el("div", "mh attrows", "Add to your message"),
    row("📎", "Files, photos or videos", "pictures · PDF, Word, Excel · text and code · 3D · zip · video · audio", () => $("attachFile").click()),
    row("📁", "A folder", "every readable file in it (code, notes, a project…)", () => $("attachDir").click()));
  box.querySelector(".mi").classList.add("hot");
  box.hidden = false;
};
async function upload(file, rel = "") {
  const fd = new FormData(); fd.append("file", file);
  const r = await fetch(`/api/attachments?path=${encodeURIComponent(rel)}`, { method: "POST", body: fd });
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText);
  return r.json();
}
$("attachFile").onchange = async () => {
  const list = [...$("attachFile").files]; $("attachFile").value = "";
  for (const f of list) {
    if (f.type.startsWith("image/") && !/gif|svg/.test(f.type) && f.size < 30e6) {
      try { images.push(await shrink(f)); paintThumbs(); continue; } catch { /* not a picture after all: upload it */ }
    }
    const chip = { name: f.name, kind: "other", note: /^video\//.test(f.type) ? "watching the video…" : "reading…", ids: [], busy: true };
    files.push(chip); paintThumbs();
    try { const a = await upload(f); Object.assign(chip, { kind: a.kind, note: a.note, ids: [a.id], busy: false }); }
    catch (e) { files.splice(files.indexOf(chip), 1); alert(`${f.name}: ${e.message}`); }
    paintThumbs();
  }
};
$("attachDir").onchange = async () => {
  const all = [...$("attachDir").files]; $("attachDir").value = "";
  if (!all.length) return;
  const root = (all[0].webkitRelativePath || all[0].name).split("/")[0];
  const junk = /(^|\/)(\.git|node_modules|__pycache__|\.venv|venv|dist|build|\.idea|\.vs|\.vscode|bin|obj|target|\.next|\.cache)\//;
  const pick = all.filter(f => !junk.test(f.webkitRelativePath) && f.size < 20e6).slice(0, 300);
  const chip = { name: root, kind: "folder", note: `reading 0 / ${pick.length}…`, ids: [], busy: true };
  files.push(chip); paintThumbs();
  let done = 0;
  const queue = [...pick];
  const worker = async () => {
    while (queue.length) {
      const f = queue.shift();
      try { const a = await upload(f, f.webkitRelativePath); if (a.id) chip.ids.push(a.id); } catch { /* skipped */ }
      chip.note = `reading ${++done} / ${pick.length}…`; paintThumbs();
    }
  };
  await Promise.all([worker(), worker(), worker()]);
  const skipped = all.length - pick.length;
  Object.assign(chip, { busy: false, note: `${chip.ids.length} files` + (skipped ? ` (${skipped} skipped: build folders, big files)` : "") });
  paintThumbs();
};
function attList(items) {  // the attachments on a sent message; a folder's files are shown as one line
  const box = el("div", "attlist"), folders = {};
  for (const a of items) {
    const top = (a.path || a.name || "").includes("/") ? a.path.split("/")[0] : null;
    if (top) { (folders[top] = folders[top] || []).push(a); continue; }
    box.append(el("span", "fchip", `${KIND_ICON[a.kind] || "📎"} <b>${esc(a.name)}</b> <small>${esc(a.note || "")}</small>`));
  }
  for (const [name, list] of Object.entries(folders)) {
    const s = el("span", "fchip", `📁 <b>${esc(name)}</b> <small>${list.length} files</small>`);
    s.title = list.map(a => a.path).join("\n");
    box.append(s);
  }
  return box;
}
function shrink(file) {
  return new Promise((res, rej) => {
    const img = new Image();
    img.onload = () => {
      const s = Math.min(1, 1280 / Math.max(img.width, img.height));
      const c = Object.assign(document.createElement("canvas"), { width: img.width * s, height: img.height * s });
      c.getContext("2d").drawImage(img, 0, 0, c.width, c.height);
      res(c.toDataURL("image/jpeg", 0.85));
    };
    img.onerror = rej;
    img.src = URL.createObjectURL(file);
  });
}
function paintThumbs() {
  $("thumbs").innerHTML = "";
  images.forEach((src, i) => {
    const s = el("span"); s.append(Object.assign(el("img"), { src }));
    const x = el("button", null, "✕"); x.onclick = () => { images.splice(i, 1); paintThumbs(); };
    s.append(x); $("thumbs").append(s);
  });
  files.forEach((f, i) => {
    const s = el("span", "fchip" + (f.busy ? " busy" : ""), `${KIND_ICON[f.kind] || "📎"} <b>${esc(f.name)}</b> <small>${esc(f.note || "")}</small>`);
    const x = el("button", null, "✕"); x.title = "Remove"; x.onclick = () => { files.splice(i, 1); paintThumbs(); };
    s.append(x); $("thumbs").append(s);
  });
}

// ---------- chips
function paintChips() {
  $("toolsChip").classList.toggle("on", toolsOn);
  $("thinkChip").classList.toggle("on", thinking);
}
$("toolsChip").onclick = () => { toolsOn = !toolsOn; store.set("tools", toolsOn ? "1" : "0"); paintChips(); };
$("thinkChip").onclick = async () => { thinking = !thinking; paintChips(); await api("/api/settings", json("PUT", { thinking })); };
// "Python code": for 3D the AI writes its own Blender Python (a setting — the app's safety gate reads it, not the page)
let pythonOn = false;
function paintPy() {
  $("pyChip").classList.toggle("on", pythonOn);
  $("pyChip").lastChild.textContent = pythonOn ? "Python code: on" : "Python code";
}
$("pyChip").onclick = async () => {
  pythonOn = !pythonOn; paintPy();
  try { await api("/api/settings", json("PUT", { python_code: pythonOn })); } catch (e) { pythonOn = !pythonOn; paintPy(); alert(e.message); }
};
api("/api/settings").then(s => { pythonOn = !!s.python_code; paintPy(); }).catch(() => {});
// the AI's code with every try (error -> fix -> run -> look), like reading a programmer's log
function codeBox(c) {
  const tries = c.tries || [];
  const ok = tries.length && /ran/.test(tries[tries.length - 1].result);
  const box = el("details", "plan codebox", `<summary>🐍 The AI's Python code — ${tries.length} ${tries.length === 1 ? "try" : "tries"}${ok ? "" : " (didn't work)"}</summary>`
    + `<div class="tries">${tries.map(t => `<div>${/ran/.test(t.result) && !(t.details || []).length ? "✅" : /ran/.test(t.result) ? "🔧" : "❌"} `
      + `<b>Try ${t.try}</b>: ${esc(t.result)}${(t.details || []).length ? ` <span class="muted">— ${esc(t.details.join("; ").slice(0, 300))}</span>` : ""}</div>`).join("")}</div>`
    + `<pre></pre>`);
  box.querySelector("pre").textContent = c.text || "";
  box.append(button("Copy the code", "sm", () => navigator.clipboard.writeText(c.text || "")));
  return box;
}

// ---------- voice: tap to talk / auto-send when you stop talking / hands-free conversation
const voiceMode = () => $("voiceMode").value;
$("voiceMode").value = store.get("voiceMode", "off");
$("voiceMode").onchange = () => {
  store.set("voiceMode", voiceMode());
  if (voiceMode() === "hands") startListening();
  else if (voiceMode() === "off" && mic?.mode === "watch") closeMic();
};
// ---------- microphone (raw sound): while she talks it listens too, so you can interrupt her just by talking —
// like ChatGPT / Gemini voice. The half second before she stopped is kept, so your first words aren't lost.
let mic = null, transcribing = false, held = "";
// Sounds unfinished: ends with "…" or a joining word ("and", "that", "was" …) — you only paused to think.
const unfinished = (t) => /(\.\.\.|…)\s*$/.test(t) || /\b(and|but|or|so|because|that|the|a|an|to|of|was|is|are|were|i|my|with|for|in|on|if|then|like|what|which|when|about|from|at|by|into|as|than|very|want|wanted|need|going|gonna|said|și|si|dar|că|ca|sau|să|sa|la|de|cu|pe|care)[,]?\s*$/i.test(t);
$("mic").onclick = () => mic?.mode === "record" ? finishRecord() : startListening();  // while she talks: interrupts her
speech.addEventListener("change", (e) => {
  $("talking").hidden = !e.detail;
  $("talkTip").textContent = "or press Esc";
  if (e.detail && voiceMode() !== "off") watchWhileTalking();
  else if (!e.detail && mic?.mode === "watch") { mic.mode = "idle"; mic.closeT = setTimeout(closeMic, 1500); }
});
$("stopTalk").onclick = () => stopSpeaking();
// Hands-free only listens while this window is in front: a video or podcast in another window isn't you talking.
window.addEventListener("blur", () => {
  if (voiceMode() === "hands" && mic?.mode === "record" && !mic.spoke) {
    closeMic(); hint("Hands-free is paused while you're in another window.");
    $("input").placeholder = "Message Local AI…  (start with “remember …” to save a fact)";
  }
});
window.addEventListener("focus", () => {
  if (voiceMode() === "hands" && $("p-chat").classList.contains("on") && !mic && !busy && !transcribing && !isSpeaking())
    startListening();
});

async function openMic() {
  if (mic) { clearTimeout(mic.closeT); return mic; }
  const stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true,
    autoGainControl: true, channelCount: 1 } });  // echo cancellation: her own voice from the speakers is removed
  if (mic) { stream.getTracks().forEach(t => t.stop()); return mic; }
  const ctx = new AudioContext();
  if (ctx.state === "suspended") {  // Windows/Edge start sound only after a click in the app
    ctx.resume();
    await new Promise(r => setTimeout(r, 300));
    if (ctx.state === "suspended") {
      hint("Click anywhere in the app once so it can use the microphone.");
      document.addEventListener("pointerdown", () => ctx.resume(), { once: true });
    }
  }
  const node = ctx.createScriptProcessor(2048, 1, 1);  // ~43 ms pieces
  ctx.createMediaStreamSource(stream).connect(node);
  node.connect(ctx.destination);  // silent — the browser only runs it when connected
  mic = { stream, ctx, node, mode: "idle", t: 0, frames: [], ring: [], hist: [], loud: 0 };
  node.onaudioprocess = (e) => micFrame(e.inputBuffer.getChannelData(0));
  return mic;
}
function closeMic() {
  if (!mic) return;
  clearTimeout(mic.closeT);
  mic.node.onaudioprocess = null; mic.node.disconnect(); mic.ctx.close();
  mic.stream.getTracks().forEach(t => t.stop());
  mic = null;
  $("mic").classList.remove("rec");
}

async function watchWhileTalking() {
  try { await openMic(); } catch { return; }  // no microphone: Stop / Esc still work
  if (!isSpeaking() || mic.mode === "record") return;
  Object.assign(mic, { mode: "watch", t: 0, ring: [], hist: [], loud: 0 });
  $("talkTip").textContent = "or just start talking";
}

function micFrame(input) {
  const m = mic;
  if (!m || m.mode === "idle") return;
  const x = new Float32Array(input);
  const rms = Math.sqrt(x.reduce((a, v) => a + v * v, 0) / x.length);
  const ms = 1000 * x.length / m.ctx.sampleRate;
  m.t += ms;
  if (m.mode === "watch") {  // she is talking: are YOU talking over her?
    m.ring.push(x); if (m.ring.length > 24) m.ring.shift();  // the last ~1 s
    m.hist.push(rms); if (m.hist.length > 70) m.hist.shift();  // ~3 s of loudness (her voice through the mic + room)
    if (m.t < 700 || !document.hasFocus()) return;  // learn her echo first; in another window: a video isn't you
    const sorted = [...m.hist].sort((a, b) => a - b);
    const level = Math.max(0.04, sorted[Math.floor(sorted.length * 0.7)] * 3);
    m.loud = rms > level ? m.loud + ms : Math.max(0, m.loud - ms / 2);
    if (m.loud >= 350) {  // a real voice for ~0.35 s: you're talking — she stops and listens
      const quiet = Math.max(0.015, sorted[Math.floor(sorted.length * 0.1)] * 3);
      stopSpeaking();
      beginRecord(m.ring.slice(-14), quiet);
    }
    return;
  }
  m.frames.push(x);  // recording
  if (m.t <= m.calib) { m.floorSum += rms; m.floorN++; return; }  // first half second: learn how loud the room is
  if (m.floorN) { m.level = Math.max(0.012, (m.floorSum / m.floorN) * 2.5); m.floorN = 0; }
  if (rms > m.level) { m.spoke = true; m.quietFor = 0; } else m.quietFor += ms;
  if (m.auto && ((m.spoke && m.quietFor > 1500 && m.t > 1000) || m.t > 60000)) finishRecord();
  else if (m.t > 180000) finishRecord();
}

function beginRecord(before = [], level = 0) {
  const interrupted = before.length > 0;
  Object.assign(mic, { mode: "record", t: 0, frames: before, spoke: interrupted, quietFor: 0,
    calib: interrupted ? 0 : 500, floorSum: 0, floorN: 0, level: level || 0.02,
    auto: interrupted || voiceMode() === "auto" || voiceMode() === "hands" });
  $("mic").classList.add("rec");
  $("input").placeholder = interrupted ? "Listening… (she stopped — go on)" : "Listening… (speak, then pause)";
}

async function startListening() {
  stopSpeaking();  // never record her own voice
  if (busy || transcribing || mic?.mode === "record") return;
  try { await openMic(); } catch { alert("The microphone isn't available — allow it for this app."); return; }
  beginRecord();
}

async function finishRecord() {
  const m = mic;
  if (!m || m.mode !== "record") return;
  const frames = m.frames, rate = m.ctx.sampleRate, auto = m.auto;
  closeMic();
  $("input").placeholder = "Transcribing…";
  const fd = new FormData();
  fd.append("file", toWav(frames, rate), "voice.wav");
  transcribing = true;
  try {
    let { text } = await api("/api/stt", { method: "POST", body: fd });
    // Interrupted while she was still writing: she finishes writing it (it stays in the chat and she remembers
    // it) — then your words go in.
    for (let i = 0; busy && i < 600; i++) await new Promise(r => setTimeout(r, 200));
    transcribing = false;
    const heard = (text || "").trim(), said = [held, heard].filter(Boolean).join(" ");
    if (heard && auto && voiceMode() !== "off" && unfinished(heard) && said.length < 800) {
      held = said; $("input").value = said;
      hint("…go on — I'm listening for the rest.");
      startListening();
      return;
    }
    held = "";
    if (!said) { if (voiceMode() === "hands") startListening(); return; }
    text = said;
    // Voice off = dictation into the box. Hands-free = a conversation: sent at once.
    // Other voice modes: shown for 2 s so a mishearing can be fixed, then sent.
    if (voiceMode() === "off") { $("input").value += ($("input").value ? " " : "") + text; $("input").focus(); }
    else if (voiceMode() === "hands") { $("input").value = text; submit(); }
    else voiceSend(text);
  } catch (e) { alert("Transcription failed: " + e.message); }
  finally { transcribing = false; $("input").placeholder = "Message Local AI…  (start with “remember …” to save a fact)"; }
}

export function toWav(frames, rate) {  // raw microphone sound -> 16 kHz mono WAV (what speech recognition uses)
  const len = frames.reduce((a, f) => a + f.length, 0), all = new Float32Array(len);
  let o = 0;
  for (const f of frames) { all.set(f, o); o += f.length; }
  const step = rate / 16000, n = Math.floor(len / step), pcm = new Int16Array(n);
  for (let i = 0; i < n; i++) {
    const a = Math.floor(i * step), b = Math.max(a + 1, Math.floor((i + 1) * step));
    let sum = 0;
    for (let j = a; j < b; j++) sum += all[j];
    pcm[i] = Math.max(-1, Math.min(1, sum / (b - a))) * 32767;
  }
  const buf = new ArrayBuffer(44 + n * 2), v = new DataView(buf);
  const w = (p, str) => [...str].forEach((c, i) => v.setUint8(p + i, c.charCodeAt(0)));
  w(0, "RIFF"); v.setUint32(4, 36 + n * 2, true); w(8, "WAVE"); w(12, "fmt "); v.setUint32(16, 16, true);
  v.setUint16(20, 1, true); v.setUint16(22, 1, true); v.setUint32(24, 16000, true); v.setUint32(28, 32000, true);
  v.setUint16(32, 2, true); v.setUint16(34, 16, true); w(36, "data"); v.setUint32(40, n * 2, true);
  new Int16Array(buf, 44).set(pcm);
  return new Blob([buf], { type: "audio/wav" });
}

let voiceTimer = null;
function voiceSend(text) {
  $("input").value = text;
  let left = 2;
  hint(`Heard: “${text}” — sending in ${left} s. Press Esc or click the box to fix it.`);
  voiceTimer = setInterval(() => {
    left--;
    if (left > 0) { hint(`Heard: “${text}” — sending in ${left} s. Press Esc or click the box to fix it.`); return; }
    cancelVoiceSend(); hint("");
    submit();
  }, 1000);
}
function cancelVoiceSend() { clearInterval(voiceTimer); voiceTimer = null; }
$("input").addEventListener("mousedown", () => { if (voiceTimer) { cancelVoiceSend(); hint("Not sent — edit the text, then press Enter."); } });

onPage("chat", () => { loadConvs(); if (!chatId && !$("log").children.length) hello(); });

export async function initChat() {
  const s = await api("/api/settings");
  thinking = s.thinking !== false;
  paintChips();
  hello();
}
