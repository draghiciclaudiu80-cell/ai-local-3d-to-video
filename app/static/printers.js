// The printer menu (3D editor + print window): pick your printer, add one from OrcaSlicer's own library (1000+
// machines: K1 Max, Prusa MK4, Bambu A1…), or a custom printer — your plate size on top of another printer's tested
// slicing settings (a printer you built, or a bigger one later). The choice sets the plate, the fit checks, the cutter
// and the slicing everywhere. onChange(info) gets the chosen printer (name, bed, qualities, materials…).
import { api, el, esc, json } from "./core.js";

const btn = (text, cls, fn) => { const b = el("button", "btn sm " + (cls || ""), text); b.onclick = fn; return b; };
const num = (v, ph) => Object.assign(el("input"), { type: "number", min: "30", max: "2000", step: "1", value: v ?? "", placeholder: ph || "" });

export function printerPicker(onChange) {
  const wrap = el("span", "prpick");
  const select = el("select", "prsel");
  wrap.append(select);
  async function fill() {
    let r;
    try { r = await api("/api/printers"); } catch { return; }
    select.innerHTML = r.printers.map(p => `<option value="${esc(p.id)}" ${p.id === r.current ? "selected" : ""}>${esc(p.name)} — ${(p.bed || []).map(Math.round).join("×")} mm${p.kind === "custom" ? " (custom)" : ""}</option>`).join("")
      + `<option value="__custom">➕ Custom printer / plate size…</option><option value="__library">📚 Add a printer from OrcaSlicer's list…</option>`
      + (r.printers.find(p => p.id === r.current && p.kind !== "built-in") ? `<option value="__remove">✕ Remove this printer from the list</option>` : "");
    select.dataset.current = r.current;
  }
  select.onchange = async () => {
    const v = select.value, cur = select.dataset.current;
    if (v === "__custom") { select.value = cur; return customDialog(async info => { await fill(); onChange?.(info); }); }
    if (v === "__library") { select.value = cur; return libraryDialog(async info => { await fill(); onChange?.(info); }); }
    if (v === "__remove") {
      select.value = cur;
      if (!confirm("Remove this printer from the list? (Your models stay.)")) return;
      await api(`/api/printers/${encodeURIComponent(cur)}`, { method: "DELETE" }).catch(() => {});
      await fill();
      onChange?.(await api("/api/printer").catch(() => null));
      return;
    }
    try {
      const info = await api("/api/printers/select", json("POST", { id: v }));
      select.dataset.current = v;
      onChange?.(info);
    } catch (e) { alert(e.message); select.value = cur; }
  };
  fill();
  return wrap;
}

function overlay(title) {
  const ov = el("div", "prov"), box = el("div", "prwin");
  ov.append(box);
  ov.onclick = e => { if (e.target === ov) ov.remove(); };
  const head = el("div", "row", `<b class="grow">${esc(title)}</b>`);
  head.append(btn("✕", "ghost", () => ov.remove()));
  box.append(head);
  document.body.append(ov);
  return { ov, box };
}

function customDialog(done) {
  const { ov, box } = overlay("Custom printer");
  box.append(el("div", "muted small", "Your printer's plate (the size it can really print) — the slicing settings come from the printer you base it on. "
    + "Good for a printer you built, changed, or a bigger one."));
  const name = Object.assign(el("input"), { placeholder: "Name, e.g. My big printer" });
  const w = num(220, "width"), d = num(220, "depth"), h = num(250, "height");
  const base = el("select");
  api("/api/printers").then(r => { base.innerHTML = r.printers.filter(p => p.kind !== "custom").map(p => `<option value="${esc(p.id)}">${esc(p.name)}</option>`).join(""); });
  const nmax = num("", "e.g. 300"), bmax = num("", "e.g. 110");
  const row = (label, ...ctl) => { const r = el("label", "f", esc(label)); ctl.forEach(c => r.append(c)); return r; };
  const sizes = el("div", "row");
  sizes.append(row("Width mm", w), row("Depth mm", d), row("Height mm", h));
  box.append(row("Name", name), sizes, row("Slicing settings from", base));
  const lim = el("div", "row");
  lim.append(row("Max nozzle °C (optional)", nmax), row("Max bed °C (optional)", bmax));
  box.append(lim);
  const out = el("div", "small");
  box.append(el("div", "row", ""), out);
  box.lastChild.previousSibling.append(btn("Save and use it", "primary", async () => {
    try {
      const info = await api("/api/printers/custom", json("POST", {
        name: name.value.trim(), bed: [+w.value, +d.value, +h.value], base: base.value,
        nozzle_max: +nmax.value || null, bed_max: +bmax.value || null }));
      ov.remove();
      done(info);
    } catch (e) { out.innerHTML = `<span class="fitbad">${esc(e.message)}</span>`; }
  }));
}

function libraryDialog(done) {
  const { ov, box } = overlay("Add a printer from OrcaSlicer's list");
  box.append(el("div", "muted small", "OrcaSlicer comes with tested profiles for 1000+ printers. Type the brand / model, pick it — "
    + "the app makes a full offline profile (plate, qualities, materials)."));
  const q = Object.assign(el("input"), { placeholder: "e.g. k1 max, prusa mk4, bambu a1, ender 5" });
  const list = el("div", "prlib");
  box.append(q, list);
  let t = null;
  const search = async () => {
    list.innerHTML = `<div class="muted small">Searching…</div>`;
    try {
      const r = await api(`/api/printers/library?q=${encodeURIComponent(q.value.trim())}`);
      list.innerHTML = r.machines.length ? "" : `<div class="muted small">Nothing found — try fewer words.</div>`;
      r.machines.forEach(n => list.append(btn(esc(n), "ghost prlibrow", async e => {
        e.target.disabled = true;
        e.target.textContent = `Adding ${n}…`;
        try {
          const info = await api("/api/printers/library", json("POST", { name: n }));
          ov.remove();
          done(info);
        } catch (err) { e.target.disabled = false; e.target.textContent = n; alert(err.message); }
      })));
    } catch (e) { list.innerHTML = `<div class="fitbad small">${esc(e.message)}</div>`; }
  };
  q.oninput = () => { clearTimeout(t); t = setTimeout(search, 250); };
  q.focus();
  search();
}
