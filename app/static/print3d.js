// "Print it" — G-code for the user's own 3D printer, sliced on this PC by OrcaSlicer (offline, the printer's own
// tested settings), then: saved, copied to an SD card, streamed over the USB cable, put on the printer's own SD card
// over USB, or sent to a print server on the LAN. A print only ever STARTS from a click here (never the AI on its own).
import { api, el, esc, json, store } from "./core.js";
import { printerPicker } from "./printers.js";

const fmtMin = s => (s >= 3600 ? `${Math.floor(s / 3600)} h ${Math.round((s % 3600) / 60)} min` : `${Math.max(1, Math.round(s / 60))} min`);
function save(url, name) {  // the browser's own download (the same as the Download buttons)
  const a = Object.assign(document.createElement("a"), { href: url, download: name || "" });
  document.body.append(a); a.click(); a.remove();
}
const sel = (opts, val) => el("select", null, opts.map(([v, t]) => `<option value="${esc(v)}" ${String(v) === String(val ?? "") ? "selected" : ""}>${esc(t)}</option>`).join(""));
const lab = (text, ctl) => { const l = el("label", "f", esc(text)); l.append(ctl); return l; };
const btn = (text, cls, fn) => { const b = el("button", "btn sm " + (cls || ""), text); b.onclick = fn; return b; };

/** The parts of a model that get printed (bought parts left out), with their size. */
function printable(m) {
  if (m.parts) return m.parts.map((p, i) => ({ i, name: p.name, stl: p.stl, size: p.size_mm || [], ref: p.reference })).filter(p => !p.ref && p.stl);
  return m.stl ? [{ i: 0, name: m.name || "model", stl: m.stl, size: m.size_mm || [] }] : [];
}
const fits = (s, bed) => s.length < 3 || (s[2] <= bed[2] && ((s[0] <= bed[0] && s[1] <= bed[1]) || (s[1] <= bed[0] && s[0] <= bed[1])));

// ---------------------------------------------------------------- cut to fit
/** ✂ The model cut into pieces that fit the chosen printer (pin holes in the cuts) — then the print window for them. */
export async function cutAndPrint(m) {
  try {
    const r = await api("/api/model3d/cut", json("POST", { model: m }));
    if (r.fits) { alert("It already fits your printer's plate."); return openPrint(m, {}); }
    window.dispatchEvent(new CustomEvent("model3dcut", { detail: r }));
    openPrint(r.model3d, {});
  } catch (e) { alert(e.message); }
}

// ---------------------------------------------------------------- the print window
let win = null;
function closeWin() { win?.remove(); win = null; }

/** The print window for a model (a chat card, the Gallery, Create › 3D). part = one part of a device only. */
export async function openPrint(m, opts = {}) {
  closeWin();
  win = el("div", "prov");
  const box = el("div", "prwin");
  win.append(box);
  win.onclick = e => { if (e.target === win) closeWin(); };
  document.body.append(win);
  box.innerHTML = `<div class="muted small">Looking for the printer…</div>`;
  let info;
  try { info = await api("/api/printer?ports=1"); } catch (e) { box.innerHTML = `<div class="fitbad">${esc(e.message)}</div>`; return; }
  const parts = printable(m), only = opts.part != null ? new Set([opts.part]) : null;
  box.innerHTML = "";
  const head = el("div", "row", `<b class="grow">🖨 Print</b>`);
  head.append(printerPicker(() => openPrint(m, opts)), btn("✕", "ghost", closeWin));  // another printer: reopen with its settings
  box.append(head, el("div", "muted small", `${info.bed.map(Math.round).join(" × ")} mm plate · ${info.nozzle} mm nozzle · sliced on this PC by OrcaSlicer — no internet, no account`));
  if (!info.slicer) {
    box.append(el("div", "fitbad small", "OrcaSlicer isn't installed on this PC — get it free from orcaslicer.com (then this works offline for good)."));
    return;
  }
  // which parts
  const list = el("div", "prparts");
  const checks = parts.map(p => {
    const ok = fits(p.size, info.bed);
    const c = Object.assign(el("input"), { type: "checkbox", checked: ok && (!only || only.has(p.i)), disabled: !ok });
    const row = el("label", "m3part", "");
    row.append(c, el("span", "grow", `${esc(p.name)} <span class="muted">${p.size.map(Math.round).join(" × ")} mm</span>`
      + (ok ? "" : ` <span class="fitbad">too big for the plate</span>`)));
    list.append(row);
    return c;
  });
  if (parts.length > 1) box.append(el("div", "small", "Parts on the plate (all that fit are printed together):"), list);
  else if (parts[0] && !fits(parts[0].size, info.bed)) box.append(el("div", "fitbad small", `Too big for the plate (${parts[0].size.map(Math.round).join(" × ")} mm).`));
  if (parts.some(p => !fits(p.size, info.bed))) {  // too big: the app cuts it into pieces that fit (with alignment-pin holes)
    const cut = btn("✂ Cut it into pieces that fit this printer", "primary", async () => {
      cut.disabled = true;
      cut.textContent = "Cutting… (Blender, a few seconds)";
      await cutAndPrint(m);
      cut.disabled = false; cut.textContent = "✂ Cut it into pieces that fit this printer";
    });
    box.append(el("div", "row", "")); box.lastChild.append(cut);
  }
  // the choices (remembered)
  const material = sel(info.materials.map(x => [x, x]), store.get("print.material", info.default_material));
  const quality = sel(info.qualities.map(x => [x, x]), store.get("print.quality", info.default_quality));
  const infill = Object.assign(el("input"), { type: "number", min: "0", max: "100", step: "5", value: store.get("print.infill", "15") });
  const supports = sel([["off", "none"], ["auto", "where needed"], ["tree", "tree (easy to remove)"]], store.get("print.supports", "off"));
  const brim = Object.assign(el("input"), { type: "checkbox", checked: store.get("print.brim", "0") === "1" });
  const brimL = el("label", "row small", ""); brimL.append(brim, document.createTextNode(" brim (sticks better)"));
  const row1 = el("div", "row"), row2 = el("div", "row");
  row1.append(lab("Material", material), lab("Quality", quality));
  row2.append(lab("Infill %", infill), lab("Supports", supports), brimL);
  box.append(row1, row2);
  const go = btn("Make G-code", "primary", () => make());
  const out = el("div", "prout");
  box.append(el("div", "row", ""), out);
  box.lastChild.previousSibling.append(go);
  async function make() {
    const stls = parts.filter((p, i) => checks[i].checked).map(p => p.stl);
    if (!stls.length) return (out.innerHTML = `<div class="fitbad small">Pick at least one part that fits.</div>`);
    const options = { material: material.value, quality: quality.value, infill: +infill.value || 0, supports: supports.value, brim: brim.checked };
    store.set("print.material", options.material); store.set("print.quality", options.quality);
    store.set("print.infill", String(options.infill)); store.set("print.supports", options.supports); store.set("print.brim", brim.checked ? "1" : "0");
    go.disabled = true;
    out.innerHTML = "";
    const rid = Math.random().toString(36).slice(2, 12), bar = progress(rid);
    out.append(bar.el);
    try {
      const r = await api("/api/slice", json("POST", { stls, options, run: rid, name: m.name || "model" }));
      bar.stop();
      if (r.stopped) { out.innerHTML = `<div class="muted small">Stopped.</div>`; return; }
      out.innerHTML = "";
      out.append(resultBox(r, info));
    } catch (e) { bar.stop(); out.innerHTML = `<div class="fitbad small">${esc(e.message)}</div>`; }
    finally { go.disabled = false; }
  }
  if (info.job?.state && !["idle", "done", "error", "cancelled"].includes(info.job.state)) out.append(jobBox());
}

function progress(rid) {  // the slicing bar (+ Stop)
  const e = el("div", "prog3d", `<div class="row small"><span class="t grow">Slicing…</span></div><div class="bar"><i style="width:2%"></i></div>`);
  const stop = btn("Stop", "danger", () => api(`/api/plugin-runs/${rid}/stop`, { method: "POST" }).catch(() => {}));
  e.firstChild.append(stop);
  const t = setInterval(async () => {
    try {
      const s = await api(`/api/plugin-runs/${rid}`);
      if (s.text) e.querySelector(".t").textContent = `${s.text} ${s.elapsed ? s.elapsed + " s" : ""}`;
      if (s.pct != null) e.querySelector("i").style.width = Math.round(s.pct * 100) + "%";
    } catch {}
  }, 700);
  return { el: e, stop: () => clearInterval(t) };
}

/** What the slicer made: time, filament, the files, and the ways to send it. */
export function resultBox(r, info) {
  const b = el("div", "prres");
  const time = r.seconds ? fmtMin(r.seconds) : r.time || "?";
  b.append(el("div", "prstats", `⏱ <b>${esc(time)}</b> · ${r.grams != null ? `<b>${r.grams} g</b>` : ""} ${esc(r.settings || "")}`
    + `${r.meters ? ` (${r.meters} m)` : ""}${r.layers ? ` · ${r.layers} layers` : ""}${r.plates > 1 ? ` · ${r.plates} plates` : ""}`));
  for (const n of r.notes || []) b.append(el("div", "small fitbad", "⚠ " + esc(n)));
  const files = el("div", "row");
  for (const f of r.files || [{ gcode: r.gcode, name: r.gcode_name }]) files.append(btn(`💾 Save G-code${r.files?.length > 1 ? " " + (r.files.indexOf(f) + 1) : ""}`, "primary", () => save(f.gcode, f.name)));
  if (r.threemf) files.append(btn("💾 Save 3MF (Creality Print / Orca)", "", () => save(r.threemf, r.threemf_name)));
  b.append(files, sendBox(r, info));
  return b;
}

// ---------------------------------------------------------------- sending it to the printer
function sendBox(r, info0) {
  const box = el("div", "prsend");
  const name = r.gcode_name || "print.gcode";
  const status = el("div", "small");
  let info = info0;
  async function paint(refresh) {
    if (refresh || !info?.ports) {
      try { info = await api("/api/printer?ports=1"); } catch (e) { status.textContent = e.message; return; }
    }
    box.innerHTML = "";
    // 1. SD card in this PC
    const card = el("div", "prway");
    card.append(el("b", "small", "SD card (in this PC)"));
    if (info.drives?.length) {
      const d = sel(info.drives.map(x => [x.path, `${x.name} · ${x.free_gb} GB free`]), info.drives[0].path);
      card.append(d, btn("Copy to card", "", async () => {
        status.textContent = "Copying…";
        try {
          const s = await api("/api/printer/send", json("POST", { mode: "card", gcode: r.gcode, drive: d.value, name }));
          status.innerHTML = `✓ Copied as <b>${esc(s.name)}</b>. `;
          status.append(btn("Eject the card", "", async () => {
            const e = await api("/api/printer/eject", json("POST", { drive: d.value }));
            status.textContent = e.ejected ? "✓ Ejected — put the card in the printer and choose the file on its screen." : "Eject it from the taskbar before pulling it out.";
          }));
        } catch (e) { status.textContent = e.message; }
      }));
    } else card.append(el("span", "muted small", "Put the printer's microSD card in this PC's card reader, then ↻."));
    // 2. USB cable
    const usb = el("div", "prway");
    usb.append(el("b", "small", "USB cable"));
    if (info.ports?.length) {
      const p = sel(info.ports.map(x => [x.port, x.name]), info.link?.port || info.ports[0].port);
      usb.append(p, btn("▶ Print over USB", "primary", () => send("usb", p.value)),
        btn("⇪ Onto the printer's SD card", "", () => send("usb_sd", p.value)));
    } else usb.append(el("span", "muted small", "Plug the printer's USB cable into this PC and turn the printer on, then ↻."));
    // 3. a print server on the LAN (only when there is one)
    const net = el("div", "prway");
    const link = info.link || {};
    if ((link.kind === "octoprint" || link.kind === "moonraker") && link.url) {
      net.append(el("b", "small", `Network (${link.kind === "moonraker" ? "Klipper" : "OctoPrint"})`),
        btn("Send + print", "", async () => {
          if (!confirm(`Send “${name}” to ${link.url} and start printing?`)) return;
          status.textContent = "Sending…";
          try { const s = await api("/api/printer/send", json("POST", { mode: "network", gcode: r.gcode, name })); status.textContent = `✓ Sent to ${s.server} — it's printing.`; }
          catch (e) { status.textContent = e.message; }
        }));
    }
    const setup = el("details", "small", `<summary>Print server on the network (OctoPrint / Klipper)…</summary>`);
    const kind = sel([["octoprint", "OctoPrint"], ["moonraker", "Klipper (Moonraker)"]], link.kind === "moonraker" ? "moonraker" : "octoprint");
    const url = Object.assign(el("input"), { placeholder: "http://192.168.1.50", value: link.url || "" });
    const key = Object.assign(el("input"), { placeholder: "API key (OctoPrint)", value: link.key || "" });
    setup.append(el("div", "muted small", "The Ender-3 V3 SE has no Wi-Fi itself — this is for a Raspberry Pi with OctoPrint / Klipper next to it."),
      kind, url, key, btn("Save", "", async () => {
        await api("/api/printer/link", json("POST", { kind: kind.value, url: url.value.trim(), key: key.value.trim() }));
        paint(true);
      }));
    net.append(setup);
    box.append(card, usb, net, el("div", "row", ""), status);
    box.lastChild.previousSibling.append(btn("↻ Look again", "ghost", () => paint(true)));
  }
  async function send(mode, port) {
    const how = mode === "usb" ? "print it over the USB cable — the PC must stay on until it's done"
      : "copy it onto the printer's own SD card over USB, then start it (the printer prints by itself)";
    if (!confirm(`Start printing “${name}” on the ${info.name}?\n\nThis will ${how}.\nCheck that the plate is empty and clean.`)) return;
    try {
      await api("/api/printer/send", json("POST", { mode, port, gcode: r.gcode, name }));
      box.querySelector(".prjob")?.remove();
      box.append(jobBox());
    } catch (e) { status.textContent = e.message; }
  }
  paint(false);
  return box;
}

/** The print going on: state, progress, temperatures, Pause / Resume / Stop. */
export function jobBox() {
  const b = el("div", "prjob");
  const line = el("div", "small"), bar = el("div", "bar", "<i></i>"), acts = el("div", "row");
  b.append(line, bar, acts);
  const act = a => api(`/api/printer/job/${a}`, { method: "POST" }).catch(e => alert(e.message));
  const tick = async () => {
    if (!b.isConnected) return clearInterval(t);
    let s;
    try { s = await api("/api/printer/job"); } catch { return; }
    const temps = s.temps || {}, tt = [temps.nozzle && `nozzle ${Math.round(temps.nozzle[0])}/${Math.round(temps.nozzle[1])} °C`,
      temps.bed && `bed ${Math.round(temps.bed[0])}/${Math.round(temps.bed[1])} °C`].filter(Boolean).join(" · ");
    line.innerHTML = `<b>${esc({ connecting: "Connecting", heating: "Heating up", printing: "Printing", uploading: "Copying to the printer's card",
      paused: "Paused", done: "Done", error: "Stopped by an error", cancelled: "Stopped", idle: "Nothing printing" }[s.state] || s.state)}</b>`
      + ` ${s.pct != null && s.total ? `${s.pct}%` : ""} ${tt ? "· " + esc(tt) : ""}${s.printer ? ` · ${esc(s.printer)}` : ""}<br><span class="muted">${esc(s.message || "")}</span>`;
    bar.firstChild.style.width = (s.pct || 0) + "%";
    acts.innerHTML = "";
    if (["printing", "heating"].includes(s.state) && s.mode === "usb") acts.append(btn("⏸ Pause", "", () => act("pause")));
    if (s.state === "paused") acts.append(btn("▶ Resume", "", () => act("resume")));
    if (["connecting", "heating", "printing", "uploading", "paused"].includes(s.state))
      acts.append(btn("■ Stop the print", "danger", () => { if (confirm("Stop the print? (heaters off, nozzle lifted)")) act("cancel"); }));
    if (["done", "error", "cancelled", "idle"].includes(s.state)) clearInterval(t);
  };
  const t = setInterval(tick, 1500);
  tick();
  return b;
}

// ---------------------------------------------------------------- a normal (paper) printer
/** Prints a picture (kind image, url /media/…) or a text on a paper printer: pick the printer, copies, Print. */
export async function openPaper(job) {
  closeWin();
  win = el("div", "prov");
  const box = el("div", "prwin");
  win.append(box);
  win.onclick = e => { if (e.target === win) closeWin(); };
  document.body.append(win);
  const head = el("div", "row", `<b class="grow">🖨 Print ${job.kind === "image" ? "the picture" : "the text"} on paper</b>`);
  head.append(btn("✕", "ghost", closeWin));
  box.append(head);
  if (job.kind === "image") box.append(Object.assign(el("img", "prthumb"), { src: job.url, alt: "" }));
  else box.append(el("div", "prtext muted small", esc(String(job.text || "").slice(0, 400)) + (String(job.text || "").length > 400 ? "…" : "")));
  const out = el("div", "small");
  let list = [];
  try { list = (await api("/api/paper/printers")).printers || []; } catch (e) { out.textContent = e.message; }
  if (!list.length) { box.append(el("div", "fitbad small", "No printer is set up on this PC (Windows Settings › Printers, or CUPS on Linux).")); return; }
  const p = sel(list.map(x => [x.name, x.name + (x.default ? " (default)" : "")]), store.get("paper.printer", (list.find(x => x.default) || list[0]).name));
  const copies = Object.assign(el("input"), { type: "number", min: "1", max: "99", value: "1" });
  const row = el("div", "row");
  row.append(lab("Printer", p), lab("Copies", copies));
  const go = btn("🖨 Print", "primary", async () => {
    go.disabled = true;
    store.set("paper.printer", p.value);
    out.textContent = "Printing…";
    try {
      const r = await api("/api/paper/print", json("POST", { ...job, printer: p.value, copies: +copies.value || 1 }));
      out.innerHTML = "";
      if (r.pdf) { out.append(document.createTextNode("✓ Made a PDF. ")); out.append(btn("💾 Save the PDF", "primary", () => save(r.pdf, (job.name || "print") + ".pdf"))); }
      else out.textContent = `✓ Sent to ${r.printed}${r.copies > 1 ? ` (${r.copies} copies)` : ""}.`;
    } catch (e) { out.textContent = e.message; }
    finally { go.disabled = false; }
  });
  row.append(go);
  box.append(row, out);
}

/** In a chat answer: "print this picture / text" — a button that opens the paper print window. */
export function paperCard(job) {
  const c = el("div", "prcard");
  c.append(el("div", "small", `🖨 ${job.kind === "image" ? "Print this picture" : "Print this text"} on paper`));
  if (job.kind === "image") c.append(Object.assign(el("img", "prthumb"), { src: job.url, alt: "" }));
  c.append(btn("🖨 Choose the printer and print", "primary", () => openPaper(job)));
  return c;
}

/** In a chat answer: what Cortana sliced ("print it"), with the same Save / send buttons. */
export function printCard(r) {
  const c = el("div", "prcard");
  c.append(el("div", "small", `🖨 <b>${esc(r.printer || "3D printer")}</b>`), resultBox(r, null));
  return c;
}
