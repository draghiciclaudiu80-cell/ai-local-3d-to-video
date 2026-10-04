import { $, api, button, el, esc, gb, icon, json, onPage, store, tabs } from "./core.js";

const HINT = {
  text: "The model you chat with. It also plans images, videos and movies and uses the web and PC when Tools is on — pick one over 2 GB for that. Models marked “sees images” understand pictures too.",
  vision: "Models that can SEE the screen. Computer use sends them screenshots and they decide where to click.",
  image: "Draws pictures. “Lightning” and “Turbo” models are fast (4 steps).",
  video: "Makes clips and movie scenes. Only Wan 2.1 video models work here; “distill” ones are about 5× faster.",
  voice: "Voices for reading replies aloud and for movie narration. Each is ~60 MB and runs on the CPU. Search above: 177 voices in 58 languages.",
  transcription: "Turns your speech into text for the 🎤 button and voice mode. If it mishears you: set your language below and try Whisper Small or Large v3 Turbo.",
  "3d": "AI models that turn a picture (or text) into a 3D model, or split a model into parts. Almost all need an NVIDIA graphics card, so this PC can't run them yet — download them now to keep them for a stronger PC. They're saved in models\\3d.",
};
const FIT = { good: "Runs well", tight: "Tight on memory", no: "Too big" };
const VERDICT = { ok: "✓ Works in this app", maybe: "? Might work", no: "✕ Won't work here" };
const SEARCHABLE = ["text", "vision", "image", "video", "voice", "transcription", "3d"];
const PLACEHOLDER = {
  voice: "Search voices by language or name — e.g. romanian, german, english…",
  transcription: "Search speech-to-text models on Hugging Face — e.g. whisper large, small.en…",
  "3d": "Search 3D AI models on Hugging Face — e.g. trellis, triposg, partcrafter, hunyuan3d…",
};
let maxGb = +store.get("maxGb", "0");
let pollT, searchT, searchSeq = 0;
const tab = tabs("modelTabs", "modelTab", "text", () => { $("hfResults").innerHTML = ""; $("hfQuery").value = ""; load(); });

const fits = (gbs) => !maxGb || gbs <= maxGb;
const badge = (fit, why) => `<span class="badge ${fit}" title="${esc(why || "")}">${FIT[fit] || fit}</span>`;
const params = (n) => n ? `<span class="badge info">${n >= 1e9 ? (n / 1e9).toFixed(n < 1e10 ? 1 : 0).replace(/\.0$/, "") + "B" : Math.round(n / 1e6) + "M"} params</span>` : "";
const mcard = (html, cls = "") => el("div", "mcard " + cls, html);
const section = (title) => el("div", "sect", title);
const kctx = n => !n ? "" : n >= 1e6 ? `${Math.round(n / 1048576)}M` : `${Math.round(n / 1024)}k`;

/** What a model can do, as symbols (hover one for the words). */
function capBadges(c) {
  if (!c) return "";
  const b = (sym, title, cls = "") => `<span class="cap ${cls}" title="${esc(title)}">${sym}</span>`;
  const out = [];
  if (c.embedding) return b("🧩", "Embeddings: the memory search model — not for chatting", "dim");
  if (c.tools) out.push(b("🔧", "Tool calling: it can use the app's tools by itself (web search, pictures, 3D, calculators…)"));
  if (c.vision) out.push(b("👁", "Vision: it sees pictures you attach (and screenshots)"));
  else if (c.vision_missing) out.push(b("👁?", "A vision model, but its vision add-on file (mmproj) isn't next to it — download it to let it see", "warn"));
  if (c.video) out.push(b("🎬", c.video_trained ? "Video: trained on video — it watches a clip's frames and hears its words (best)" : "Video: watches a clip as frames + its spoken words"));
  if (c.thinking) out.push(b("🧠", "Thinking: it can reason step by step before answering (slower, smarter)"));
  if (c.audio) out.push(b("🎤", "Audio: it can hear sound files directly"));
  if (c.context) out.push(b(`📏${kctx(c.context)}`, `Context: it can read up to ${c.context.toLocaleString()} tokens at once (the app uses your Memory length setting)`, "dim"));
  if (!c.tools && c.template) out.push(b("✋", "No tool calling: the app plans for it instead (slower, works)", "dim"));
  return `<span class="caps">${out.join("")}</span>`;
}
const LEGEND = `<div class="muted small caplegend">🔧 uses tools by itself · 👁 sees images · 🎬 understands video · 🧠 thinks first · 🎤 hears audio · 📏 how much it reads at once · ✋ no tool calling — hover a symbol for more</div>`;

/** The two helper models next to the chat model: the small model and Laya (System 1). Start / stop / swap / test. */
async function brainsCard(pane) {
  const box = el("div", "brains");
  pane.append(box);
  let r;
  try { r = await api("/api/brains"); } catch { box.remove(); return; }
  box.innerHTML = "";
  const dot = on => `<span class="dot ${on ? "on" : ""}" style="display:inline-block;margin-right:4px"></span>${on ? "running" : "stopped"}`;
  // the small model
  const sm = el("div", "mcard brain");
  sm.innerHTML = `<div class="name">Small model <span class="muted small">— a small chat model on the processor (3D designer option, “Small model only”)</span></div>
    <div class="meta">${r.small.name ? esc(r.small.name) + " · " + gb(r.small.size) : "none"} · ${dot(r.small.running)}${r.small.only ? " · <b>used as the chat model now</b>" : ""}</div>`;
  const pick = el("select", "grow");
  pick.innerHTML = r.small.choices.map(c => `<option value="${esc(c.path)}" ${c.path === r.small.path ? "selected" : ""}>${esc(c.name)} — ${gb(c.size)}${c.size > 3e9 ? " (big for a small model)" : ""}</option>`).join("");
  const capLine = el("div", "small");
  const showCaps = () => { const c = r.small.choices.find(x => x.path === pick.value); capLine.innerHTML = c ? capBadges(c.caps) : ""; };
  pick.onchange = showCaps; showCaps();
  const row = el("div", "row");
  row.append(pick, button("Use this one", "sm", async () => { await api("/api/brains/small", json("POST", { action: "use", path: pick.value })).catch(e => alert(e.message)); load(); }));
  row.append(r.small.running ? button("■ Stop", "sm ghost", async () => { await api("/api/brains/small", json("POST", { action: "stop" })); load(); })
    : button("▶ Start", "sm ghost", async e => { e.target.disabled = true; e.target.textContent = "Starting…"; await api("/api/brains/small", json("POST", { action: "start" })).catch(err => alert(err.message)); load(); }));
  sm.append(row, capLine);
  // Laya
  const ly = el("div", "mcard brain");
  const cur = r.laya.checkpoints.find(c => c.name === r.laya.model);
  ly.innerHTML = `<div class="name">Laya <span class="muted small">— the decision model (System 1, Jev-style): decides what you want in ~1 s, never writes text</span></div>
    <div class="meta">${r.laya.available ? esc(cur?.label || r.laya.model) + (cur ? " · " + gb(cur.size) : "") + " · " + dot(r.laya.running) : "not installed"}${r.laya.fixed ? "" : " · automatic"}</div>`;
  if (r.laya.available) {
    const lp = el("select", "grow");
    lp.innerHTML = `<option value="">Automatic (typed-decisions — tested best)</option>` + r.laya.checkpoints.map(c => `<option value="${esc(c.name)}" ${r.laya.fixed && c.name === r.laya.model ? "selected" : ""}>${esc(c.label)}${c.multilingual ? " — multilingual" : ""} · ${gb(c.size)}</option>`).join("");
    const lrow = el("div", "row");
    lrow.append(lp, button("Use this one", "sm", async () => {
      await api("/api/brains/laya", json("POST", lp.value ? { action: "use", model: lp.value } : { action: "auto" })).catch(e => alert(e.message)); load();
    }));
    lrow.append(r.laya.running ? button("■ Stop", "sm ghost", async () => { await api("/api/brains/laya", json("POST", { action: "stop" })); load(); })
      : button("▶ Start", "sm ghost", async e => { e.target.disabled = true; e.target.textContent = "Starting… (~15 s)"; await api("/api/brains/laya", json("POST", { action: "start" })).catch(err => alert(err.message)); load(); }));
    const out = el("div", "small laytest");
    lrow.append(button("🧪 Test Laya", "sm", async e => {
      e.target.disabled = true; out.innerHTML = `<span class="muted">Testing 12 messages… (first run loads Laya, ~20 s)</span>`;
      try {
        const t = await api("/api/brains/laya/test", { method: "POST" });
        out.innerHTML = `<b>${esc(t.verdict)}</b> — ${t.right}/${t.total} right overall; it was sure enough to act alone on ${t.acted} and got ${t.acted_right} of those right (act line ${t.act_at}); ~${t.avg_ms} ms each · ${esc(t.model)}`
          + `<details><summary>Every answer</summary>${t.rows.map(x => `<div class="mono">${x.ok ? "✓" : "✕"} ${esc(x.text)} → ${esc(x.got)} (${x.sure})${x.ok ? "" : " — wanted " + esc(x.want)}</div>`).join("")}</details>`;
      } catch (err) { out.innerHTML = `<span class="fitbad">${esc(err.message)}</span>`; }
      e.target.disabled = false;
    }));
    ly.append(lrow, out, el("div", "muted small", "New Laya models: put the folder (with model.safetensors + its config) in models\\laya-real — it shows up here. Test it before you keep it."));
  }
  box.append(sm, ly);
}

function sizeChips() {
  $("sizeChips").innerHTML = "";
  for (const v of [0, 2, 4, 8, 16]) {
    const c = el("button", "chip" + (v === maxGb ? " on" : ""), v ? `≤${v} GB` : "Any size");
    c.onclick = () => { maxGb = v; store.set("maxGb", v); sizeChips(); load(); if ($("hfQuery").value.trim().length > 1) search(); };
    $("sizeChips").append(c);
  }
}

async function useModel(modality, value) {
  try { await api("/api/models/active", json("POST", { modality, value })); } catch (e) { return alert(e.message); }
  load();
}

// ---------- downloads (all types, always on top)
async function downloadsPanel() {
  const list = (await api("/api/downloads")).filter(d => d.status === "running" || d.status === "error");
  const box = $("dlPanel");
  box.innerHTML = "";
  if (!list.length) return false;
  box.append(section("Downloading"));
  const g = el("div", "mgrid"); box.append(g);
  for (const d of list) {
    const running = d.status === "running";
    const c = mcard(`<div class="name">${esc(d.name)} <span class="badge info">${esc(d.modality)}</span></div>
      <div class="bar"><i style="width:${Math.round(d.progress * 100)}%"></i></div>
      <div class="meta">${Math.round(d.progress * 100)}% of ${d.size_gb.toFixed(1)} GB · ${esc(d.file)}${running ? ` · ${(d.speed / 1e6).toFixed(1)} MB/s` : ""}</div>
      ${d.error ? `<div class="why no">Stopped: ${esc(d.error)}</div>` : ""}<div class="acts"></div>`);
    const acts = c.querySelector(".acts");
    if (running) acts.append(button("Cancel", "sm danger", async () => {
      if (!confirm("Cancel this download? The part downloaded so far is deleted.")) return;
      await api(`/api/downloads/${d.id}`, { method: "DELETE" }); refreshSoon(300);
    }));
    else acts.append(button("Remove", "sm", async () => { await api(`/api/downloads/${d.id}`, { method: "DELETE" }); refreshSoon(0); }));
    g.append(c);
  }
  return list.some(d => d.status === "running");
}
function refreshAll() { load(); if ($("hfQuery").value.trim().length > 1) search(true); }
function refreshSoon(ms) { clearTimeout(pollT); pollT = setTimeout(() => { if ($("p-models").classList.contains("on")) load(); }, ms); }

// ---------- installed + curated list
async function load() {
  const t = tab();
  $("modelHint").textContent = HINT[t];
  $("searchRow").hidden = !SEARCHABLE.includes(t);
  $("hfQuery").placeholder = PLACEHOLDER[t] || "Search Hugging Face — start typing, e.g. qwen, llama, gemma…";
  const [r, downloading] = await Promise.all([api(`/api/models/${t}`), downloadsPanel()]);
  if (t !== tab()) return;  // a newer tab click already took over
  const pane = $("modelPane");
  pane.innerHTML = "";
  if (t === "transcription") languageCard(r);
  if (t === "3d") threeDPage(r);
  else if (t === "voice" || t === "transcription") simpleList(t, r.items);
  else {
    if (t === "text") { pane.append(section("Helper models")); await brainsCard(pane); }
    pane.append(section("On this device"));
    if (t === "text" || t === "vision") pane.append(el("div", null, LEGEND));
    const gi = el("div", "mgrid"); pane.append(gi);
    if (!r.installed.length) gi.append(el("div", "empty", "None yet — download one below, or search Hugging Face above."));
    for (const m of r.installed) gi.append(installedCard(t, m));
    pane.append(section("Recommended downloads"));
    const gs = el("div", "mgrid"); pane.append(gs);
    const shown = r.store.filter(s => fits(s.size_gb));
    if (!shown.length) gs.append(el("div", "empty", r.store.length ? "Nothing in this size — pick a bigger size above." : "You have everything from this list. Search Hugging Face above for more."));
    for (const s of shown) gs.append(storeCard(s));
  }
  if (downloading) refreshSoon(1500);
}

function installedCard(t, m) {
  const c = mcard(`<div class="name">${esc(m.name)}${m.vision && !m.caps ? ` <span class="badge info">sees images</span>` : ""}${m.fast ? ` <span class="badge info">fast</span>` : ""}</div>${m.caps ? `<div>${capBadges(m.caps)}${m.caps.params ? ` <span class="meta">${esc(m.caps.params)}</span>` : ""}</div>` : ""}
    <div class="meta">${gb(m.size)} · ${esc(m.arch || "")}${m.owned ? "" : " · " + esc(m.folder.split("\\").slice(-2).join("\\"))}</div>
    <div>${m.usable ? badge(m.fit, m.why) : `<span class="badge no">Can't use</span>`} <span class="meta">${esc(m.why)}</span></div><div class="acts"></div>`, m.active ? "active" : "");
  const acts = c.querySelector(".acts");
  if (m.active) acts.append(el("span", "active-mark", `${icon("check")}Active`));
  else if (m.usable) acts.append(button("Use", "sm primary", () => {
    if (m.fit === "no" && !confirm("This model is too big for this PC and may freeze it. Use it anyway?")) return;
    useModel(t, m.path);
  }));
  if (m.owned) acts.append(button(icon("trash"), "sm ghost", async () => {
    if (!confirm(`Delete ${m.name} (${gb(m.size)})?`)) return;
    try { await api("/api/models/file?path=" + encodeURIComponent(m.path), { method: "DELETE" }); } catch (e) { alert(e.message); }
    load();
  }));
  return c;
}

function storeCard(s) {
  const c = mcard(`<div class="name">${esc(s.name)}${s.tags.map(x => ` <span class="badge info">${esc(x)}</span>`).join("")}</div>
    <div class="meta">${s.size_gb} GB</div><div class="small">${esc(s.note)}</div><div>${badge(s.fit, s.why)} <span class="meta">${esc(s.why)}</span></div><div class="acts"></div>`);
  const acts = c.querySelector(".acts");
  if (s.download?.status === "running") acts.append(el("span", "meta", "Downloading — see above"));
  else acts.append(button(`${icon("download")}Download`, "sm " + (s.fit === "no" ? "danger" : "primary"), async () => {
    if (s.fit === "no" && !confirm("Too big for this PC — it may freeze or crash it. Download anyway?")) return;
    try { await api("/api/models/download", json("POST", { catalog_id: s.id })); } catch (e) { alert(e.message); }
    load();
  }));
  return c;
}

function simpleList(t, items) {
  $("modelPane").append(section(t === "voice" ? "Voices" : "Speech-to-text models"));
  const g = el("div", "mgrid"); $("modelPane").append(g);
  for (const v of items) g.append(smallCard(t, v));
}

function smallCard(t, v) {
  const extra = t === "voice" ? `${v.installed ? "on this PC" : "~60 MB download"}` : `${gb(v.size_gb * 1e9)}${v.note ? " · " + esc(v.note) : ""}`;
  const c = mcard(`<div class="name">${esc(v.name)}</div><div class="meta">${extra} · runs on the CPU</div><div class="acts"></div>`, v.active ? "active" : "");
  const acts = c.querySelector(".acts");
  const d = v.download;
  if (d?.status === "running") {  // same live progress as the other models
    acts.before(el("div", null, `<div class="bar"><i style="width:${Math.round(d.progress * 100)}%"></i></div>
      <div class="meta">Downloading · ${Math.round(d.progress * 100)}% · ${(d.speed / 1e6).toFixed(1)} MB/s — switches to it when done</div>`));
    acts.append(button("Cancel", "sm danger", async () => {
      await api(`/api/downloads/${d.id}`, { method: "DELETE" }); refreshAll();
    }));
  } else if (v.active) acts.append(el("span", "active-mark", `${icon("check")}Active`));
  else {
    if (d?.status === "error") acts.before(el("div", "why no", `Download stopped: ${esc(d.error)}`));
    acts.append(button(v.installed ? "Use" : `${icon("download")}${d?.status === "error" ? "Try again" : "Get & use"}`, "sm primary", async (e) => {
      e.currentTarget.disabled = true;
      try {
        if (v.installed) await useModel(t, v.id);
        else await api(t === "voice" ? `/api/voices/${encodeURIComponent(v.id)}` : `/api/whisper/${encodeURIComponent(v.id)}`, { method: "POST" });
      } catch (err) { alert(err.message); }
      refreshAll();
    }));
  }
  if (t === "voice") acts.append(button(`${icon("speak")}Test`, "sm", async (e) => {
    const b = e.currentTarget; b.disabled = true; if (!v.installed) b.textContent = "Downloading…";
    try { const r = await api("/api/tts", json("POST", { text: "Hello! This is how I sound. Salut, așa sun.", voice: v.id })); new Audio(URL.createObjectURL(await r.blob())).play(); }
    catch (err) { alert(err.message); }
    b.disabled = false; b.innerHTML = `${icon("speak")}Test`;
  }));
  return c;
}

function languageCard(r) {
  const c = mcard(`<div class="name">Language you speak</div><div class="meta">Setting it (instead of “detect”) helps a lot with accents and short messages.</div>
    <div class="acts"><select id="sttLang">${Object.entries(r.languages).map(([k, n]) => `<option value="${k}" ${k === r.language ? "selected" : ""}>${esc(n)}</option>`).join("")}</select></div>`);
  c.querySelector("select").onchange = async (e) => { await api("/api/settings", json("PUT", { stt_language: e.target.value })); };
  const g = el("div", "mgrid"); g.append(c); $("modelPane").append(g);
}

function whisperCard(m) {
  const c = mcard(`<div class="name">${esc(m.name)}</div>
    <div class="meta">by ${esc(m.author)} · ⬇ ${m.downloads.toLocaleString()} · ${esc(m.updated)}</div>
    <div class="why ${m.verdict}">${VERDICT[m.verdict]} — ${esc(m.reason)}</div>
    ${m.size ? `<div>${badge(m.fit, m.why)} <span class="meta">${gb(m.size)}</span></div>` : ""}<div class="acts"></div>`, m.verdict === "no" ? "no" : "");
  const acts = c.querySelector(".acts"), d = m.download;
  if (d?.status === "running") {
    acts.before(el("div", null, `<div class="bar"><i style="width:${Math.round(d.progress * 100)}%"></i></div><div class="meta">Downloading · ${Math.round(d.progress * 100)}%</div>`));
    acts.append(button("Cancel", "sm danger", async () => { await api(`/api/downloads/${d.id}`, { method: "DELETE" }); search(true); load(); }));
  } else if (m.present && m.active) acts.append(el("span", "active-mark", `${icon("check")}Active`));
  else if (m.present) {
    acts.append(el("span", "active-mark", `${icon("check")}On this PC`));
    acts.append(button("Use", "sm primary", async () => { await useModel("transcription", m.id); search(true); }));
  } else if (m.verdict === "ok") {
    if (d?.status === "error") acts.before(el("div", "why no", `Download stopped: ${esc(d.error)}`));
    acts.append(button(`${icon("download")}${d?.status === "error" ? "Try again" : "Download " + gb(m.size)}`, "sm primary", async (e) => {
      e.currentTarget.disabled = true;
      await startDl(m.repo, m.files, "transcription");
      search(true);
    }));
  }
  return c;
}

// ---------- 3D AI models: kept for a stronger PC (this one can't run them yet)
function threeDPage(r) {
  const pane = $("modelPane");
  pane.append(el("div", "notice", esc(r.why)));
  pane.append(section("On this device"));
  const gi = el("div", "mgrid"); pane.append(gi);
  if (!r.installed.length) gi.append(el("div", "empty", "None yet — download one below to keep it for later, or search Hugging Face above."));
  for (const m of r.installed) {
    const c = mcard(`<div class="name">${esc(m.name)}</div>
      <div class="meta">${gb(m.size)} · ${m.files} files · by ${esc(m.repo.split("/")[0])}${m.partial ? " · <b>not finished</b> — press Download again to go on" : ""}</div>
      <div class="meta">${esc(m.folder)}</div><div class="acts"></div>`);
    c.querySelector(".acts").append(button(icon("trash"), "sm ghost", async () => {
      if (!confirm(`Delete ${m.name} (${gb(m.size)})?`)) return;
      try { await api("/api/models3d?repo=" + encodeURIComponent(m.repo), { method: "DELETE" }); } catch (e) { alert(e.message); }
      load();
    }));
    gi.append(c);
  }
  pane.append(section("3D models to keep for later"));
  const gs = el("div", "mgrid"); pane.append(gs);
  const shown = r.store.filter(s => !s.size || fits(s.size / 1e9));
  if (!shown.length) gs.append(el("div", "empty", "Nothing in this size — pick a bigger size above."));
  for (const s of shown) gs.append(threeDCard(s));
}

function threeDCard(m) {
  const meta = m.author ? `by ${esc(m.author)} · ⬇ ${(m.downloads || 0).toLocaleString()} · ${esc(m.updated)}${m.task ? " · " + esc(m.task) : ""}` : "";
  const status = m.watch ? "Not released yet — check its page later" : m.verdict === "maybe"
    ? "? An NVIDIA card is here — the app can't start it yet" : "Keep for later — this PC can't run it yet";
  const c = mcard(`<div class="name">${esc(m.name)}${m.size ? ` <span class="badge info">${gb(m.size)}</span>` : ""}</div>
    ${meta ? `<div class="meta">${meta}</div>` : ""}${m.does ? `<div class="small">${esc(m.does)}</div>` : ""}
    ${m.needs ? `<div class="meta">Needs: ${esc(m.needs)}</div>` : ""}
    ${m.license ? `<div class="small ${m.license.startsWith("⚠") ? "fitbad" : "muted"}">${esc(m.license)}</div>` : ""}
    <div class="why ${m.verdict === "maybe" ? "maybe" : "no"}">${status}</div><div class="acts"></div>`);
  const acts = c.querySelector(".acts"), d = m.download;
  const open = url => api("/api/open", json("POST", { url })).catch(e => alert(e.message));
  if (m.watch) acts.append(button("Open its page", "sm", () => open(m.watch)));
  else if (d?.status === "running") {
    acts.before(el("div", null, `<div class="bar"><i style="width:${Math.round(d.progress * 100)}%"></i></div>
      <div class="meta">Downloading · ${Math.round(d.progress * 100)}% · ${(d.speed / 1e6).toFixed(1)} MB/s</div>`));
    acts.append(button("Cancel", "sm danger", async () => {
      if (!confirm("Cancel this download? The part downloaded so far is deleted.")) return;
      await api(`/api/downloads/${d.id}`, { method: "DELETE" }); refreshAll();
    }));
  } else if (m.present) acts.append(el("span", "active-mark", `${icon("check")}On this PC — kept for later`));
  else if (m.gated) acts.append(el("span", "meta", "Needs a Hugging Face login to download — not supported"));
  else {
    if (d?.status === "error") acts.before(el("div", "why no", `Download stopped: ${esc(d.error)}`));
    acts.append(button(`${icon("download")}${d?.status === "error" ? "Try again" : "Download" + (m.size ? " " + gb(m.size) : "")}`, "sm", async (e) => {
      if (!confirm(`${m.name}${m.size ? " (" + gb(m.size) + ")" : ""}: this PC can't run it yet — it's kept in models\\3d for a stronger PC. Download it now?`)) return;
      e.currentTarget.disabled = true;
      try { await api("/api/models/download", json("POST", { repo: m.repo, modality: "3d" })); } catch (err) { alert(err.message); }
      refreshAll();
    }));
  }
  if (m.repo) acts.append(button("Page", "sm ghost", () => open("https://huggingface.co/" + m.repo)));
  return c;
}

// ---------- Hugging Face search: results appear while you type
let resT;
async function search(quiet = false) {
  const q = $("hfQuery").value.trim();
  const box = $("hfResults");
  clearTimeout(resT);
  if (q.length < 2) { box.innerHTML = ""; return; }
  const seq = ++searchSeq, t = tab();
  if (!quiet) box.innerHTML = `<div class="search-status">Searching ${t === "voice" ? "voices" : "Hugging Face"} for “${esc(q)}”…</div>`;
  let list;
  try { list = await api(`/api/hf/search?q=${encodeURIComponent(q)}&modality=${t}`); }
  catch (e) { if (seq === searchSeq) box.innerHTML = `<div class="notice">${esc(e.message)}</div>`; return; }
  if (seq !== searchSeq) return;  // the user kept typing — a newer search is on its way
  box.innerHTML = "";
  const head = el("div", "row", `<div class="sect grow">${t === "voice" ? "Voices" : "Hugging Face"} · “${esc(q)}” · ${list.length} found</div>`);
  head.append(button("Close", "sm ghost", () => { $("hfQuery").value = ""; box.innerHTML = ""; }));
  box.append(head);
  if (t === "3d") {
    const shown3 = list.filter(m => !maxGb || !m.size || m.size / 1e9 <= maxGb);
    if (!shown3.length) { box.append(el("div", "empty", list.length ? "Nothing in this size — pick a bigger size." : "No 3D models found. Try: trellis, triposg, hunyuan3d, partcrafter, image-to-3d…")); return; }
    const g3 = el("div", "mgrid"); box.append(g3);
    for (const m of shown3) g3.append(threeDCard(m));
    if (list.some(m => m.download?.status === "running"))
      resT = setTimeout(() => { if ($("p-models").classList.contains("on")) search(true); }, 1500);
    return;
  }
  if (t === "voice" || t === "transcription") {
    const shownV = t === "transcription" ? list.filter(m => !maxGb || m.size / 1e9 <= maxGb) : list;
    if (!shownV.length) { box.append(el("div", "empty", t === "voice" ? "No voices match. Try a language: english, romanian, german, spanish…" : "Nothing found. Try: whisper, whisper large, distil…")); return; }
    const gv = el("div", "mgrid"); box.append(gv);
    for (const m of shownV) gv.append(t === "voice" ? smallCard("voice", m) : whisperCard(m));
    if (list.some(m => m.download?.status === "running"))
      resT = setTimeout(() => { if ($("p-models").classList.contains("on")) search(true); }, 1500);
    return;
  }
  const shown = list.filter(m => !maxGb || !m.rec || m.total / 1e9 <= maxGb);
  if (!shown.length) { box.append(el("div", "empty", list.length ? "Nothing in this size — pick a bigger size." : "No models found. Try another name (qwen, llama, gemma, sdxl, wan…).")); return; }
  const g = el("div", "mgrid"); box.append(g);
  for (const m of shown) g.append(resultCard(m, t));
  // While something from these results downloads, keep the cards live (progress -> "On this PC").
  if (list.some(m => m.download?.status === "running"))
    resT = setTimeout(() => { if ($("p-models").classList.contains("on")) search(true); }, 1500);
}

function resultCard(m, t) {
  const withProj = m.proj && (t === "text" || t === "vision");
  const quant = m.rec ? (m.rec.name.match(/(IQ\d_\w+?|Q\d_K_[SML]|Q\d_K|Q\d_\d|BF16|F16|F32)(?=[.-])/i) || [""])[0].toUpperCase() : "";
  const size = m.rec ? `${quant ? esc(quant) + " · " : ""}${gb(m.rec.size)}${withProj ? ` + ${gb(m.proj.size)} vision add-on` : ""}` : "no model files";
  const c = mcard(`<div class="name">${esc(m.name)} ${params(m.params)}${m.vision ? ` <span class="badge info">sees images</span>` : ""}</div>
    <div class="meta">by ${esc(m.author)} · ⬇ ${m.downloads.toLocaleString()} · ♥ ${m.likes} · ${esc(m.updated)}${m.arch ? " · " + esc(m.arch) : ""}</div>
    <div class="why ${m.verdict}">${VERDICT[m.verdict]} — ${esc(m.reason)}</div>
    ${m.rec ? `<div>${badge(m.fit, m.why)} <span class="meta">${size}</span></div>` : ""}<div class="acts"></div><div class="files" hidden></div>`, m.verdict === "no" ? "no" : "");
  const acts = c.querySelector(".acts");
  const d = m.download;
  if (d?.status === "running") {
    acts.before(el("div", null, `<div class="bar"><i style="width:${Math.round(d.progress * 100)}%"></i></div>
      <div class="meta">Downloading · ${Math.round(d.progress * 100)}% · ${(d.speed / 1e6).toFixed(1)} MB/s</div>`));
    acts.append(button("Cancel", "sm danger", async () => {
      if (!confirm("Cancel this download? The part downloaded so far is deleted.")) return;
      await api(`/api/downloads/${d.id}`, { method: "DELETE" }); search(true); load();
    }));
  } else if (m.present && m.active) acts.append(el("span", "active-mark", `${icon("check")}Active`));
  else if (m.present) {
    acts.append(el("span", "active-mark", `${icon("check")}On this PC`));
    if (m.path && m.verdict !== "no") acts.append(button("Use", "sm primary", async () => { await useModel(t, m.path); search(true); }));
  } else if (m.rec && m.verdict !== "no") {
    if (d?.status === "error") acts.before(el("div", "why no", `Download stopped: ${esc(d.error)}`));
    acts.append(button(`${icon("download")}${d?.status === "error" ? "Try again" : "Download " + gb(m.total)}`,
      "sm " + (m.verdict === "ok" && m.fit !== "no" ? "primary" : ""), async (e) => {
        if (m.fit === "no" && !confirm("Too big for this PC — it may freeze it. Download anyway?")) return;
        if (m.verdict === "maybe" && !confirm(m.reason + "\n\nDownload anyway?")) return;
        e.currentTarget.disabled = true;
        await startDl(m.repo, [...m.rec.paths, ...(withProj ? m.proj.paths : [])], t);
        search(true);
      }));
  }
  if (m.rec && m.verdict !== "no") {
    const files = c.querySelector(".files");
    acts.append(button("Other versions", "sm ghost", async () => {
      if (!files.hidden) { files.hidden = true; return; }
      files.hidden = false; files.innerHTML = `<div class="meta">Loading…</div>`;
      try { showFiles(m, files, await api(`/api/hf/files?repo=${encodeURIComponent(m.repo)}`), t); }
      catch (e) { files.innerHTML = `<div class="notice">${esc(e.message)}</div>`; }
    }));
  }
  return c;
}

function showFiles(m, box, groups, t) {
  box.innerHTML = "";
  const proj = groups.find(g => g.role === "vision" && /f16/i.test(g.name)) || groups.find(g => g.role === "vision");
  const ROLE = { model: "", vision: "vision add-on", helper: "helper file — not a model" };
  for (const g of groups.filter(g => g.role !== "helper" && fits(g.size / 1e9))) {
    const r = el("div", "file", `<span class="n">${esc(g.name)}${g.recommended ? " ★" : ""}${ROLE[g.role] ? ` <span class="muted">(${ROLE[g.role]})</span>` : ""}</span><span>${gb(g.size)}</span> ${badge(g.fit, g.why)}`);
    if (g.present) r.append(el("span", "active-mark", icon("check")));
    else if (g.role === "model") r.append(button(icon("download"), "sm", () => {
      const want = [...g.paths, ...(proj && (t === "text" || t === "vision") ? proj.paths : [])];
      startDl(m.repo, want, t);
    }));
    box.append(r);
  }
  if (!box.children.length) box.append(el("div", "meta", "No versions in this size."));
}

async function startDl(repo, files, modality) {
  try { await api("/api/models/download", json("POST", { repo, files, modality })); }
  catch (e) { return alert(e.message); }
  load();
}

$("hfQuery").addEventListener("input", () => { clearTimeout(searchT); searchT = setTimeout(search, 450); });
$("hfQuery").addEventListener("keydown", (e) => { if (e.key === "Enter") { clearTimeout(searchT); search(); } });

onPage("models", async () => {
  sizeChips(); load();
  try {
    const h = await api("/api/hardware");
    $("hwLine").textContent = `${h.cpu} · ${h.ram_gb} GB RAM · ${h.gpus.join(", ") || "no GPU"} · ${h.free_gb} GB free`;
  } catch {}
});
