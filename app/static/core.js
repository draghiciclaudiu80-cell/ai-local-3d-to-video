// Shared helpers for every page.
export const $ = (id) => document.getElementById(id);
export const esc = (s) => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
export const gb = (b) => b >= 1e9 ? (b / 1e9).toFixed(b >= 1e10 ? 0 : 1) + " GB" : Math.max(1, Math.round(b / 1e6)) + " MB";
export const mmss = (s) => `${Math.floor(s / 60)}:${String(Math.round(s % 60)).padStart(2, "0")}`;
export const icon = (name) => `<svg class="i"><use href="#i-${name}"/></svg>`;
export const json = (method, body) => ({ method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

export async function api(url, opt = {}) {
  const r = await fetch(url, opt);
  if (!r.ok) {
    let m = r.statusText;
    try { m = (await r.json()).detail || m; } catch {}
    throw new Error(typeof m === "string" ? m : JSON.stringify(m));
  }
  return (r.headers.get("content-type") || "").includes("json") ? r.json() : r;
}

export const store = {
  get(k, d) { try { return localStorage.getItem(k) ?? d; } catch { return d; } },
  set(k, v) { try { localStorage.setItem(k, v); } catch {} },
};

export function el(tag, cls, html) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (html != null) e.innerHTML = html;
  return e;
}

export function button(text, cls, onClick) {
  const b = el("button", "btn " + (cls || ""), text);
  b.onclick = onClick;
  return b;
}

// Pages register a loader that runs whenever the page is opened.
const loaders = {};
export let current = "chat";
export function onPage(name, fn) { loaders[name] = fn; }
const NAV_OF = { apps: "create", forge: "create" };  // Apps and Forge are tabs of Create (their own pages, Create's tab bar)
export function show(name) {
  current = name;
  store.set("page", name);
  document.querySelectorAll("#nav button, #settingsBtn").forEach(b => b.classList.toggle("on", b.dataset.p === (NAV_OF[name] || name)));
  document.querySelectorAll(".page").forEach(p => p.classList.toggle("on", p.id === "p-" + name));
  loaders[name]?.();
}

export function tabs(barId, key, initial, onChange) {
  let value = store.get(key, initial);
  const bar = $(barId);
  const paint = () => bar.querySelectorAll("button").forEach(b => b.classList.toggle("on", b.dataset.t === value));
  bar.onclick = (e) => {
    const t = e.target.closest("button[data-t]")?.dataset.t;
    if (!t) return;
    value = t; store.set(key, t); paint(); onChange(t);
  };
  paint();
  return () => value;
}

// Speaking goes sentence by sentence: the first words play while the rest is still being made (or still being
// written by the model), and Stop / Esc / talking over her cuts it off at once.
let turnNo = 0, playing = null, pending = [], wake = null, talking = false;
export const speech = new EventTarget();  // "change" (detail: true/false) when her voice starts/stops
const tell = (on) => { if (on !== talking) { talking = on; speech.dispatchEvent(new CustomEvent("change", { detail: on })); } };
export const isSpeaking = () => talking;

function sentenceEnd(text, min) {  // where a piece long enough to speak ends (0 = not yet)
  if ((text.match(/```/g) || []).length % 2) return 0;  // inside a code block: wait for its end
  for (const m of text.matchAll(/[.!?…:;](?=\s)|\n/g)) if (m.index + 1 >= min) return m.index + 1;
  return 0;
}

export function talker(voice) {  // add() text as it arrives, then end(); done = finished or stopped
  stopSpeaking();
  const my = ++turnNo, queue = [], voiced = [];
  let ended = false, buf = "", firstError = null, played = false;
  const make = (text) => { if (text.trim()) { queue.push(text); wake?.(); } };
  const get = (i) => {  // the voice for piece i — asked for only just ahead of time, in order (first words first)
    if (i >= queue.length || voiced[i]) return voiced[i];
    const c = new AbortController();
    pending.push(c);
    return (voiced[i] = api("/api/tts", { ...json("POST", { text: queue[i], voice }), signal: c.signal }).then(r => r.blob())
      .catch(e => { if (e.name !== "AbortError") firstError ??= e; return null; }));
  };
  const done = (async () => {
    try {
      for (let i = 0; my === turnNo; i++) {
        while (i >= queue.length && !ended && my === turnNo) await new Promise(r => { wake = r; });
        if (my !== turnNo || i >= queue.length) break;
        const next = get(i);
        get(i + 1);  // make the next piece while this one plays
        const blob = await next;
        if (my !== turnNo) break;
        if (!blob) continue;
        const audio = new Audio(URL.createObjectURL(blob));
        playing = audio;
        await audio.play();
        played = true;
        tell(true);
        await new Promise(res => { audio.onended = res; audio.onerror = res; audio.onpause = res; });
        URL.revokeObjectURL(audio.src);
      }
    } finally {
      if (my === turnNo) { playing = null; pending = []; tell(false); }
    }
    if (!played && firstError && my === turnNo) throw firstError;
  })();
  return {
    add(text) {
      if (my !== turnNo) return;
      buf += text;
      for (let cut; (cut = sentenceEnd(buf, queue.length ? 140 : 24)); buf = buf.slice(cut)) make(buf.slice(0, cut));
    },
    end() { if (my !== turnNo) return; make(buf); buf = ""; ended = true; wake?.(); },
    done,
  };
}
export function speak(text, voice) {
  const t = talker(voice);
  t.add(text); t.end();
  return t.done;
}
export function stopSpeaking() {
  turnNo++;
  pending.forEach(c => c.abort()); pending = [];
  playing?.pause(); playing = null;
  wake?.();
  tell(false);
}
document.addEventListener("keydown", (e) => { if (e.key === "Escape" && isSpeaking()) stopSpeaking(); });
