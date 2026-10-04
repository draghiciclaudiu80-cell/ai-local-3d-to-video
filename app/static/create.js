import { $, api, button, el, esc, icon, json, mmss, onPage, tabs } from "./core.js";
import { open3d } from "./create3d.js";

let style = "None";
const createTab = tabs("createTabs", "createTab", "image", paint);
function paint(t = createTab()) {
  for (const k of ["image", "video", "movie", "model"]) $("c-" + k).hidden = k !== t;
  $("c-queue").hidden = t === "model";
  if (t === "movie") loadMovieOptions();
  if (t === "model") open3d();
}

async function loadStyles() {
  const list = await api("/api/styles");
  $("styleChips").innerHTML = "";
  for (const s of list) {
    const c = el("button", "chip" + (s === style ? " on" : ""), esc(s));
    c.onclick = () => { style = s; loadStyles(); };
    $("styleChips").append(c);
  }
}
async function activeName(modality, target) {
  try {
    const r = await api(`/api/models/${modality}`);
    const a = r.installed.find(m => m.active);
    $(target).innerHTML = a ? `Using <b class="mono">${esc(a.name)}</b> — change it in Models.` : `No ${modality} model yet — get one in <b>Models</b>.`;
  } catch {}
}
const size = (v) => v.split("x").map(Number);

// ---------- reference pictures: the same subject from up to 3 angles (shared by Image, Video and Movie).
// The picture-reading model turns them into one description that's added to what you make -> the subject stays the same.
const refs = { imgs: [null, null, null], subject: "", front: false, strength: 0.6, busy: false };
const ANGLES = ["Front", "Side", "Back"];
async function toDataUrl(file, max = 768) {  // smaller copy: faster to read, and nothing big is kept
  const img = await createImageBitmap(file);
  const k = Math.min(1, max / Math.max(img.width, img.height));
  const c = Object.assign(document.createElement("canvas"), { width: Math.round(img.width * k), height: Math.round(img.height * k) });
  c.getContext("2d").drawImage(img, 0, 0, c.width, c.height);
  return c.toDataURL("image/jpeg", 0.9);
}
async function setRef(i, file) {
  if (!file || !file.type.startsWith("image/")) return;
  refs.imgs[i] = await toDataUrl(file); refs.subject = ""; paintRefs();
}
function paintRefs() {
  document.querySelectorAll("[data-refs]").forEach(box => {
    const kind = box.dataset.refs;
    box.innerHTML = `<div class="f mono small muted">Reference pictures (optional) — the same subject from up to 3 angles keeps it looking the same</div>`;
    const row = el("div", "refrow");
    ANGLES.forEach((a, i) => {
      const slot = el("label", "refslot" + (refs.imgs[i] ? " has" : ""),
        refs.imgs[i] ? `<img src="${refs.imgs[i]}" alt=""><span>${a}</span><button class="x" title="Remove">✕</button>` : `<span>+ ${a}</span><em>click · drop · paste</em>`);
      const inp = Object.assign(el("input"), { type: "file", accept: "image/*", hidden: true });
      inp.onchange = () => setRef(i, inp.files[0]);
      slot.append(inp);
      slot.ondragover = e => { e.preventDefault(); slot.classList.add("over"); };
      slot.ondragleave = () => slot.classList.remove("over");
      slot.ondrop = e => { e.preventDefault(); setRef(i, e.dataTransfer.files[0]); };
      const x = slot.querySelector(".x");
      if (x) x.onclick = e => { e.preventDefault(); refs.imgs[i] = null; refs.subject = ""; paintRefs(); };
      row.append(slot);
    });
    box.append(row);
    if (!refs.imgs.some(Boolean)) return;
    const sub = el("div", "refsub");
    sub.innerHTML = `<div class="row"><button class="btn sm">${refs.busy ? "Reading your pictures…" : refs.subject ? "Describe again" : "Describe my subject"}</button>
      <span class="muted small grow">The picture-reading model studies the angles; this description is added to what you make.</span></div>
      <textarea rows="2" placeholder="Describe my subject — or write it yourself"></textarea>`;
    sub.querySelector("textarea").value = refs.subject;
    sub.querySelector("button").disabled = refs.busy;
    sub.querySelector("button").onclick = () => describe().catch(e => alert(e.message));
    sub.querySelector("textarea").oninput = e => { refs.subject = e.target.value; };
    box.append(sub);
    if (kind === "image" && refs.imgs[0]) {
      const st = el("div", "row small");
      st.innerHTML = `<label class="row" style="align-items:center"><input type="checkbox" ${refs.front ? "checked" : ""} style="min-height:0"> Start from the front picture</label>
        <label class="row grow" style="align-items:center">how close <input type="range" min="0.3" max="0.9" step="0.05" value="${refs.strength}" class="grow"> free</label>`;
      st.querySelector("input[type=checkbox]").onchange = e => { refs.front = e.target.checked; };
      st.querySelector("input[type=range]").oninput = e => { refs.strength = +e.target.value; };
      box.append(st);
    }
  });
}
async function describe() {
  refs.busy = true; paintRefs();
  try { refs.subject = (await api("/api/refs/describe", json("POST", { images: refs.imgs.filter(Boolean) }))).description; }
  finally { refs.busy = false; paintRefs(); }
}
async function withSubject(text) {  // pictures added but not described yet: describe first (~20-40 s the first time)
  if (refs.imgs.some(Boolean) && !refs.subject.trim()) await describe();
  return refs.subject.trim() ? `${text}, ${refs.subject.trim()}` : text;
}
document.addEventListener("paste", e => {  // paste a picture on the Create page: goes into the first free angle
  if (!document.getElementById("p-create")?.offsetParent) return;
  const f = [...(e.clipboardData?.files || [])].find(x => x.type.startsWith("image/"));
  if (!f) return;
  e.preventDefault();
  const i = refs.imgs.findIndex(x => !x);
  setRef(i < 0 ? 0 : i, f);
});
paintRefs();

$("imgGo").onclick = async () => {
  const prompt = $("imgPrompt").value.trim();
  if (!prompt) return $("imgPrompt").focus();
  const [width, height] = size($("imgSize").value);
  try {
    const init = refs.front && refs.imgs[0] ? refs.imgs[0] : null;
    await api("/api/image", json("POST", { prompt: await withSubject(prompt), style, width, height, seed: +$("imgSeed").value,
      init, strength: refs.strength }));  // low = stays close to the front picture, high = freer
    loadQueue();
  } catch (e) { alert(e.message); }
};
$("vidGo").onclick = async () => {
  const prompt = $("vidPrompt").value.trim();
  if (!prompt) return $("vidPrompt").focus();
  const [width, height] = size($("vidSize").value);
  try { await api("/api/video", json("POST", { prompt: await withSubject(prompt), seconds: +$("vidSecs").value, width, height })); loadQueue(); }
  catch (e) { alert(e.message); }
};

async function loadMovieOptions() {
  const [voices, sounds] = await Promise.all([api("/api/models/voice"), api("/api/sounds")]);
  const keep = [$("mvVoice").value, $("mvMusic").value];
  $("mvVoice").innerHTML = voices.items.map(v => `<option value="${v.id}" ${v.active ? "selected" : ""}>${esc(v.name)}</option>`).join("");
  $("mvMusic").innerHTML = `<option value="">No music</option>` + sounds.map(s => `<option>${esc(s)}</option>`).join("");
  if (keep[0]) $("mvVoice").value = keep[0];
  $("mvMusic").value = keep[1] || "";
}
$("musicFile").onchange = async () => {
  const f = $("musicFile").files[0]; if (!f) return;
  const fd = new FormData(); fd.append("file", f);
  try { await api("/api/sounds", { method: "POST", body: fd }); await loadMovieOptions(); $("mvMusic").value = f.name; }
  catch (e) { alert(e.message); }
  $("musicFile").value = "";
};
$("mvGo").onclick = async () => {
  const lines = $("mvScenes").value.split("\n").map(s => s.trim()).filter(Boolean);
  if (!lines.length) return $("mvScenes").focus();
  const scenes = lines.map(l => ({ visual: l.split("|")[0].trim(), narration: (l.split("|")[1] || "").trim() }));
  const mins = Math.max(1, Math.round(scenes.length * (+$("mvSecs").value * 0.5 + 0.3)));
  if (!confirm(`Make ${scenes.length} scenes? On this PC that takes about ${mins} minutes.`)) return;
  try {
    await api("/api/movie", json("POST", { title: $("mvTitle").value, look: await withSubject($("mvLook").value), scenes,
      seconds: +$("mvSecs").value, voice: $("mvVoice").value, music: $("mvMusic").value || null }));
    loadQueue();
  } catch (e) { alert(e.message); }
};

// ---------- queue
let qTimer;
$("qStopAll").onclick = async () => {
  if (!confirm("Stop everything that's being made (pictures, videos, merges, movies)?")) return;
  try { await api("/api/stop-all", { method: "POST" }); } catch (e) { alert(e.message); }
  loadQueue();
};
export async function loadQueue() {
  const { jobs, movies } = await api("/api/jobs");
  const box = $("queue");
  box.innerHTML = "";
  for (const m of movies.filter(m => m.status !== "done").slice(0, 3)) {
    const j = el("div", "job", `<div class="top"><span class="p">🎞 <b>${esc(m.title)}</b> · ${esc(m.status)} · scene ${m.done_scenes}/${m.scenes}</span></div>
      <div class="bar"><i style="width:${Math.round(m.progress * 100)}%"></i></div>${m.error ? `<div class="notice">${esc(m.error)}</div>` : ""}`);
    const row = el("div", "row");
    if (m.status === "rendering" || m.status === "adding sound") {
      row.append(button(`${icon("stop")}Stop this movie`, "sm danger", async () => {
        if (!confirm(`Stop "${m.title}"? The ${m.done_scenes} scene(s) already made stay in the queue.`)) return;
        await api(`/api/movies/${m.id}`, { method: "DELETE" }); loadQueue();
      }));
    } else {
      row.append(button(`${icon("trash")}Remove`, "sm", async () => { await api(`/api/movies/${m.id}`, { method: "DELETE" }); loadQueue(); }));
    }
    j.append(row);
    box.append(j);
  }
  const shown = jobs.filter(j => !j.movie && j.status !== "cancelled").slice(0, 8);  // stopped = gone
  if (!shown.length && !box.children.length) box.innerHTML = `<div class="empty">Nothing yet — your creations appear here.</div>`;
  for (const j of shown) {
    const active = j.status === "running" || j.status === "queued";
    const card = el("div", "job", `<div class="top"><span class="p">${j.kind === "video" ? "🎬" : "🖼"} ${esc(j.prompt)}</span>
      <span class="muted small mono">${esc(j.status)}${j.elapsed != null ? " · " + mmss(j.elapsed) : ""}</span></div>
      ${active ? `<div class="bar"><i style="width:${Math.round(j.progress * 100)}%"></i></div><div class="muted small">${esc(j.phase || "Waiting…")}${j.eta != null ? ` · ~${mmss(j.eta)} left` : ""}</div>` : ""}
      ${j.note && active ? `<div class="notice">${esc(j.note)}</div>` : ""}
      ${j.error ? `<div class="notice" style="color:var(--bad)">${esc(j.error.split("\n").pop())}</div>` : ""}
      ${j.status === "done" ? (j.kind === "video" ? `<video src="/media/${j.file}" controls loop muted></video>` : `<img src="/media/${j.file}" alt="">`) : ""}`);
    const row = el("div", "row");
    row.append(button(active ? "Cancel" : `${icon("trash")}Delete`, "sm danger", async () => {
      if (!active && !confirm("Delete this permanently?")) return;
      await api(`/api/jobs/${j.id}`, { method: "DELETE" }); loadQueue();
    }));
    if (j.status === "done") row.prepend(Object.assign(el("a", "btn sm", `${icon("save")}Save`), { href: `/media/${j.file}`, download: j.file }));
    card.append(row);
    box.append(card);
  }
  clearTimeout(qTimer);
  if (jobs.some(j => j.status === "running" || j.status === "queued") || movies.some(m => m.status !== "done" && m.status !== "error"))
    qTimer = setTimeout(() => { if (document.getElementById("p-create").classList.contains("on")) loadQueue(); }, 2000);
}

onPage("create", () => { paint(); loadStyles(); loadQueue(); activeName("image", "imgModel"); activeName("video", "vidModel"); });
