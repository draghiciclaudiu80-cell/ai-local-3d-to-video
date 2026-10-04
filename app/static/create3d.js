// Create › 3D: describe a part or a device -> the chosen AI designs it (or start from a working design) -> change it
// by hand -> Build (PicoGK or FreeCAD: each part its own STL, fit check between the parts).
// By hand, in the 3D view (mouse first; touch / pen work too): click a part or a hole to select it, drag its arrows
// (or the part itself) to move it, its square handles to stretch it, its rings to turn it; copy / paste / delete / undo;
// right-click = a menu (copy, paste, delete, turn 90°, mirror, save STL / STEP); the Hole, Dent and Thread tools work on any
// surface you click — press and drag to draw the circle, then pick a size or type / say it. "Edit in 3D" from a chat
// opens this same editor OVER the chat (moved into an overlay), and "Send to chat" puts the result back there.
import { $, api, button, el, esc, json, show } from "./core.js";
import { FITS, SCREWS, across, blueprint, closeMenu, download, exploder, fitsBed, holeInfo, isoPitch, makeViewer, parseStl, plateMeshes, popMenu, roundPitch, v3, viewAssembly } from "./viewer3d.js";
import { currentChat, openChat, progress3dBox, toWav } from "./chat.js";
import { openPrint } from "./print3d.js";
import { printerPicker } from "./printers.js";
import { convert, dentPart, fmt, handlesFor, lineParam, mirrored, moved, parseSay, partBox, rayPlane, screwFor, turned } from "./edit3d.js";

const FIELDS = {  // PicoGK's shapes
  sphere: ["radius"], box: ["size", "round"], cylinder: ["radius", "height"], cone: ["radius", "radius2", "height"],
  tube: ["radius", "wall", "height"], torus: ["radius", "radius2"], extrude: ["points", "height"], revolve: ["points"],
  gear: ["teeth", "module", "height", "bore"], helix: ["radius", "radius2", "height", "turns"], rod: ["from", "to", "radius"],
  lattice: ["size", "cell", "beam", "type"], gyroid: ["size", "cell", "wall"],
  // from LEAP 71's libraries
  curved_pipe: ["points3", "radius", "wall"], tpms: ["size", "cell", "wall", "type"],
  quasicrystal: ["radius", "generations", "beam", "tile"], rover_wheel: ["preset", "seed"], heat_exchanger: [],
};
const FC_FIELDS = {  // FreeCAD's shapes (each sits on its center)
  box: ["size", "round"], cylinder: ["radius", "height", "axis"], cone: ["radius", "radius2", "height", "axis"],
  tube: ["radius", "wall", "height", "axis"], sphere: ["radius"], slot: ["length", "width", "height", "axis", "direction"],
  polygon: ["points", "height"],
};
const TYPES = { lattice: ["cubic", "body_centre", "octahedron", "random"], tpms: ["diamond", "primitive", "lidinoid"] };
const IN_DESIGN_COORDS = new Set(["rod", "curved_pipe"]);  // given by points in the design itself (no center / turn)
const LABEL = { center: "Center x · y · z", rotate: "Turn x · y · z (°)", size: "Size x · y · z", radius: "Radius", height: "Height",
  wall: "Wall", cell: "Cell", beam: "Beam radius", round: "Rounded edges", teeth: "Teeth", module: "Module (tooth size)",
  bore: "Hole radius", turns: "Turns", from: "From x · y · z", to: "To x · y · z", points: "Outline points (x,y per line)",
  radius2: { cone: "Top radius", torus: "Thickness", helix: "Wire radius" }, points3: "Path points (x,y,z per line)",
  type: "Type", generations: "Generations (1-2)", tile: "Tile (1-4)", preset: "Preset (1-4, 0 = random)", seed: "Random seed",
  axis: "Along", direction: "Long side along", length: "Length", width: "Width" };
const DEFAULTS = { center: [0, 0, 0], rotate: [0, 0, 0], size: [30, 30, 30], radius: 10, radius2: 4, height: 30, wall: 2, cell: 10,
  beam: 1, round: 0, teeth: 20, module: 1.5, bore: 1.6, turns: 6, from: [0, 0, 0], to: [0, 0, 40],
  points: [[0, 0], [30, 0], [30, 10], [0, 20]], points3: [[0, 0, 0], [40, 0, 0], [60, 20, 30]], type: "",
  generations: 1, tile: 4, preset: 2, seed: 0, axis: "z", direction: "x", length: 30, width: 8 };
const VEC = new Set(["center", "rotate", "size", "from", "to"]);
const PG_TPL = [["dart_blaster", "Dart blaster (Nerf-style pistol)"], ["centrifugal_pump", "Water pump (DC motor)"], ["gear_pair", "Gear pair"],
  ["box_with_lid", "Box with lid"], ["handcuffs", "Handcuffs (hinged + chain)"], ["revolver_blaster", "Revolver blaster (6-shot)"],
  ["robot_arm", "Robot arm (4 servos, 300 mm)"], ["robot_hand", "Robotic hand (tendons)"],
  ["fidget_spinner", "Fidget spinner (608 bearings)"]];
const FC_TPL = [["motor_mount", "Motor mount (NEMA 17 stepper)"], ["l_bracket", "L bracket"], ["enclosure", "Electronics box (Raspberry Pi / Arduino)"],
  ["mounting_plate", "Mounting plate"], ["flange", "Flange (shaft hub)"], ["spacer", "Spacer / standoff"], ["pipe_clamp", "Pipe clamp"],
  ["fit_test", "Fit test — find your printer's clearance (15 min print)"]];
const START = engine => (engine === "freecad"
  ? { name: "part", engine: "freecad", bodies: [{ name: "part", parts: [{ op: "add", shape: "box", center: [0, 0, 10], size: [40, 30, 20] }], holes: [] }] }
  : { name: "part", bodies: [{ name: "part", parts: [{ op: "add", shape: "box", center: [0, 0, 15], size: [30, 30, 30] }] }] });
const TOOLS = {
  select: "Click a shape to select it (double-click: the whole part) · drag its arrows — or it — to move · right-click = menu · right-drag moves the view",
  stretch: "Click a part, then drag its square handles to make it longer / bigger — the other side stays put · Shift = 0.1 mm steps",
  rotate: "Click a part, then drag one of its 3 rings to turn it — 15° steps, Shift = 1° · right-click → Turn 90°",
  hole: "Click a surface for a hole — or press and drag to draw its circle. Then pick M3, M4… or type / say it (“M3 countersunk”, “2 cm”)",
  dent: "Click a surface — or draw a circle — for a dent: round, square or a finger dimple",
  thread: "Click a cylinder to thread its outside — or a hole to thread it inside",
};

let recipe = START("picogk"), cur = 0, viewer = null, built = null, mode = "blue", fresh = true;
let ex = null, exploded = false;  // Explode / Assemble (next to Blueprint / Built)
let sel = null;                   // the selected part / hole: {kind: "part" | "hole", body, index}
let more = [];                    // Ctrl+click: more selected items (sel = the last clicked one: its arrows, its numbers)
let ctrlHeld = false;             // Ctrl / Cmd is held (the press handler gets no event)
addEventListener("keydown", e => { if (e.key === "Control" || e.key === "Meta") ctrlHeld = true; });
addEventListener("keyup", e => { if (e.key === "Control" || e.key === "Meta") ctrlHeld = false; });
addEventListener("blur", () => { ctrlHeld = false; });
let tool = "select", snapStep = 1;
let hist = [], fut = [];          // undo / redo: the design as JSON
let clip = null;                  // a copied part / hole
let drag = null, drawing = null, marker = null, hoverG = null, label = null, pop = null;
let meshes = [];                  // the blueprint now shown
let origin = null;                // the chat "Edit in 3D" came from ("Send to chat")
let lastHole = { for: "M3", fit: "clearance", depth: 0 }, lastDent = { shape: "round", width: 10, depth: 2 };
const fcMode = () => recipe.engine === "freecad";
function exButton() {
  $("d3Explode").hidden = !ex || ex.groups < 2;
  $("d3Explode").textContent = exploded ? "Assemble" : "Explode";
}

function normalize(r) {  // always a list of bodies inside the editor
  r = structuredClone(r || START("picogk"));
  if (!r.bodies?.length) r.bodies = [{ name: r.name || "part", parts: r.parts || [], holes: r.holes, hollow: r.hollow, smooth: r.smooth }];
  delete r.parts; delete r.holes; delete r.hollow; delete r.smooth;
  for (const b of r.bodies) if (!Array.isArray(b.parts) || !b.parts.length) b.parts = START(r.engine).bodies[0].parts;
  return r;
}
const body = () => recipe.bodies[cur];
const num = (v, d) => (v !== "" && Number.isFinite(+v) ? +v : d);
const same = (a, b) => !!a && !!b && a.kind === b.kind && a.body === b.body && a.index === b.index;
const itemOf = s => { const b = s && recipe.bodies[s.body]; return !b ? null : s.kind === "body" ? b : (s.kind === "hole" ? b.holes : b.parts)?.[s.index] || null; };
const setItem = (s, v) => { if (s.kind === "body") { recipe.bodies[s.body] = v; return; } const b = recipe.bodies[s.body]; (s.kind === "hole" ? b.holes : b.parts)[s.index] = v; };
const selAll = () => (sel ? [sel, ...more] : []).filter(x => itemOf(x));
const inSel = ref => !!ref && selAll().some(x => same(ref, x) || (x.kind === "body" && ref.body === x.body));  // a whole part: all its shapes
const hint = t => { $("d3Hint").textContent = t; };

function draw(recenter) {
  if (mode === "built" && built) return;
  if (!viewer) {
    $("d3Canvas").querySelectorAll("canvas, .muted").forEach(c => c.remove());
    viewer = makeViewer($("d3Canvas"));
    viewer.setTool(editTool);
    viewer.setOverlay(overlay);
  }
  meshes = blueprint(recipe, recipe.bodies.length > 1 ? cur : -1, sel);
  ex = exploder(meshes, viewer, m => m.body);  // (the plate below isn't part of the device: it never moves)
  let shown = meshes;
  if (printerBed) {  // the printer's plate under it, at its real size
    const solid = meshes.filter(m => m.ref?.kind === "part" && !m.cut), { lo, hi } = boxOf(solid);
    if (lo[0] < Infinity) {
      const bed = printerBed.bed, many = recipe.bodies.length > 1;
      const big = recipe.bodies.map((b, i) => { const bb = boxOf(solid.filter(m => m.body === i)); return [b.name || `part ${i + 1}`, bb]; })
        .filter(([, bb]) => bb.lo[0] < Infinity && !fitsBed([0, 1, 2].map(k => bb.hi[k] - bb.lo[k]), bed))
        .map(([n, bb]) => `${n} ${[0, 1, 2].map(k => Math.round(bb.hi[k] - bb.lo[k])).join(" × ")} mm`);
      const pl = plateMeshes(lo, hi, bed, many ? !big.length : null);
      shown = [...meshes, ...pl.meshes];
      $("d3Fit").textContent = pl.fits
        ? (many ? `✓ Every part fits your ${printerBed.name} (${bed.join(" × ")} mm) — the slicer lays them out; the grid is 20 mm`
          : `✓ Fits your ${printerBed.name} (${bed.join(" × ")} mm) — the grid is 20 mm`)
        : `⚠ Too big for your ${printerBed.name} (${bed.map(Math.round).join(" × ")} mm): ${many ? big.join("; ") : pl.size.map(Math.round).join(" × ") + " mm"} — make it smaller, or press ✂ Cut to fit`;
      $("d3Fit").className = "small " + (pl.fits ? "fitok" : "fitbad");
      if ($("d3CutFit")) $("d3CutFit").hidden = pl.fits;
    }
  }
  viewer.show(shown, !recenter);
  if (exploded) ex.set(0.8);
  exButton();
}
let printerBed = null;  // {name, bed}: the user's 3D printer (its plate is drawn under the design)
api("/api/printer").then(r => { printerBed = { name: r.name.replace("Creality ", ""), bed: r.bed }; if (viewer && mode === "blue") draw(false); }).catch(() => {});
// the printer menu: another printer / a custom plate changes the plate drawn here, the fit line and the cutter
$("d3Printer")?.append(printerPicker(info => {
  if (!info) return;
  printerBed = { name: String(info.name || "printer").replace("Creality ", ""), bed: info.bed };
  if (viewer && mode === "blue") draw(false);
}));
function setMode(m) {
  mode = m;
  $("d3Mode").querySelectorAll("button").forEach(b => b.classList.toggle("on", b.dataset.t === m));
  $("d3Panel").innerHTML = "";
  closePop();
  if (m === "built" && built) {
    viewer = null; $("d3Canvas").innerHTML = "";
    ex = null; exButton();
    if (built.parts) viewAssembly(built, $("d3Canvas"), $("d3Panel"), esc).then(r => {
      r.v.setTool({ menu: (p, e) => editMenu(p, e) });
      ex = r.ex;
      if (exploded) ex.set(0.8);
      const s = $("d3Panel").querySelector("input[type=range]");
      if (s) { s.value = ex.k; s.addEventListener("input", () => { exploded = ex.k > 0.05; exButton(); }); }
      $("d3Panel").querySelector(".exbtn")?.remove();  // the one next to Blueprint / Built does it here
      exButton();
    });
    else {
      viewer = makeViewer($("d3Canvas"));
      viewer.setTool({ menu: (p, e) => editMenu(p, e) });
      fetch(built.view || built.stl).then(r => r.arrayBuffer()).then(b => viewer.show([parseStl(b)]));
    }
    hint("The real, built model. Blueprint = change it (the tools work there).");
  } else { viewer = null; $("d3Canvas").innerHTML = ""; draw(true); status(); }
}

// ---------------------------------------------------------------- undo / redo, selection, status line
function snap() {  // remember the design before a change (one undo step)
  const s = JSON.stringify(recipe);
  if (hist[hist.length - 1] !== s) { hist.push(s); if (hist.length > 150) hist.shift(); }
  fut = [];
  paintUndo();
}
function undo() {
  const now = JSON.stringify(recipe);
  while (hist.length && hist[hist.length - 1] === now) hist.pop();
  if (!hist.length) return hint("Nothing to undo.");
  fut.push(now);
  recipe = JSON.parse(hist.pop());
  afterHistory();
}
function redo() {
  if (!fut.length) return hint("Nothing to redo.");
  hist.push(JSON.stringify(recipe));
  recipe = JSON.parse(fut.pop());
  afterHistory();
}
function afterHistory() {
  if (sel && !itemOf(sel)) sel = null;
  cur = Math.min(cur, recipe.bodies.length - 1);
  closePop(); paintParts(); changed(); status();
}
function paintUndo() { $("d3Undo").disabled = !hist.length; $("d3Redo").disabled = !fut.length; }

function select(s, quiet) {
  more = [];
  sel = s && itemOf(s) ? { kind: s.kind, body: s.body, index: s.index } : null;
  if (sel && sel.body !== cur) cur = sel.body;
  if (!quiet) closePop();
  paintParts(); draw(false); status();
  if (sel?.kind === "hole" && !quiet) openHolePop({ ref: sel });
}
/** Ctrl+click (like files in Windows): add one more to the selection — or take it out again. */
function toggleSel(ref) {
  const r = { kind: ref.kind, body: ref.body, index: ref.index };
  const i = selAll().findIndex(x => same(x, r));
  if (i >= 0) {  // already in: out it goes (the next one takes the arrows)
    const rest = selAll().filter((x, j) => j !== i);
    sel = rest[0] || null; more = rest.slice(1);
  } else if (!selAll().some(x => x.kind === "body" && x.body === r.body)) {  // (a shape of a part that's selected whole: in already)
    const keep = r.kind === "body" ? selAll().filter(x => x.body !== r.body) : selAll();  // a whole part replaces its shapes
    more = keep; sel = r;
  }
  if (sel) cur = sel.body;
  closePop(); paintParts(); draw(false); status();
}
function status() {
  const it = itemOf(sel);
  if (!it) return hint(TOOLS[tool]);
  if (more.length) return hint(`${selAll().length} selected — drag an arrow (or one of them) to move them all · arrow keys nudge · Ctrl+C / Ctrl+V copies · Del deletes · right-click → Turn / Mirror · Ctrl+click adds or takes one out · Esc lets go`);
  if (sel.kind === "body") return hint(`The whole part “${it.name || "part"}” (${it.parts.length} shape${it.parts.length > 1 ? "s" : ""}${it.holes?.length ? `, ${it.holes.length} hole${it.holes.length > 1 ? "s" : ""}` : ""}) — drag an arrow (or it) to move all of it · Ctrl+C / Ctrl+V copies it · Del removes it · click one shape to pick just that`);
  const what = sel.kind === "hole" ? `Hole: ${holeInfo(it).label}` : `Part ${sel.index + 1}: ${sel.index && it.op && it.op !== "add" ? it.op + " " : ""}${it.shape}${it.thread ? " (threaded)" : ""}`;
  hint(`${what} — ` + (tool === "rotate" ? "drag a ring to turn it (15° steps, Shift = 1°) · right-click → Turn 90°"
    : tool === "stretch" && sel.kind === "part" ? (handlesFor(it, fcMode()).length ? "drag a square handle to stretch it" : "this shape can only be moved (its numbers are on the left)")
    : "drag an arrow (or the part) to move it · arrow keys nudge · Ctrl+C / Ctrl+V copies · Del deletes · Esc lets go"));
}

// ---------------------------------------------------------------- the form (left): bodies, parts, holes
function paintTemplates() {
  const list = fcMode() ? FC_TPL : PG_TPL;
  if ($("d3Tpl").dataset.engine === (fcMode() ? "fc" : "pg")) return;
  $("d3Tpl").dataset.engine = fcMode() ? "fc" : "pg";
  $("d3Tpl").innerHTML = `<option value="">—</option>` + list.map(([v, t]) => `<option value="${v}">${esc(t)}</option>`).join("");
}
function paintBodies() {
  const fc = fcMode();
  $("d3Body").innerHTML = recipe.bodies.map((b, i) => `<option value="${i}" ${i === cur ? "selected" : ""}>${i + 1}. ${esc(b.name || "part")}${b.reference ? " (bought)" : ""}</option>`).join("");
  $("d3DelBody").disabled = recipe.bodies.length < 2;
  $("d3Ref").checked = !!body().reference;
  $("d3Name").value = body().name || "part";
  $("d3Engine").value = fc ? "freecad" : "picogk";
  $("d3HollowL").firstChild.textContent = fc ? "Hollow, open top (wall mm)" : "Hollow (wall, mm)";
  $("d3SmoothL").firstChild.textContent = fc ? "Round edges (mm)" : "Smooth (mm)";
  $("d3ChamferL").hidden = !fc;
  $("d3Hollow").value = (fc ? body().shell : body().hollow) || 0;
  $("d3Smooth").value = (fc ? body().fillet : body().smooth) || 0;
  $("d3Chamfer").value = body().chamfer || 0;
  $("d3PartsHint").textContent = `Parts, in order — add joins, ${fc ? "cut" : "subtract"} cuts away, intersect keeps only the overlap. Millimetres, Z is up.`
    + (fc ? " FreeCAD: every shape sits on its center." : "");
  $("d3Build").lastChild.textContent = fc ? "Build with FreeCAD" : "Build with PicoGK";
  paintTemplates();
}

function field(p, k) {
  const lab = typeof LABEL[k] === "object" ? LABEL[k][p.shape] || "Radius 2" : LABEL[k];
  const f = el("label", "f small", esc(p.shape === "quasicrystal" && k === "radius" ? "Face side" : lab));
  if (k === "type" || k === "axis" || k === "direction") {
    const opts = k === "type" ? TYPES[p.shape] || [] : ["x", "y", "z"].filter(a => k !== "direction" || a !== (p.axis || "z"));
    if (k === "type" && !p.type) p.type = opts[0];
    const val = p[k] || (k === "direction" ? opts[0] : DEFAULTS[k]);
    const s = el("select", null, opts.map(t => `<option ${t === val ? "selected" : ""}>${t}</option>`).join(""));
    s.onfocus = snap;
    s.onchange = () => { p[k] = s.value; if (k === "axis") paintParts(); changed(); };
    f.append(s);
  } else if (k === "points3" || k === "points") {
    const n = k === "points3" ? 3 : 2, t = el("textarea");
    t.rows = 3;
    t.value = (p.points || DEFAULTS[k]).map(q => q.join(", ")).join("\n");
    t.onfocus = snap;
    t.oninput = () => {
      const pts = t.value.split("\n").map(l => l.split(/[,; ]+/).filter(Boolean).map(Number)).filter(q => q.length >= n && q.every(Number.isFinite)).map(q => q.slice(0, n));
      if (pts.length >= (n === 3 ? 2 : 3)) { p.points = pts; changed(); }
    };
    f.append(t);
  } else if (VEC.has(k)) {
    const trio = el("div", "trio");
    for (let a = 0; a < 3; a++) {
      const inp = Object.assign(el("input"), { type: "number", step: "1", value: (p[k] || DEFAULTS[k])[a] });
      inp.onfocus = snap;
      inp.oninput = () => { p[k] = [...(p[k] || DEFAULTS[k])]; p[k][a] = num(inp.value, 0); changed(); };
      trio.append(inp);
    }
    f.append(trio);
  } else {
    const inp = Object.assign(el("input"), { type: "number", step: k === "teeth" ? "1" : "0.5", value: p[k] ?? DEFAULTS[k] });
    inp.onfocus = snap;
    inp.oninput = () => { p[k] = num(inp.value, DEFAULTS[k]); changed(); };
    f.append(inp);
  }
  return f;
}

function paintParts() {
  paintBodies();
  const fc = fcMode(), F = fc ? FC_FIELDS : FIELDS, box = $("d3Parts");
  box.innerHTML = "";
  body().parts.forEach((p, i) => {
    const on = (sel?.kind === "part" && sel.body === cur && sel.index === i) || (sel?.kind === "body" && sel.body === cur);
    const row = el("div", "d3part" + (on ? " on" : ""));
    const ops = fc ? ["add", "cut", "intersect"] : ["add", "subtract", "intersect"];
    const op = el("select", null, (i ? ops : ["add"]).map(o => `<option ${o === (p.op || "add") ? "selected" : ""}>${o}</option>`).join(""));
    const shape = el("select", null, Object.keys(F).map(s => `<option ${s === p.shape ? "selected" : ""}>${s}</option>`).join(""));
    if (!F[p.shape]) shape.insertAdjacentHTML("afterbegin", `<option selected>${esc(p.shape)}</option>`);
    op.onfocus = shape.onfocus = snap;
    op.onchange = () => { p.op = op.value; changed(); };
    shape.onchange = () => {
      p.shape = shape.value;
      for (const k of F[p.shape] || []) if (p[k] == null) p[k] = structuredClone(DEFAULTS[k]);
      if (p.shape !== "cylinder") delete p.thread;
      paintParts(); changed();
    };
    const nr = el("b", "mono small pick", String(i + 1));
    nr.title = "Select it in the 3D view";
    const head = el("div", "row");
    head.append(nr, op, shape);
    if (p.thread) head.append(el("span", "chip small", "🔩 thread"));
    head.append(el("span", "grow"), button("✕", "sm ghost", () => removeItem({ kind: "part", body: cur, index: i })));
    row.append(head);
    const fields = el("div", "d3fields");
    const own = !fc && IN_DESIGN_COORDS.has(p.shape);
    for (const k of [...(own ? [] : ["center"]), ...F[p.shape] || [], ...(own ? [] : ["rotate"])]) fields.append(field(p, k));
    if (p.shape === "curved_pipe" && !p.points) p.points = structuredClone(DEFAULTS.points3);
    if (p.shape === "heat_exchanger") fields.append(el("div", "muted small", "LEAP 71's helical heat exchanger — a fixed design (no sizes). Building takes a few minutes."));
    if (p.thread) {
      const th = el("label", "f small", "Thread pitch (mm)");
      const inp = Object.assign(el("input"), { type: "number", step: "0.05", min: "0.25", value: p.thread.pitch || (fc ? isoPitch(2 * p.radius) : roundPitch(2 * p.radius)) });
      inp.onfocus = snap;
      inp.oninput = () => { p.thread = { pitch: Math.max(0.25, num(inp.value, 1)) }; changed(); };
      th.append(inp);
      fields.append(th);
    }
    if (!fc) {
      const rep = el("label", "f small", "Copies (around / in a row)");
      const cnt = Object.assign(el("input"), { type: "number", min: "1", step: "1", value: p.repeat?.count || 1 });
      cnt.onfocus = snap;
      cnt.oninput = () => { const n = Math.max(1, Math.round(num(cnt.value, 1))); if (n > 1) p.repeat = { ...(p.repeat || {}), count: n }; else delete p.repeat; changed(); };
      rep.append(cnt);
      fields.append(rep);
    }
    row.append(fields);
    row.onclick = e => { if (!e.target.closest("select, input, textarea, button")) { if (!same(sel, { kind: "part", body: cur, index: i })) select({ kind: "part", body: cur, index: i }); } };
    box.append(row);
    if (on && (sel.kind === "part" || i === 0)) requestAnimationFrame(() => showRow(row));
  });
  const hs = body().holes || [];
  if (hs.length) {
    box.append(el("div", "f mono small muted", `Holes (${hs.length}) — click one here or in the 3D view to change it`));
    hs.forEach((h, i) => {
      const o = holeInfo(h), on = sel?.kind === "hole" && sel.body === cur && sel.index === i;
      const row = el("div", "d3hole" + (on ? " on" : ""), `<span class="grow">${esc(o.label)} · ${o.depth ? fmt(o.depth) + " mm deep" : "through"}</span>`
        + `<span class="muted mono small">${(h.at || []).map(fmt).join(", ")}</span>`);
      row.onclick = () => select({ kind: "hole", body: cur, index: i });
      row.append(button("✕", "sm ghost", e => { e.stopPropagation(); removeItem({ kind: "hole", body: cur, index: i }); }));
      box.append(row);
      if (on) requestAnimationFrame(() => showRow(row));
    });
  }
  paintUndo();
}
function showRow(row) {  // the selected row in view inside the list — the page itself doesn't jump
  const box = $("d3Parts"), b = box.getBoundingClientRect(), r = row.getBoundingClientRect();
  if (r.top < b.top || r.bottom > b.bottom) box.scrollTop += r.top - b.top - 8;
}
function changed() {  // any edit: the blueprint follows; the last build no longer matches
  if (built) { built = null; for (const id of ["d3Download", "d3Step", "d3Send"]) $(id).hidden = true; }
  if (mode === "built") setMode("blue"); else draw(false);
}

export function open3d(r) {
  if (r) {
    recipe = normalize(r); cur = 0; fresh = false; $("d3Base").value = "change"; built = null;
    for (const id of ["d3Download", "d3Step", "d3Send"]) $(id).hidden = true;
    sel = null; hist = []; fut = []; tool = "select";
    $("d3Tools").querySelectorAll("[data-tool]").forEach(b => b.classList.toggle("on", b.dataset.tool === "select"));
  }
  paintParts();
  setMode("blue");
}

// ---------------------------------------------------------------- copy / paste / delete / nudge
function copySel() {
  if (!sel) return hint("Select a part or a hole first (click it).");
  if (more.length) {  // several: copied together, pasted as a group beside them
    const items = selAll(), bb = boxOf(meshes.filter(m => inSel(m.ref)));
    clip = { many: items.map(x => ({ kind: x.kind, body: x.body, item: structuredClone(itemOf(x)) })), w: Math.max(bb.hi[0] - bb.lo[0], 2), fc: fcMode() };
    return hint(`Copied ${items.length} items — Ctrl+V puts copies next to them.`);
  }
  clip = { kind: sel.kind, item: structuredClone(itemOf(sel)), fc: fcMode() };
  hint(`Copied the ${sel.kind} — Ctrl+V puts a copy next to it.`);
}
function pasteMany() {
  if (clip.fc !== fcMode()) return hint("Those were copied from a design made with the other engine.");
  snap();
  const off = [Math.ceil((clip.w + 5) / snapStep) * snapStep, 0, 0], made = [];
  for (const c of clip.many) {
    const nb = moved(structuredClone(c.item), off, c.kind);
    if (c.kind === "body") {
      recipe.bodies.push({ ...nb, name: String(c.item.name || "part").replace(/( copy)+$/, "") + " copy" });
      made.push({ kind: "body", body: recipe.bodies.length - 1 });
    } else {
      const b = recipe.bodies[c.body] || body(), list = c.kind === "hole" ? (b.holes || (b.holes = [])) : b.parts;
      list.push(nb);
      made.push({ kind: c.kind, body: recipe.bodies.indexOf(b), index: list.length - 1 });
    }
  }
  clip.many = made.map(x => ({ kind: x.kind, body: x.body, item: structuredClone(itemOf(x)) }));  // the next paste goes on from these
  sel = made[0]; more = made.slice(1); cur = sel.body;
  paintParts(); changed(); status();
  hint(`Pasted ${made.length} items — drag them where you want them.`);
}
function paste() {
  if (!clip) return hint("Copy a part or a hole first (select it, Ctrl+C).");
  if (clip.many) return pasteMany();
  if (clip.kind === "part" && clip.fc !== fcMode()) return hint(`That part was copied from a ${clip.fc ? "FreeCAD" : "PicoGK"} design — this one is ${fcMode() ? "FreeCAD" : "PicoGK"}.`);
  snap();
  if (clip.kind === "body") {  // a whole part of the device: a copy next to it, its own width + 5 mm to the right
    const { lo, hi } = bodyBox(clip.item), w = Math.ceil((Math.max(hi[0] - lo[0], 2) + 5) / snapStep) * snapStep;
    const nb = moved(structuredClone(clip.item), [w, 0, 0], "body");
    nb.name = String(clip.item.name || "part").replace(/( copy)+$/, "") + " copy";
    recipe.bodies.push(nb);
    clip.item = structuredClone(nb);
    sel = { kind: "body", body: recipe.bodies.length - 1 };
    cur = sel.body;
    paintParts(); changed(); status();
    return hint("Pasted the whole part — drag it where you want it.");
  }
  const bi = sel?.body ?? cur, b = recipe.bodies[bi];
  let off;
  if (clip.kind === "hole") {  // along the same surface, a hole's width + 5 mm further
    const [u] = across(v3.unit(clip.item.dir || [0, 0, -1]));
    off = u.map(x => x * Math.ceil((holeInfo(clip.item).d + 5) / snapStep) * snapStep);  // stays on the snap grid
  } else {
    const { lo, hi } = partBox(clip.item, fcMode());
    off = [Math.max(hi[0] - lo[0], 2) + 5, 0, 0];  // its own width + 5 mm to the right
  }
  const item = moved(structuredClone(clip.item), off, clip.kind);
  const list = clip.kind === "hole" ? (b.holes || (b.holes = [])) : b.parts;
  list.push(item);
  clip.item = structuredClone(item);  // the next paste goes on from this one
  sel = { kind: clip.kind, body: bi, index: list.length - 1 };
  cur = bi;
  paintParts(); changed(); status();
  hint("Pasted — drag it where you want it.");
}
function removeItem(s) {
  const b = recipe.bodies[s.body];
  if (!b || !itemOf(s)) return;
  if (s.kind === "body") {
    if (recipe.bodies.length === 1) return hint("A design needs at least one part.");
    if (!confirm(`Remove “${b.name || "part"}” (all of it) from the device?`)) return;
    snap(); recipe.bodies.splice(s.body, 1); cur = 0;
  } else if (s.kind === "part" && b.parts.length === 1) {
    if (recipe.bodies.length === 1) return hint("A design needs at least one part.");
    if (!confirm(`“${b.name || "part"}” has nothing else — remove it from the device?`)) return;
    snap(); recipe.bodies.splice(s.body, 1); cur = 0;
  } else {
    snap(); (s.kind === "hole" ? b.holes : b.parts).splice(s.index, 1);
  }
  sel = null; closePop(); paintParts(); changed(); status();
}
// ---------------------------------------------------------------- mirror: a left hand from a right hand
const MIRROR = [["↔", "left / right"], ["↕", "front / back"], ["⇅", "up / down"]];
function designBox() {
  const lo = [Infinity, Infinity, Infinity], hi = [-Infinity, -Infinity, -Infinity];
  for (const b of recipe.bodies) { const bb = bodyBox(b); for (let k = 0; k < 3; k++) { lo[k] = Math.min(lo[k], bb.lo[k]); hi[k] = Math.max(hi[k], bb.hi[k]); } }
  return lo[0] < Infinity ? { lo, hi } : { lo: [0, 0, 0], hi: [0, 0, 0] };
}
/** k = 0 left/right, 1 front/back, 2 up/down. copy: a mirrored copy (a part or the whole design goes beside the
 * original; a shape or hole gets its twin on the other side of its part), else flipped where it is. Nothing selected =
 * every part of the design (a whole left hand). */
function mirrorMany(k, copy) {  // several selected: mirrored as ONE group around its middle (copies go beside the group)
  const items = selAll(), fc = fcMode(), bb = boxOf(meshes.filter(m => inSel(m.ref)));
  const P = bb.lo.map((x, j) => (x + bb.hi[j]) / 2), ax = k === 2 ? 0 : k, off = [0, 0, 0];
  if (copy) off[ax] = Math.ceil((Math.max(bb.hi[ax] - bb.lo[ax], 2) + 5) / snapStep) * snapStep;
  snap();
  const made = [];
  for (const x of items) {
    const nb = moved(mirrored(itemOf(x), x.kind, k, P, fc), off, x.kind);
    if (!copy) { setItem(x, nb); continue; }
    if (x.kind === "body") {
      recipe.bodies.push({ ...nb, name: (nb.reference ? String(nb.name || "part").replace(/\s*\(buy\)\s*$/i, "") + " — 2nd set (buy)"
        : String(nb.name || "part").replace(/ \(mirrored\)$/, "") + " (mirrored)") });
      made.push({ kind: "body", body: recipe.bodies.length - 1 });
    } else {
      const b = recipe.bodies[x.body], list = x.kind === "hole" ? (b.holes || (b.holes = [])) : b.parts;
      list.push(nb);
      made.push({ kind: x.kind, body: x.body, index: list.length - 1 });
    }
  }
  if (made.length) { sel = made[0]; more = made.slice(1); }
  paintParts(); changed(); status();
  hint(`${copy ? "Mirrored copies of" : "Flipped"} the ${items.length} selected ${MIRROR[k][0]} ${MIRROR[k][1]}. Ctrl+Z puts it back.`);
}
function mirrorSel(k, copy) {
  if (more.length) return mirrorMany(k, copy);
  const it = sel && itemOf(sel), fc = fcMode(), kind = it ? sel.kind : "all";
  if (sel && !it) return;
  const own = kind === "all" ? designBox() : kind === "body" ? bodyBox(it) : kind === "hole" ? { lo: it.at, hi: it.at } : partBox(it, fc);
  const mid = bb => bb.lo.map((x, j) => (x + bb.hi[j]) / 2);
  let P = mid(own), twin = false;
  const off = [0, 0, 0];
  if (copy && (kind === "part" || kind === "hole")) {  // an ear on the left -> its twin on the right of the same part
    const pc = mid(bodyBox(recipe.bodies[sel.body]));
    if (Math.abs(P[k] - pc[k]) > 0.5) { P = pc; twin = true; }
  }
  if (copy && !twin) {  // beside it: to the right / behind (an upside-down copy also to the right, not floating)
    const ax = k === 2 ? 0 : k, w = kind === "hole" ? holeInfo(it).d : Math.max(own.hi[ax] - own.lo[ax], 2);
    off[ax] = Math.ceil((w + 5) / snapStep) * snapStep;
  }
  snap();
  const flip = (q, kd) => moved(mirrored(q, kd, k, P, fc), off, kd);
  const named = b => (b.reference ? String(b.name || "part").replace(/\s*\(buy\)\s*$/i, "") + " — 2nd set (buy)"  // pins for the 2nd hand
    : String(b.name || "part").replace(/ \(mirrored\)$/, "") + " (mirrored)");
  if (kind === "all") {
    const out = recipe.bodies.map(b => flip(b, "body"));
    if (copy) recipe.bodies.push(...out.map(b => ({ ...b, name: named(b) }))); else recipe.bodies = out;
  } else if (kind === "body") {
    const nb = flip(it, "body");
    if (copy) { recipe.bodies.push({ ...nb, name: named(nb) }); sel = { kind: "body", body: recipe.bodies.length - 1 }; cur = sel.body; }
    else setItem(sel, nb);
  } else {
    const nb = flip(it, kind), b = recipe.bodies[sel.body];
    if (copy) { const list = kind === "hole" ? (b.holes || (b.holes = [])) : b.parts; list.push(nb); sel = { ...sel, index: list.length - 1 }; }
    else setItem(sel, nb);
  }
  paintParts(); changed(); status();
  const what = kind === "all" ? "the whole design" : kind === "body" ? `“${it.name || "part"}”` : `the ${kind === "hole" ? "hole" : "shape"}`;
  hint(`${copy ? "Mirrored copy of" : "Flipped"} ${what} ${MIRROR[k][0]} ${MIRROR[k][1]}`
    + (copy ? (twin ? " — on the other side of its part" : " — beside the original") : "") + ". Ctrl+Z puts it back.");
}
function mirrorMenu(x, y, flipsOnly) {
  const all = sel && itemOf(sel) ? "" : " (whole design)";
  popMenu(x, y, [
    ...(flipsOnly ? [] : MIRROR.map(([a, w], k) => ({ label: `Mirror copy ${a} ${w}${all}`, act: () => mirrorSel(k, true) }))),
    { sep: true },
    ...MIRROR.map(([a, w], k) => ({ label: `Flip in place ${a} ${w}${all}`, act: () => mirrorSel(k, false) })),
  ]);
}
function removeSel() {  // Del / Delete: everything selected
  if (!more.length) return sel ? removeItem(sel) : hint("Select a part or a hole first.");
  const items = selAll(), gone = new Set(items.filter(x => x.kind === "body").map(x => x.body));
  if (!confirm(`Delete the ${items.length} selected items?`)) return;
  snap();
  for (const x of items.filter(y => y.kind !== "body" && !gone.has(y.body)).sort((a, b) => b.index - a.index)) {
    const b = recipe.bodies[x.body];
    (x.kind === "hole" ? b.holes : b.parts).splice(x.index, 1);  // highest number first: the others keep theirs
  }
  for (const i of [...gone].sort((a, b) => b - a)) recipe.bodies.splice(i, 1);
  recipe.bodies = recipe.bodies.filter(b => b.parts?.length);  // a part with no shapes left goes too
  if (!recipe.bodies.length) { undo(); return hint("A design needs at least one part — nothing was deleted."); }
  sel = null; more = []; cur = 0; closePop(); paintParts(); changed(); status();
}
function nudge(d) {
  if (!sel) return;
  snap();
  for (const x of more) if (itemOf(x)) setItem(x, moved(itemOf(x), d, x.kind));
  setItem(sel, moved(itemOf(sel), d, sel.kind));
  paintParts(); changed(); status();
}
function frameSel() {
  if (!viewer) return;
  const ms = sel ? meshes.filter(m => inSel(m.ref)) : meshes;
  const lo = [Infinity, Infinity, Infinity], hi = [-Infinity, -Infinity, -Infinity];
  for (const m of ms) for (let i = 0; i < m.pos.length; i++) { const k = i % 3, v = m.pos[i] + (m.offset?.[k] || 0); if (v < lo[k]) lo[k] = v; if (v > hi[k]) hi[k] = v; }
  if (lo[0] < Infinity) viewer.focus(lo, hi);
}

// ---------------------------------------------------------------- the 3D view: arrows, handles, drawing circles
const partsOnly = m => m.ref?.kind === "part";
const any = m => !!m.ref;
function boxOf(ms) {
  const lo = [Infinity, Infinity, Infinity], hi = [-Infinity, -Infinity, -Infinity];
  for (const m of ms) for (let i = 0; i < m.pos.length; i++) { const k = i % 3; if (m.pos[i] < lo[k]) lo[k] = m.pos[i]; if (m.pos[i] > hi[k]) hi[k] = m.pos[i]; }
  return { lo, hi };
}
function bodyBox(b) {  // a whole part's box, from its added shapes
  const lo = [Infinity, Infinity, Infinity], hi = [-Infinity, -Infinity, -Infinity];
  for (const [i, p] of (b.parts || []).entries()) {
    if (i && ["cut", "subtract"].includes(p.op)) continue;
    const bb = partBox(p, fcMode());
    for (let k = 0; k < 3; k++) { lo[k] = Math.min(lo[k], bb.lo[k]); hi[k] = Math.max(hi[k], bb.hi[k]); }
  }
  return lo[0] < Infinity ? { lo, hi } : { lo: [0, 0, 0], hi: [0, 0, 0] };
}
function gizmos() {  // what can be grabbed now (screen positions): 3 move arrows, the stretch handles, or 3 turn rings
  if (!sel || mode !== "blue" || !viewer || drawing || !["select", "stretch", "rotate"].includes(tool)) return [];
  const it = itemOf(sel), ms = meshes.filter(x => inSel(x.ref)), m = ms[0];
  if (!it || !m) return [];
  const off = m.offset || [0, 0, 0], out = [];
  if (tool === "stretch" && sel.kind === "part") {
    for (const h of handlesFor(it, fcMode())) {
      const pos = v3.add(h.pos, off), P = viewer.project(pos);
      if (P[2] <= 0) continue;
      const front = v3.dot(h.dir, viewer.ray(P[0], P[1]).d) < 0.05;  // its face looks at you (the others: faded)
      out.push({ id: "h:" + h.id, kind: "handle", h, pos, P, front, tip: viewer.project(v3.add(pos, h.dir, 22 * viewer.pxSize(pos))) });
    }
    return out;
  }
  const { lo, hi } = boxOf(ms), P = sel.kind === "hole" ? it.at : lo.map((x, j) => (x + hi[j]) / 2), c = v3.add(P, off), C = viewer.project(c);
  if (C[2] <= 0) return [];
  if (tool === "rotate") {  // ring k lies across axis k: dragging along it turns the selection around that axis
    const R = 70 * viewer.pxSize(c), AXS = [[1, 0, 0], [0, 1, 0], [0, 0, 1]];
    for (let k = 0; k < 3; k++) {
      const a = AXS[(k + 1) % 3], b = AXS[(k + 2) % 3], pts = [];
      for (let i = 0; i <= 64; i++) { const t = i / 64 * Math.PI * 2; pts.push(viewer.project(v3.add(v3.add(c, a, R * Math.cos(t)), b, R * Math.sin(t)))); }
      out.push({ id: "r" + k, kind: "ring", k, a, b, c, P, pts });
    }
    return out;
  }
  const L = 75 * viewer.pxSize(c);
  [[1, 0, 0], [0, 1, 0], [0, 0, 1]].forEach((a, k) => {
    const B = viewer.project(v3.add(c, a, L));
    if (B[2] > 0) out.push({ id: "a" + k, kind: "axis", k, a, c, C, B });
  });
  return out;
}
const segDist = (p, a, b) => {
  const dx = b[0] - a[0], dy = b[1] - a[1], t = Math.max(0, Math.min(1, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / (dx * dx + dy * dy || 1)));
  return Math.hypot(p[0] - a[0] - t * dx, p[1] - a[1] - t * dy);
};
function ringDist(p, pts) {
  let d = Infinity;
  for (let i = 1; i < pts.length; i++) if (pts[i][2] > 0 && pts[i - 1][2] > 0) d = Math.min(d, segDist(p, pts[i - 1], pts[i]));
  return d;
}
function ringAngle(g, p) {  // where the pointer is around ring g (degrees); null = the ring is seen edge-on
  const r = viewer.ray(p[0], p[1]), n = [0, 0, 0];
  n[g.k] = 1;
  if (Math.abs(v3.dot(r.d, n)) < 0.15) return null;
  const v = v3.sub(rayPlane(r, g.c, n), g.c);
  return Math.atan2(v3.dot(v, g.b), v3.dot(v, g.a)) * 180 / Math.PI;
}
function gizmoAt(p) {
  let best = null, bd = 12;
  for (const g of gizmos()) {
    if (g.kind === "axis" && Math.hypot(p[0] - g.C[0], p[1] - g.C[1]) < 14) continue;  // the middle: grab the part itself
    const d = g.kind === "axis" ? segDist(p, g.C, g.B) : g.kind === "ring" ? ringDist(p, g.pts) - 2
      : Math.hypot(p[0] - g.P[0], p[1] - g.P[1]) + (g.front ? 0 : 7);
    if (d < bd) { bd = d; best = g; }
  }
  return best;
}
function snapAt(p, n) {  // a clicked point on a flat face: on the snap grid across the face (exactly on the face)
  const k = [0, 1, 2].find(i => Math.abs(n[i]) > 0.999);
  return p.map((x, i) => (k === undefined || i === k ? Math.round(x * 1000) / 1000 : Math.round(x / snapStep) * snapStep));
}
const markR = () => (tool === "dent" ? lastDent.width / 2 : holeInfo(lastHole).d / 2);

const editTool = {
  hover(p) {
    if (mode !== "blue") return "";
    const g = gizmoAt(p);
    if ((g?.id || null) !== hoverG) { hoverG = g?.id || null; viewer.redraw(); }
    if (g) return g.kind === "axis" ? "move" : g.kind === "ring" ? "grab" : "pointer";
    if (tool === "hole" || tool === "dent") {
      if (pop) return "";
      const h = viewer.pick(p[0], p[1], partsOnly);
      marker = h ? { at: snapAt(h.at, h.normal), n: h.normal, r: markR(), off: h.mesh.offset, square: tool === "dent" && lastDent.shape === "square" } : null;
      viewer.redraw();
      return h ? "crosshair" : "";
    }
    const h = viewer.pick(p[0], p[1], any);
    return h ? (inSel(h.mesh.ref) && tool !== "thread" ? "move" : "pointer") : "";
  },
  leave() { if (marker && !pop && !drawing) { marker = null; viewer?.redraw(); } },
  down(p, e) {
    if (mode !== "blue") return false;
    const g = gizmoAt(p);
    if (g) { startDrag(g, p); return true; }
    if (tool === "hole" || tool === "dent") {
      if (viewer.pick(p[0], p[1], m => m.ref?.kind === "hole")) return false;  // a click on a hole selects it
      const h = viewer.pick(p[0], p[1], partsOnly);
      if (!h) return false;
      closePop();
      drawing = { at: snapAt(h.at, h.normal), n: h.normal, ref: h.mesh.ref, off: h.mesh.offset || [0, 0, 0], start: p, r: markR(), drawn: false,
        square: tool === "dent" && lastDent.shape === "square" };
      marker = drawing;
      viewer.redraw();
      return true;
    }
    if (["select", "stretch", "rotate"].includes(tool) && sel) {
      const h = viewer.pick(p[0], p[1], any);
      if (h && inSel(h.mesh.ref)) { startPlane(h, p, e?.ctrlKey || e?.metaKey || ctrlHeld); return true; }
    }
    return false;
  },
  move(p, e) { if (drag) dragMove(p, e); else if (drawing) drawMove(p); },
  up() { if (drag) dragEnd(); else if (drawing) drawEnd(); },
  click(p, e) {
    if (mode !== "blue") return;
    const h = viewer.pick(p[0], p[1], any);
    if (tool === "thread") { if (h) openThread(h.mesh.ref, p); else hint("Click a cylinder — or a hole."); return; }
    if ((tool === "hole" || tool === "dent") && h?.mesh.ref.kind !== "hole") return;
    if ((e?.ctrlKey || e?.metaKey || ctrlHeld) && sel) return h ? toggleSel(h.mesh.ref) : undefined;  // Ctrl+click: one more (empty space: keep all)
    if (same(h?.mesh.ref, sel) && !more.length) return;
    select(h ? h.mesh.ref : null);
  },
  dblclick(p, e) {  // double-click: the whole part of the device (all its shapes and holes) — to move / copy it in one go
    if (mode !== "blue" || !["select", "stretch", "rotate"].includes(tool)) return false;
    const h = viewer.pick(p[0], p[1], any);
    if (!h) return false;
    if ((e?.ctrlKey || e?.metaKey || ctrlHeld) && sel) { toggleSel({ kind: "body", body: h.mesh.ref.body }); return true; }
    select({ kind: "body", body: h.mesh.ref.body });
    return true;
  },
  cancel() {
    if (drag) { setItem(drag.ref, drag.start); for (const o of drag.others || []) setItem(o.ref, o.start); drag = null; }
    drawing = null; label = null; draw(false);
  },
  menu(p, e) { editMenu(p, e); },
};

function startDrag(g, p) {
  snap();
  const r = viewer.ray(p[0], p[1]), start = structuredClone(itemOf(sel));
  if (g.kind === "axis") drag = { kind: "axis", k: g.k, a: g.a, c: g.c, t0: lineParam(g.c, g.a, r) ?? 0, start, ref: { ...sel } };
  else if (g.kind === "ring") drag = { kind: "turn", k: g.k, g, P: g.P, a0: ringAngle(g, p), x0: p[0], start, ref: { ...sel } };
  else drag = { kind: "handle", h: g.h, pos: g.pos, t0: lineParam(g.pos, g.h.dir, r) ?? 0, start, ref: { ...sel } };
  if (g.kind !== "handle") drag.others = others();  // several selected: they all move / turn together (stretch: just this one)
}
const others = () => more.filter(x => itemOf(x)).map(x => ({ ref: { ...x }, start: structuredClone(itemOf(x)) }));
function startPlane(h, p, ctrl) {  // drag the part itself: it slides on the flat plane facing you (a hole: along its surface)
  snap();
  const it = itemOf(sel);
  let n;
  if (sel.kind === "hole") n = v3.unit(it.dir || [0, 0, -1]);
  else { const d = h.ray.d, k = [0, 1, 2].reduce((a, i) => (Math.abs(d[i]) > Math.abs(d[a]) ? i : a), 0); n = [0, 0, 0]; n[k] = 1; }
  drag = { kind: "plane", n, P0: h.point, start: structuredClone(it), ref: { ...sel }, hit: h.mesh.ref, p0: p, moved: false, ctrl,
           others: others() };
}
function dragMove(p, e) {
  if (!drag.moved && drag.p0 && Math.hypot(p[0] - drag.p0[0], p[1] - drag.p0[1]) < 4) return;  // still a click
  drag.moved = true;
  const r = viewer.ray(p[0], p[1]), step = e.shiftKey ? 0.1 : snapStep, q = v => Math.round(v / step) * step;
  let text = "";
  if (drag.kind === "axis") {
    const t = lineParam(drag.c, drag.a, r);
    if (t == null) return;
    const d = q(t - drag.t0);
    setItem(drag.ref, moved(drag.start, drag.a.map(x => x * d), drag.ref.kind));
    for (const o of drag.others || []) setItem(o.ref, moved(o.start, drag.a.map(x => x * d), o.ref.kind));
    text = `${"XYZ"[drag.k]} ${d >= 0 ? "+" : ""}${fmt(d)} mm`;
  } else if (drag.kind === "turn") {
    let deg;
    if (drag.a0 != null) { const a = ringAngle(drag.g, p); if (a == null) return; deg = a - drag.a0; } else deg = (p[0] - drag.x0) * 0.6;
    deg = ((deg % 360) + 540) % 360 - 180;
    const st = e.shiftKey ? 1 : 15;
    deg = Math.round(deg / st) * st + 0;
    setItem(drag.ref, turned(drag.start, drag.ref.kind, drag.k, deg, drag.P));
    for (const o of drag.others || []) setItem(o.ref, turned(o.start, o.ref.kind, drag.k, deg, drag.P));
    text = `Turn around ${"XYZ"[drag.k]}: ${deg > 0 ? "+" : ""}${deg}°`;
  } else if (drag.kind === "handle") {
    const t = lineParam(drag.pos, drag.h.dir, r);
    if (t == null) return;
    const np = drag.h.apply(drag.start, q(t - drag.t0));
    setItem(drag.ref, np);
    text = drag.h.what(np);
  } else {
    const hit = rayPlane(r, drag.P0, drag.n);
    if (!hit) return;
    let d = v3.sub(hit, drag.P0);
    const k = [0, 1, 2].find(i => Math.abs(drag.n[i]) > 0.999);
    d = k === undefined ? v3.add(d, drag.n, -v3.dot(d, drag.n)) : d.map((v, i) => (i === k ? 0 : q(v)));
    setItem(drag.ref, moved(drag.start, d, drag.ref.kind));
    for (const o of drag.others || []) setItem(o.ref, moved(o.start, d, o.ref.kind));
    text = ["x", "y", "z"].map((a, i) => (Math.abs(d[i]) > 1e-9 ? `${a} ${d[i] > 0 ? "+" : ""}${fmt(d[i])}` : "")).filter(Boolean).join(" · ") + " mm";
  }
  label = { at: p, text };
  draw(false);
}
function dragEnd() {
  const d = drag;
  drag = null; label = null;
  if (d?.kind === "plane" && !d.moved && d.ctrl && d.hit) return toggleSel(d.hit);  // Ctrl+click on a selected one: out
  if (d?.kind === "plane" && !d.moved && !more.length && sel?.kind === "body" && d.hit) return select(d.hit);  // a click on one of its shapes
  paintParts(); draw(false); status();
  if (pop?.ref) placePop(pop.ref);
}
function drawMove(p) {  // press and drag on a surface: the circle grows with the pointer
  if (!drawing.drawn && Math.hypot(p[0] - drawing.start[0], p[1] - drawing.start[1]) < 6) return;
  drawing.drawn = true;
  const c = v3.add(drawing.at, drawing.off), hit = rayPlane(viewer.ray(p[0], p[1]), c, drawing.n);
  if (!hit) return;
  drawing.r = Math.max(0.25, Math.round(Math.hypot(...v3.sub(hit, c)) * 4) / 4);  // 0.5 mm steps across
  const s = tool === "hole" ? screwFor(drawing.r * 2) : null;
  label = { at: p, text: `Ø ${fmt(drawing.r * 2)} mm${s ? ` — fits an ${s} screw` : ""}` };
  viewer.redraw();
}
function drawEnd() {
  const d = drawing;
  drawing = null; label = null;
  marker = { ...d };
  if (tool === "hole") openHolePop({ at: d.at, dir: d.n.map(x => -x), body: d.ref.body, off: d.off }, d.drawn ? 2 * d.r : null);
  else openDentPop(d, d.drawn ? 2 * d.r : null);
}

function overlay(g, v) {  // drawn on top of the 3D view: arrows / handles, the circle being placed, the live size
  if (mode !== "blue") return;
  for (const z of gizmos()) {
    const hot = z.id === hoverG || (drag && ((drag.kind === "axis" && z.id === "a" + drag.k) || (drag.kind === "turn" && z.id === "r" + drag.k)
      || (drag.kind === "handle" && z.id === "h:" + drag.h.id)));
    if (z.kind === "axis") arrow(g, z.C, z.B, ["#ff5c5c", "#4cd964", "#4aa3ff"][z.k], hot, "XYZ"[z.k]);
    else if (z.kind === "ring") hoop(g, z.pts, ["#ff5c5c", "#4cd964", "#4aa3ff"][z.k], hot);
    else knob(g, z.P, z.tip, hot, z.front);
  }
  const mk = drawing || marker;
  if (mk && (tool === "hole" || tool === "dent")) ring(g, v, mk);
  if (label) tag(g, label.at, label.text);
}
function arrow(g, A, B, col, hot, txt) {
  const dx = B[0] - A[0], dy = B[1] - A[1], L = Math.hypot(dx, dy) || 1, ux = dx / L, uy = dy / L, s = hot ? 12 : 9;
  g.save();
  g.lineCap = "round";
  for (const [w, c] of [[hot ? 9 : 7, "rgba(0,0,0,.55)"], [hot ? 5 : 3, col]]) {
    g.strokeStyle = c; g.lineWidth = w; g.beginPath(); g.moveTo(A[0] + ux * 12, A[1] + uy * 12); g.lineTo(B[0], B[1]); g.stroke();
  }
  g.fillStyle = col; g.strokeStyle = "rgba(0,0,0,.6)"; g.lineWidth = 1.5;
  g.beginPath(); g.moveTo(B[0] + ux * s * 1.4, B[1] + uy * s * 1.4); g.lineTo(B[0] - uy * s * 0.7, B[1] + ux * s * 0.7); g.lineTo(B[0] + uy * s * 0.7, B[1] - ux * s * 0.7);
  g.closePath(); g.fill(); g.stroke();
  g.font = "700 11px ui-monospace, Consolas, monospace"; g.fillStyle = col;
  g.fillText(txt, B[0] + ux * (s * 1.4 + 9) - 4, B[1] + uy * (s * 1.4 + 9) + 4);
  g.restore();
}
function hoop(g, pts, col, hot) {  // a turn ring (broken where it goes behind the eye)
  g.save();
  for (const [w, c] of [[hot ? 8 : 6, "rgba(0,0,0,.5)"], [hot ? 4.5 : 2.5, col]]) {
    g.strokeStyle = c; g.lineWidth = w; g.beginPath();
    pts.forEach((P, i) => (i && P[2] > 0 && pts[i - 1][2] > 0 ? g.lineTo(P[0], P[1]) : g.moveTo(P[0], P[1])));
    g.stroke();
  }
  g.restore();
}
function knob(g, P, tip, hot, front) {
  const s = hot ? 8 : front ? 6 : 4.5;
  g.save();
  g.globalAlpha = front || hot ? 1 : 0.45;
  g.strokeStyle = "rgba(255,210,60,.9)"; g.lineWidth = 2; g.beginPath(); g.moveTo(P[0], P[1]); g.lineTo(tip[0], tip[1]); g.stroke();
  g.fillStyle = hot ? "#ffd23c" : "#ffffff"; g.strokeStyle = "rgba(0,0,0,.75)"; g.lineWidth = 2;
  g.fillRect(P[0] - s, P[1] - s, 2 * s, 2 * s); g.strokeRect(P[0] - s, P[1] - s, 2 * s, 2 * s);
  g.restore();
}
function ring(g, v, mk) {  // the hole / dent circle lying on the surface
  const c = v3.add(mk.at, mk.off || [0, 0, 0]), [u, w] = across(mk.n), r = mk.r, pts = [];
  if (mk.square) for (const [a, b] of [[-1, -1], [1, -1], [1, 1], [-1, 1], [-1, -1]]) pts.push(v.project(v3.add(v3.add(c, u, a * r), w, b * r)));
  else for (let i = 0; i <= 48; i++) { const a = i / 48 * Math.PI * 2; pts.push(v.project(v3.add(v3.add(c, u, r * Math.cos(a)), w, r * Math.sin(a)))); }
  if (pts.some(P => P[2] <= 0)) return;
  g.save();
  g.beginPath(); pts.forEach((P, i) => (i ? g.lineTo(P[0], P[1]) : g.moveTo(P[0], P[1])));
  g.strokeStyle = "rgba(0,0,0,.65)"; g.lineWidth = 5; g.stroke();
  g.strokeStyle = tool === "dent" ? "#ffd166" : "#ff6b6b"; g.lineWidth = 2.5; g.stroke();
  const C = v.project(c);
  g.strokeStyle = "#fff"; g.lineWidth = 1.5;
  g.beginPath(); g.moveTo(C[0] - 5, C[1]); g.lineTo(C[0] + 5, C[1]); g.moveTo(C[0], C[1] - 5); g.lineTo(C[0], C[1] + 5); g.stroke();
  g.restore();
}
function tag(g, p, text) {
  g.save();
  g.font = "600 12px ui-monospace, Consolas, monospace";
  const w = g.measureText(text).width + 14, x = p[0] + 16, y = p[1] - 30;
  g.fillStyle = "rgba(10,14,10,.85)"; g.strokeStyle = "rgba(255,255,255,.25)";
  g.beginPath(); g.roundRect ? g.roundRect(x, y, w, 22, 6) : g.rect(x, y, w, 22); g.fill(); g.stroke();
  g.fillStyle = "#fff"; g.fillText(text, x + 7, y + 15);
  g.restore();
}

// ---------------------------------------------------------------- the small boxes: hole, dent, thread
function closePop() {
  if (pop) { pop.el.remove(); pop.done?.(); }
  pop = null;
  if (!drawing) marker = null;
  viewer?.redraw();
}
function placeBox(boxEl, x, y) {
  const host = $("d3Canvas"), W = host.clientWidth, H = host.clientHeight;
  boxEl.style.left = Math.max(8, Math.min(W - boxEl.offsetWidth - 8, x + 16)) + "px";
  boxEl.style.top = Math.max(8, Math.min(H - boxEl.offsetHeight - 8, y - 24)) + "px";
}
function placePop(ref) {  // next to the hole it edits (after it moved)
  const it = itemOf(ref), m = meshes.find(x => same(x.ref, ref));
  if (!pop || !it?.at || !viewer) return;
  const P = viewer.project(v3.add(it.at, m?.offset || [0, 0, 0]));
  placeBox(pop.el, P[0], P[1]);
}
function sayBox(onText) {  // "type or say it" + the microphone
  const row = el("div", "row");
  const inp = Object.assign(el("input", "grow say"), { placeholder: "Type or say it: M3 · 2 cm · M4 countersunk · 8 mm deep" });
  const mic = button("🎤", "sm mic", () => listen(mic, inp, onText));
  mic.title = "Say it (press again when you're done)";
  let t;
  inp.oninput = () => { clearTimeout(t); t = setTimeout(() => onText(inp.value), 250); };
  inp.onkeydown = e => { if (e.key === "Enter") { clearTimeout(t); onText(inp.value); } };  // before the box's Enter = OK
  row.append(inp, mic);
  return { row, inp };
}
let rec = null;
async function listen(btn, input, onText) {  // a few words through the microphone -> text (the chat's speech recognition)
  if (rec) return rec.stop();
  let stream;
  try { stream = await navigator.mediaDevices.getUserMedia({ audio: true }); } catch { return alert("The microphone isn't available — allow it for this app."); }
  const ctx = new AudioContext(), src = ctx.createMediaStreamSource(stream), node = ctx.createScriptProcessor(4096, 1, 1), frames = [];
  node.onaudioprocess = e => frames.push(new Float32Array(e.inputBuffer.getChannelData(0)));
  src.connect(node); node.connect(ctx.destination);
  btn.classList.add("rec");
  const ph = input.placeholder;
  input.placeholder = "Listening… press 🎤 again when you're done";
  const stop = async () => {
    rec = null; clearTimeout(timer);
    node.disconnect(); src.disconnect(); stream.getTracks().forEach(x => x.stop());
    const rate = ctx.sampleRate;
    ctx.close();
    btn.classList.remove("rec");
    input.placeholder = "Writing down what you said…";
    const fd = new FormData();
    fd.append("file", toWav(frames, rate), "voice.wav");
    try { const { text } = await api("/api/stt", { method: "POST", body: fd }); input.value = (text || "").trim(); onText(input.value); }
    catch (e) { hint("Speech recognition failed: " + e.message); }
    finally { input.placeholder = ph; }
  };
  const timer = setTimeout(stop, 10000);
  rec = { stop };
}
function popShell(title) {
  const box = el("div", "d3pop");
  const head = el("div", "row", `<b>${esc(title)}</b><span class="grow"></span>`);
  head.append(button("✕", "sm ghost", closePop));
  box.append(head);
  box.onpointerdown = e => e.stopPropagation();
  box.onkeydown = e => { if (e.key === "Enter" && e.target.tagName === "INPUT") box.querySelector(".ok")?.click(); };
  return box;
}
const lab = (text, ctl) => { const l = el("label", "f", esc(text)); l.append(ctl); return l; };
const sel_ = (opts, val) => el("select", null, opts.map(([v, t]) => `<option value="${esc(v)}" ${String(v) === String(val ?? "") ? "selected" : ""}>${esc(t)}</option>`).join(""));
const numIn = (val, step = "0.5", min = "0") => Object.assign(el("input"), { type: "number", step, min, value: val ?? "" });

/** The hole box: a new hole at target {at, dir, body} — or an existing one {ref}. drawnD = the circle you drew. */
function openHolePop(target, drawnD) {
  closePop();
  const editing = !!target.ref, fc = fcMode();
  const spec = editing ? structuredClone(itemOf(target.ref)) : { ...structuredClone(lastHole), at: target.at, dir: target.dir };
  if (drawnD) { const s = screwFor(drawnD); if (s) { spec.for = s; spec.fit = "clearance"; delete spec.diameter; } else { delete spec.for; spec.diameter = drawnD; } }
  if (target.fit) spec.fit = target.fit;
  if (editing) snap();  // everything changed in this box = one undo step
  const box = popShell(editing ? "Hole" : "New hole");
  const say = sayBox(text => {
    const o = parseSay(text);
    if (o.dent && !editing) return openDentPop({ at: target.at, n: target.dir.map(x => -x), ref: { body: target.body }, off: target.off }, null, text);
    fill(o);
  });
  const size = sel_([...SCREWS.map(s => [s, s]), ["", "Ø mm"]], spec.for || "");
  const dia = numIn(spec.diameter ?? 5, "0.1", "0.3"), depth = numIn(spec.depth || 0);
  const fit = sel_(FITS, spec.fit || "clearance");
  const head = sel_([["", "plain"], ["countersink", "countersink (flat-head screw)"], ["counterbore", "counterbore (socket-head screw)"]], spec.head || "");
  const pos = el("div", "trio");
  const xyz = [0, 1, 2].map(i => { const n = numIn(fmt((spec.at || [0, 0, 0])[i]), "0.5", ""); n.title = "xyz"[i]; pos.append(n); return n; });
  const info = el("div", "muted small");
  const r1 = el("div", "row"), diaL = lab("Ø mm", dia);
  r1.append(lab("Size", size), diaL, lab("Depth (0 = through)", depth));
  box.append(say.row, r1, lab("Screw", fit), lab("Head", head), lab("Where (x · y · z)", pos), info);
  const foot = el("div", "row");
  if (editing) foot.append(button("Delete", "sm danger", () => removeItem(target.ref)));
  foot.append(el("span", "grow"));
  const ok = button(editing ? "Done" : "Add hole", "sm primary ok", () => {
    if (!editing) {
      snap();
      const b = recipe.bodies[target.body] || body(), list = b.holes || (b.holes = []);
      list.push(read());
      lastHole = { ...read() }; delete lastHole.at; delete lastHole.dir;
      sel = { kind: "hole", body: recipe.bodies.indexOf(b), index: list.length - 1 };
      cur = sel.body;
      closePop(); paintParts(); changed(); status();
      hint("Hole added — click another spot for the next one, or Move (V) to move it.");
    } else { closePop(); paintParts(); status(); }
  });
  foot.append(ok);
  box.append(foot);
  function read() {  // the box -> a hole
    const h = { at: xyz.map(n => num(n.value, 0)), dir: spec.dir || [0, 0, -1], fit: fit.value, depth: Math.max(0, num(depth.value, 0)) };
    if (size.value) { h.for = size.value; if (head.value) h.head = head.value; } else h.diameter = Math.max(0.3, num(dia.value, 5));
    if (h.fit === "thread" && spec.pitch) h.pitch = spec.pitch;
    return h;
  }
  function paint() {  // what it means, in words + the warnings that matter
    const h = read(), o = holeInfo(h), custom = !size.value;
    diaL.hidden = !custom;
    head.disabled = custom;
    for (const opt of fit.options) opt.disabled = custom && !["clearance", "thread"].includes(opt.value);
    let t = `Drill Ø${fmt(o.d)} mm, ${o.depth ? fmt(o.depth) + " mm deep" : "all the way through"}`;
    if (o.csink) t += ` · countersink Ø${o.csink}`;
    if (o.cbore) t += ` · counterbore Ø${o.cbore[0]} × ${o.cbore[1]} mm`;
    if (o.nut) t += ` · hex pocket ${o.nut[0]} mm for the nut`;
    if (h.fit === "insert") t += " · press the insert in with a soldering iron";
    if (h.fit === "thread") {
      t += fc ? ` · ISO thread, pitch ${h.pitch || isoPitch(o.d)} mm` : ` · round printed thread, pitch ${h.pitch || roundPitch(o.d)} mm (for a printed bolt)`;
      if (o.d < 6) t += " — under M6 printed threads don't hold: “cuts its own thread” or an insert is better";
    }
    info.textContent = t + ".";
    marker = { at: h.at, n: (h.dir || [0, 0, -1]).map(x => -x), r: o.d / 2, off: target.off || meshes.find(m => same(m.ref, target.ref))?.offset };
    if (editing) { setItem(target.ref, h); draw(false); } else viewer?.redraw();
  }
  function fill(o) {  // from typed / spoken words
    if (o.for) { size.value = o.for; } else if (o.diameter) { size.value = ""; dia.value = fmt(o.diameter); const s = screwFor(o.diameter); if (s && !o.fit) size.value = s; }
    if (o.fit) fit.value = o.fit;
    if (o.head !== undefined) head.value = o.head;
    if (o.depth !== undefined) depth.value = fmt(o.depth);
    paint();
  }
  for (const c of [size, dia, depth, fit, head, ...xyz]) c.addEventListener(c.tagName === "SELECT" ? "change" : "input", paint);
  $("d3Canvas").append(box);
  pop = { el: box, ref: editing ? target.ref : null };
  paint();
  const P = viewer.project(v3.add(spec.at || [0, 0, 0], target.off || meshes.find(m => same(m.ref, target.ref))?.offset || [0, 0, 0]));
  placeBox(box, P[0], P[1]);
  if (!editing) say.inp.focus();
}

/** The dent box: at d {at, n, ref, off}; drawnD = the circle you drew; text = words already typed in the hole box. */
function openDentPop(d, drawnD, text) {
  closePop();
  if (tool !== "dent") { tool = "dent"; $("d3Tools").querySelectorAll("[data-tool]").forEach(b => b.classList.toggle("on", b.dataset.tool === "dent")); }
  const spec = { ...lastDent, ...(drawnD ? { width: drawnD } : {}) };
  const box = popShell("New dent");
  const say = sayBox(t => fill(parseSay(t)));
  const shape = sel_([["round", "round"], ["square", "square"], ["dimple", "finger dimple (rounded)"]], spec.shape);
  const width = numIn(spec.width, "0.5", "0.5"), depth = numIn(spec.depth, "0.5", "0.2");
  const r1 = el("div", "row");
  r1.append(lab("Shape", shape), lab("Width / Ø mm", width), lab("Depth mm", depth));
  const info = el("div", "muted small", "A dent becomes a part of its own (red, cut away): you can move and stretch it after.");
  const foot = el("div", "row", `<span class="grow"></span>`);
  foot.append(button("Add dent", "sm primary ok", () => {
    snap();
    const s = read(), b = recipe.bodies[d.ref?.body] || body();
    b.parts.push(dentPart(d.at, d.n, s.shape, s.width, s.depth, fcMode()));
    lastDent = s;
    sel = { kind: "part", body: recipe.bodies.indexOf(b), index: b.parts.length - 1 };
    cur = sel.body;
    closePop(); paintParts(); changed(); status();
    hint("Dent added — Stretch (S) changes its size, Move (V) moves it.");
  }));
  box.append(say.row, r1, info, foot);
  function read() { return { shape: shape.value, width: Math.max(0.5, num(width.value, 10)), depth: Math.max(0.2, num(depth.value, 2)) }; }
  function paint() { const s = read(); marker = { ...d, r: s.width / 2, square: s.shape === "square" }; viewer?.redraw(); }
  function fill(o) {
    if (o.shape) shape.value = o.shape;
    if (o.diameter) width.value = fmt(o.diameter);
    if (o.depth) depth.value = fmt(o.depth);
    paint();
  }
  for (const c of [shape, width, depth]) c.addEventListener(c.tagName === "SELECT" ? "change" : "input", paint);
  $("d3Canvas").append(box);
  pop = { el: box };
  if (text) { say.inp.value = text; fill(parseSay(text)); } else paint();
  const P = viewer.project(v3.add(d.at, d.off || [0, 0, 0]));
  placeBox(box, P[0], P[1]);
  say.inp.focus();
}

/** Thread tool: a cylinder gets a thread (outside when it's added, inside when it's cut away); a hole becomes threaded. */
function openThread(ref, p) {
  const it = itemOf(ref);
  if (!it) return;
  if (ref.kind === "hole") {  // the hole box opens with "printed thread" picked (its note says when that's a bad idea)
    select(ref, true);
    openHolePop({ ref, fit: "thread" });
    return;
  }
  if (it.shape !== "cylinder") return hint(`Threads go on a cylinder (this is a ${it.shape}) — or on a hole.`);
  select(ref, true);
  closePop();
  const fc = fcMode(), d = 2 * (+it.radius || 10), inside = ["cut", "subtract"].includes(it.op) && ref.index > 0;
  const iso = `M${fmt(Math.round(d * 2) / 2)}`, auto = fc ? isoPitch(d) : roundPitch(d);
  const box = popShell(`Thread — Ø${fmt(d)} mm cylinder`);
  const pitch = numIn(it.thread?.pitch || auto, "0.05", "0.25");
  const info = el("div", "muted small", (inside ? "Cut away = a threaded HOLE for a bolt this size. " : "Added = a threaded ROD this size. ")
    + (fc ? `ISO metric (${iso} × ${auto} is the standard pitch), 0.15 mm play — fits a metal ${iso} ${inside ? "bolt" : "nut"} when printed well.`
      : `A round printed thread (pitch ${auto} mm, 0.3 mm play): made for a printed partner.`)
    + (d < 6 ? " Under 6 mm printed threads don't hold — a heat-set insert or a self-tapping screw hole is better." : ""));
  const foot = el("div", "row");
  if (it.thread) foot.append(button("Remove thread", "sm", () => { snap(); delete it.thread; closePop(); paintParts(); changed(); status(); }));
  foot.append(el("span", "grow"), button(it.thread ? "Save" : "Make thread", "sm primary ok", () => {
    snap();
    it.thread = { pitch: Math.max(0.25, num(pitch.value, auto)) };
    closePop(); paintParts(); changed(); status();
    hint(`Threaded — the blueprint shows rings; Build makes the real thread${fc ? " (a few seconds each)" : ""}.`);
  }));
  box.append(lab("Pitch (mm per turn)", pitch), info, foot);
  $("d3Canvas").append(box);
  pop = { el: box };
  placeBox(box, p[0], p[1]);
}

// ---------------------------------------------------------------- page controls
$("d3Body").onchange = () => { cur = +$("d3Body").value; sel = null; closePop(); paintParts(); draw(false); status(); };
$("d3Explode").onclick = () => {
  if (!ex) return;
  exploded = !exploded;
  exButton();
  const s = $("d3Panel").querySelector("input[type=range]");
  ex.animateTo(exploded ? 0.8 : 0, 650, k => { if (s) s.value = k; });
};
$("d3AddBody").onclick = () => {
  snap();
  recipe.bodies.push({ name: `part ${recipe.bodies.length + 1}`, parts: [fcMode()
    ? { op: "add", shape: "cylinder", axis: "z", center: [40, 0, 10], radius: 8, height: 20 }
    : { op: "add", shape: "cylinder", center: [40, 0, 0], radius: 8, height: 20 }] });
  cur = recipe.bodies.length - 1; sel = { kind: "part", body: cur, index: 0 }; paintParts(); changed(); status();
};
$("d3DelBody").onclick = () => {
  if (recipe.bodies.length < 2 || !confirm(`Remove “${body().name}” from the device?`)) return;
  snap(); recipe.bodies.splice(cur, 1); cur = 0; sel = null; closePop(); paintParts(); changed(); status();
};
$("d3Ref").onchange = () => { snap(); body().reference = $("d3Ref").checked || undefined; paintBodies(); changed(); };
$("d3AddPart").onclick = () => {
  snap();
  body().parts.push(fcMode() ? { op: "add", shape: "box", center: [0, 0, 30], size: [20, 20, 20] } : { op: "add", shape: "sphere", center: [0, 0, 20], radius: 10 });
  sel = { kind: "part", body: cur, index: body().parts.length - 1 };
  paintParts(); changed(); status();
};
$("d3Name").onfocus = snap;
$("d3Name").oninput = () => { body().name = $("d3Name").value; if (recipe.bodies.length === 1) recipe.name = body().name; paintBodies(); };
for (const [id, pg, fc] of [["d3Hollow", "hollow", "shell"], ["d3Smooth", "smooth", "fillet"], ["d3Chamfer", null, "chamfer"]]) {
  $(id).onfocus = snap;
  $(id).oninput = () => { const k = fcMode() ? fc : pg; if (k) { body()[k] = num($(id).value, 0); changed(); } };
}
$("d3Engine").onchange = () => {
  const toFC = $("d3Engine").value === "freecad";
  if (toFC === fcMode()) return;
  const { recipe: r, dropped, changed: approx } = convert(recipe, toFC);
  if (dropped.length && !confirm(`${toFC ? "FreeCAD" : "PicoGK"} has no ${dropped.join(", ")} — ${dropped.length > 1 ? "those parts" : "that part"} will be left out. Switch anyway?`)) {
    $("d3Engine").value = fcMode() ? "freecad" : "picogk";
    return;
  }
  snap(); recipe = r; sel = null; closePop(); paintParts(); changed();
  $("d3Status").textContent = (toFC ? "Now FreeCAD: exact sizes, screw holes, ISO threads, STEP files." : "Now PicoGK: organic shapes, lattices, round printed threads.")
    + (approx.length ? ` (${approx.join("; ")}.)` : "");
};
$("d3Mode").querySelectorAll("button").forEach(b => b.onclick = () => {
  if (b.dataset.t === "built" && !built) return $("d3Status").textContent = "Build it first.";
  setMode(b.dataset.t);
});
function setTool(t) {
  tool = t; drawing = null; marker = null; label = null;
  closePop();
  $("d3Tools").querySelectorAll("[data-tool]").forEach(b => b.classList.toggle("on", b.dataset.tool === t));
  if (mode === "built") setMode("blue");
  status(); viewer?.redraw();
}
const ACTIONS = { copy: copySel, paste, del: removeSel, undo, redo, frame: frameSel,
  mirror: () => { const r = $("d3Mirror").getBoundingClientRect(); mirrorMenu(r.left, r.bottom + 4); } };
$("d3Tools").onclick = e => {
  const b = e.target.closest("button");
  if (!b) return;
  if (b.dataset.tool) setTool(b.dataset.tool); else ACTIONS[b.dataset.act]?.();
};
$("d3Snap").onchange = () => { snapStep = +$("d3Snap").value || 1; };

document.addEventListener("keydown", e => {  // only while Create › 3D is on screen
  if (!document.querySelector(".d3")?.offsetParent) return;
  const typing = e.target.closest?.("input, textarea, select, [contenteditable=true]");
  if (e.key === "Escape") {
    if (pop) closePop(); else if (drag || drawing) editTool.cancel(); else if (tool !== "select") setTool("select"); else if (sel) select(null);
    return;
  }
  if (typing || e.altKey) return;
  const k = e.key.toLowerCase(), ctrl = e.ctrlKey || e.metaKey;
  if (ctrl && k === "z") { e.preventDefault(); if (e.shiftKey) redo(); else undo(); }
  else if (ctrl && k === "y") { e.preventDefault(); redo(); }
  else if (ctrl && k === "c") { if (sel) { e.preventDefault(); copySel(); } }
  else if (ctrl && k === "v") { e.preventDefault(); paste(); }
  else if (ctrl && k === "d") { e.preventDefault(); if (sel) { copySel(); paste(); } }
  else if (k === "delete" || k === "backspace") { if (sel) { e.preventDefault(); removeSel(); } }
  else if (ctrl && k === "a") {  // Ctrl+A: every part of the device
    e.preventDefault();
    const all = recipe.bodies.map((b, i) => ({ kind: "body", body: i }));
    sel = all[0] || null; more = all.slice(1); paintParts(); draw(false); status();
  }
  else if (!ctrl) {
    const t = { v: "select", m: "select", s: "stretch", r: "rotate", h: "hole", d: "dent", t: "thread" }[k];
    if (t) { setTool(t); return; }
    if (k === "f") { frameSel(); return; }
    const step = snapStep * (e.shiftKey ? 10 : 1);
    const d = { arrowleft: [-1, 0, 0], arrowright: [1, 0, 0], arrowup: [0, 1, 0], arrowdown: [0, -1, 0], pageup: [0, 0, 1], pagedown: [0, 0, -1] }[k];
    if (d && sel) { e.preventDefault(); nudge(d.map(x => x * step)); }
  }
});

$("d3Design").onclick = async () => {
  const request = $("d3Ask").value.trim();
  if (!request) return $("d3Ask").focus();
  const b = $("d3Design"), t = Date.now();
  b.disabled = true; b.textContent = "Designing…";
  $("d3Status").textContent = $("d3Agent").value === "small" ? "The small model is designing it (on the processor)…" : "The chat model is designing it…";
  const rid = Math.random().toString(36).slice(2, 12);  // progress bar + Stop while the AI plans it
  const prog = progress3dBox(rid, () => {});
  $("d3Status").after(prog);
  try {
    const r = await api("/api/design", json("POST", { request, agent: $("d3Agent").value, run: rid, engine: fcMode() ? "freecad" : "picogk",
      recipe: $("d3Base").value === "change" && !fresh ? recipe : null }));
    prog.remove();
    if (r.stopped) { $("d3Status").textContent = "Stopped."; return; }
    document.getElementById("d3Plan")?.remove();
    if (r.plan || r.skills?.length) {  // how the AI thought it through (and which skills it used)
      const pl = el("details", "plan", `<summary>📝 The plan${r.skills?.length ? " · 📚 " + esc(r.skills.join(", ")) : ""}</summary>`
        + `<div class="pbody" style="white-space:pre-wrap">${esc(r.plan || "")}</div>`);
      pl.id = "d3Plan"; pl.open = !!r.plan;
      $("d3Status").after(pl);
    }
    if (r.recipe.template && r.recipe.template !== "none") {  // a working design: build it straight away (its parts come back)
      $("d3Status").textContent = `The AI picked the ready-made “${r.recipe.template}” — building it…`;
      return await build(r.recipe, t);
    }
    snap();
    recipe = normalize(r.recipe); cur = 0; fresh = false; sel = null; $("d3Base").value = "change";
    built = null; for (const id of ["d3Download", "d3Step", "d3Send"]) $(id).hidden = true;
    paintParts(); setMode("blue");
    $("d3Status").textContent = `Designed in ${Math.round((Date.now() - t) / 1000)} s — check the blueprint, change anything, then Build.`;
  } catch (e) { $("d3Status").textContent = e.message; }
  finally { prog.remove(); b.disabled = false; b.textContent = "Design it"; }
};

async function build(what, t = Date.now()) {
  const b = $("d3Build"), label0 = b.lastChild.textContent, fc = what.engine === "freecad";
  b.disabled = true; b.lastChild.textContent = "Building…";
  $("d3Status").textContent = `${fc ? "FreeCAD" : "PicoGK"} is building ` + (what.template ? "every part of the design…" : "the design…");
  const rid = Math.random().toString(36).slice(2, 12);  // progress bar + Stop, like pictures and videos
  const prog = progress3dBox(rid, () => {});
  prog.querySelector(".t").textContent = "Starting the 3D engine…";
  $("d3Status").after(prog);
  const send = structuredClone(what);
  if (send.bodies) { delete send.template; delete send.options; }  // the parts as they are now — not the template again
  try {
    const r = await api("/api/design/build", json("POST", { recipe: send, run: rid }));
    if (r.stopped) { $("d3Status").textContent = "Stopped — nothing was built."; return; }
    const m = r.model3d, full = r.full || r.params;
    if (full) {
      recipe = normalize(full); cur = Math.min(cur, recipe.bodies.length - 1); fresh = false; $("d3Base").value = "change";
      if (sel && !itemOf(sel)) sel = null;
      paintParts();
    }
    built = m;
    $("d3Download").href = m.parts ? m.zip : m.stl;
    $("d3Download").download = `${(m.name || "part").replace(/[^\w -]/g, "")}.${m.parts ? "zip" : "stl"}`;
    $("d3Download").textContent = m.parts ? "Download all (zip)" : "Download STL";
    $("d3Download").hidden = false;
    $("d3Step").hidden = !m.step;
    if (m.step) { $("d3Step").href = m.step; $("d3Step").download = `${(m.name || "part").replace(/[^\w -]/g, "")}.step`; }
    $("d3Send").hidden = !origin;
    setMode("built");
    const fit = m.parts ? (m.collisions?.length ? ` · ⚠ ${m.collisions.length} collision(s)` : " · ✓ nothing collides") : "";
    $("d3Status").textContent = `Built in ${Math.round((Date.now() - t) / 1000)} s · ${(m.size_mm || []).map(Math.round).join(" × ")} mm`
      + `${m.parts ? ` · ${m.parts.length} parts` : ` · ${Number(m.triangles).toLocaleString()} triangles`}${fit} · saved in Gallery › 3D`
      + (origin ? " · “Send to chat” puts it back in the chat." : ".") + (m.notes ? ` ${m.notes}` : "");
  } catch (e) { $("d3Status").textContent = "It didn't work: " + e.message; }
  finally { prog.remove(); b.disabled = false; b.lastChild.textContent = label0; }
}
$("d3Build").onclick = () => build({ ...recipe, name: recipe.name || body().name });
$("d3Tpl").onchange = async () => {
  const tpl = $("d3Tpl").value, lbl = $("d3Tpl").selectedOptions?.[0]?.textContent || tpl;
  if (!tpl) return;
  $("d3Tpl").value = "";
  snap();
  await build({ name: lbl.replace(/ \(.*\)$/, ""), template: tpl, options: {}, ...(fcMode() ? { engine: "freecad" } : {}) });
};
async function sendToChat() {  // the changed model goes back into the chat it came from (built first if needed)
  if (!origin) return;
  if (!built) {
    await build({ ...recipe, name: recipe.name || body().name });
    if (!built) return;
  }
  try {
    await api(`/api/chats/${origin}/model3d`, json("POST", { model3d: built, recipe }));
    chatOverlay(false);
    show("chat");
    await openChat(origin);
  } catch (e) { $("d3Status").textContent = "Couldn't send it to the chat: " + e.message; }
}
$("d3Send").onclick = sendToChat;
$("d3Print").onclick = () => printIt(sel?.kind === "body" && recipe.bodies.length > 1 ? sel.body : null);

// ---------------------------------------------------------------- right-click menu, turn 90°, save the files
function editMenu(p, e) {
  closePop();
  const h = mode === "blue" && viewer ? viewer.pick(p[0], p[1], any) : null;
  if (h && !inSel(h.mesh.ref)) select(h.mesh.ref, true);
  const it = itemOf(sel), whole = sel?.kind === "body", many = recipe.bodies.length > 1, b = sel ? recipe.bodies[sel.body] : null;
  popMenu(e.clientX, e.clientY, [
    { label: whole ? "Copy the whole part" : "Copy", key: "Ctrl+C", act: copySel, disabled: !it },
    { label: "Paste", key: "Ctrl+V", act: paste, disabled: !clip },
    { label: "Duplicate", key: "Ctrl+D", act: () => { copySel(); paste(); }, disabled: !it },
    { label: more.length ? `Delete the ${selAll().length} selected` : whole ? "Delete the whole part" : "Delete", key: "Del", act: removeSel, disabled: !it, danger: true },
    { sep: true },
    ...[0, 1, 2].map(k => ({ label: `Turn 90° around ${"XYZ"[k]}`, act: () => turn90(k), disabled: !it })),
    { sep: true },
    ...MIRROR.map(([a, w], k) => ({ label: `Mirror copy ${a} ${w}${it ? "" : " (whole design)"}`, act: () => mirrorSel(k, true) })),
    { label: "Flip in place…", act: () => mirrorMenu(e.clientX, e.clientY, true) },
    { sep: true },
    ...(h ? [whole ? { label: "Pick just this shape", act: () => select(h.mesh.ref) }
      : { label: "Select the whole part", key: "double-click", act: () => select({ kind: "body", body: h.mesh.ref.body }) }] : []),
    { label: it ? "Look at it" : "Look at everything", key: "F", act: frameSel },
    { sep: true },
    { label: "Undo", key: "Ctrl+Z", act: undo, disabled: !hist.length },
    { label: "Redo", key: "Ctrl+Y", act: redo, disabled: !fut.length },
    { sep: true },
    { label: "🖨 Print — G-code for my printer…", act: () => printIt(many && b ? sel.body : null) },
    { sep: true },
    ...(many && b ? [{ label: `Save “${b.name || "part"}” (STL)`, act: () => saveFile("stl", sel.body) }] : []),
    { label: many ? "Save all parts (zip)" : "Save STL (to print)", act: () => saveFile(many ? "zip" : "stl") },
    ...(fcMode() ? [{ label: "Save STEP (CAD)", act: () => saveFile("step") }] : []),
  ]);
}
function turn90(k) {
  const it = itemOf(sel);
  if (!it) return;
  const ms = meshes.filter(x => inSel(x.ref)), bb = ms.length ? boxOf(ms) : sel.kind === "body" ? bodyBox(it) : partBox(it, fcMode());
  const P = sel.kind === "hole" && !more.length ? it.at : bb.lo.map((x, j) => (x + bb.hi[j]) / 2);  // several: around their middle
  snap();
  for (const x of selAll()) setItem(x, turned(itemOf(x), x.kind, k, 90, P));
  paintParts(); changed(); status();
  hint(`Turned 90° around ${"XYZ"[k]} — Ctrl+Z puts it back.`);
}
async function cutToFit() {  // ✂ the design in pieces that fit the printer (built first), then the print window for them
  if (!built) {
    hint("Building it first…");
    await build({ ...recipe, name: recipe.name || body().name });
    if (!built) return;
  }
  const b = $("d3CutFit");
  b.disabled = true; b.textContent = "✂ Cutting…";
  try {
    const r = await api("/api/model3d/cut", json("POST", { model: built }));
    if (r.fits) hint("It already fits your printer.");
    else { hint(`Cut into ${r.pieces} pieces that fit — saved in the Gallery. ${r.notes || ""}`); openPrint(r.model3d, {}); }
  } catch (e) { hint("⚠ " + e.message); }
  finally { b.disabled = false; b.textContent = "✂ Cut to fit"; }
}
$("d3CutFit")?.addEventListener("click", cutToFit);
async function printIt(which) {  // the print window for what's built (built first when the design changed)
  if (!built) {
    hint("Building it first…");
    await build({ ...recipe, name: recipe.name || body().name });
    if (!built) return;
  }
  let part = null;
  if (built.parts && which != null) {
    const b = recipe.bodies[which], i = built.parts.findIndex(x => x.name === b?.name);
    part = i >= 0 ? i : which;
  }
  openPrint(built, part != null ? { part } : {});
}
async function saveFile(kind, which) {  // "Save …" = the built file (built first when the design changed)
  if (!built) {
    hint("Building it first…");
    await build({ ...recipe, name: recipe.name || body().name });
    if (!built) return;
  }
  const nm = String(built.name || "model").replace(/[^\w -]/g, "").trim() || "model";
  if (kind === "step") return built.step ? download(built.step, nm + ".step") : hint("STEP files come from FreeCAD designs (Engine: FreeCAD).");
  if (built.parts && which != null) {
    const b = recipe.bodies[which], pt = built.parts.find(x => x.name === b?.name) || built.parts[which];
    if (pt) return download(pt.stl, (String(pt.name || nm).replace(/[^\w -]/g, "").trim() || nm) + ".stl");
  }
  if (built.parts) return download(built.zip, nm + ".zip");
  download(built.stl, nm + ".stl");
}

// ---------------------------------------------------------------- "Edit in 3D" from a chat: this editor over the chat
let ovEl = null;
function chatOverlay(on, title) {
  const d3 = document.querySelector(".d3");
  if (on) {
    if (!ovEl) {
      ovEl = el("div", "d3ov");
      ovEl.innerHTML = `<div class="d3ovhead"><b class="ovt"></b><span class="muted small grow">— change it, then Send to chat (or just close)</span></div><div class="d3ovbody"></div>`;
      const head = ovEl.querySelector(".d3ovhead");
      head.append(button("Send to chat", "sm primary", sendToChat), button("✕ Close", "sm", () => chatOverlay(false)));
      document.body.append(ovEl);
    }
    ovEl.querySelector(".ovt").textContent = title || "Editing in 3D";
    ovEl.querySelector(".d3ovbody").append(d3);
    ovEl.hidden = false;
  } else if (ovEl && !ovEl.hidden) {
    closePop(); closeMenu();
    $("c-model").append(d3);
    ovEl.hidden = true;
  }
}

// "Build it myself in Create › 3D" (a choice button after a design the AI couldn't make): the words come along
window.addEventListener("open3dask", e => {
  show("create");
  document.querySelector('#createTabs [data-t="model"]').click();
  $("d3Ask").value = e.detail || "";
  $("d3Base").value = "new";
  $("d3Status").textContent = "Build it from parts (+ Add part), or describe it more simply and press Design it.";
});

// "Edit in 3D" from a chat answer ({recipe, fromChat}) or the Gallery ({recipe})
window.addEventListener("edit3d", async e => {
  const d = e.detail || {}, from = d.fromChat ? currentChat() : null;
  let r = d.recipe !== undefined ? d.recipe : d;
  if (from) chatOverlay(true, `Editing “${r?.name || "3D model"}”`);  // you stay in the chat
  else {
    chatOverlay(false);
    show("create");
    document.querySelector('#createTabs [data-t="model"]').click();
  }
  if (r && r.template && !r.bodies && !r.parts) {  // a ready-made design saved short: its parts first
    $("d3Status").textContent = "Opening the design…";
    try { r = (await api("/api/design/expand", json("POST", { recipe: r }))).recipe; }
    catch (err) { $("d3Status").textContent = err.message; return; }
  }
  open3d(r);
  origin = from;
  if (d.part != null && recipe.bodies[d.part]) select({ kind: "body", body: d.part });  // right-clicked on that part
  $("d3Status").textContent = "Click a part or a hole to change it (right-click = menu) — or use Hole / Dent / Thread. Then Build"
    + (origin ? ", and “Send to chat” puts it back in the chat." : ".");
});
