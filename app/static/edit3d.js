// Create › 3D editing helpers (no page state, no DOM): what a typed / spoken hole means, where a part's stretch
// handles are and what dragging them does, moving, dents, and turning a PicoGK design into a FreeCAD one (and back).
import { CLEARANCE, SCREWS, across, partTris, rot, v3 } from "./viewer3d.js";

const { add, sub, dot, cross, unit } = v3;
const D2R = Math.PI / 180;
const AXV = { x: [1, 0, 0], y: [0, 1, 0], z: [0, 0, 1] };
const r3 = x => Math.round(x * 1000) / 1000 + 0;  // + 0: no "-0" in the design
const r3v = v => v.map(r3);
export const fmt = x => String(Math.round((+x || 0) * 100) / 100);

/** The turn [x, y, 0] (degrees) that points a part's up (Z) along the unit direction D. */
export function aim(D) {
  const a = -Math.asin(Math.max(-1, Math.min(1, D[1]))) / D2R;
  const b = Math.abs(D[1]) < 1 - 1e-9 ? Math.atan2(D[0], D[2]) / D2R : 0;
  return [r3(a), r3(b), 0];
}

// turns as 3x3 matrices (rows), X first, then Y, then Z — like the engines
export function rotMat(deg = [0, 0, 0]) {
  const [a, b, c] = deg.map(d => (+d || 0) * D2R), [ca, sa, cb, sb, cc, sc] = [Math.cos(a), Math.sin(a), Math.cos(b), Math.sin(b), Math.cos(c), Math.sin(c)];
  return matMul([[cc, -sc, 0], [sc, cc, 0], [0, 0, 1]], matMul([[cb, 0, sb], [0, 1, 0], [-sb, 0, cb]], [[1, 0, 0], [0, ca, -sa], [0, sa, ca]]));
}
export const matMul = (A, B) => A.map(row => [0, 1, 2].map(j => row[0] * B[0][j] + row[1] * B[1][j] + row[2] * B[2][j]));
export function matDeg(M) {
  const b = Math.asin(Math.max(-1, Math.min(1, -M[2][0])));
  if (Math.abs(M[2][0]) > 0.99999) return [0, r3(b / D2R), r3(Math.atan2(-M[0][1], M[1][1]) / D2R)];
  return [r3(Math.atan2(M[2][1], M[2][2]) / D2R), r3(b / D2R), r3(Math.atan2(M[1][0], M[0][0]) / D2R)];
}

/** Where along the line A + t·a the pointer's ray passes closest (null: the ray runs along it). */
export function lineParam(A, a, r) {
  const w0 = sub(A, r.o), b = dot(a, r.d), d = dot(a, w0), e = dot(r.d, w0), c = dot(r.d, r.d), den = dot(a, a) * c - b * b;
  return Math.abs(den) < 1e-9 ? null : (b * e - c * d) / den;
}
/** Where the pointer's ray meets the plane through P0 with normal n (null: it runs along the plane). */
export function rayPlane(r, P0, n) {
  const den = dot(r.d, n);
  return Math.abs(den) < 1e-6 ? null : add(r.o, r.d, dot(sub(P0, r.o), n) / den);
}

/** A part / hole moved by d. */
export function moved(q, d, kind) {
  if (kind === "body") return { ...q, parts: (q.parts || []).map(p => moved(p, d, "part")), ...(q.holes ? { holes: q.holes.map(h => moved(h, d, "hole")) } : {}) };
  if (kind === "hole") return { ...q, at: r3v(add(q.at || [0, 0, 0], d)) };
  if (q.shape === "rod") return { ...q, from: r3v(add(q.from || [0, 0, 0], d)), to: r3v(add(q.to || [0, 0, 20], d)) };
  if (q.shape === "curved_pipe") return { ...q, points: (q.points || []).map(pt => r3v(add(pt, d))) };
  return { ...q, center: r3v(add(q.center || [0, 0, 0], d)) };
}

const mv = (M, v) => [0, 1, 2].map(i => M[i][0] * v[0] + M[i][1] * v[1] + M[i][2] * v[2]);
const around = (M, p, P) => add(P, mv(M, sub(p, P)));
/** A part / hole / whole body turned by deg around the world axis k (0 = X, 1 = Y, 2 = Z) through the point P:
 * its place swings around P and its own turn adds up (holes: their drilling direction turns too). */
export function turned(q, kind, k, deg, P) {
  const d = [0, 0, 0];
  d[k] = deg;
  const M = rotMat(d);
  if (kind === "body") return { ...q, parts: (q.parts || []).map(p => turned(p, "part", k, deg, P)), ...(q.holes ? { holes: q.holes.map(h => turned(h, "hole", k, deg, P)) } : {}) };
  if (kind === "hole") return { ...q, at: r3v(around(M, q.at || [0, 0, 0], P)), dir: r3v(unit(mv(M, q.dir || [0, 0, -1]))) };
  if (q.shape === "rod") return { ...q, from: r3v(around(M, q.from || [0, 0, 0], P)), to: r3v(around(M, q.to || [0, 0, 20], P)) };
  if (q.shape === "curved_pipe") return { ...q, points: (q.points || []).map(pt => r3v(around(M, pt, P))) };
  const out = { ...q, center: r3v(around(M, q.center || [0, 0, 0], P)), rotate: matDeg(matMul(M, rotMat(q.rotate || [0, 0, 0]))) };
  if (q.repeat) out.repeat = { ...q.repeat, axis_point: r3v(around(M, q.repeat.axis_point || [0, 0, 0], P)), ...(q.repeat.step ? { step: r3v(mv(M, q.repeat.step)) } : {}) };
  return out;
}

/** A part / hole / whole body mirrored across the plane through P square to the world axis k (0 = X: left <-> right,
 * 1 = Y: front <-> back, 2 = Z: up <-> down): a left hand from a right hand. A mirror isn't a turn, so a shape gets the
 * turn S·R·D, where D flips it across one of its own planes of symmetry (boxes, cylinders, cones, tubes, gears, spheres
 * are symmetric; an outline's points are flipped instead). Springs and threads keep their hand (bought / standard). */
export function mirrored(q, kind, k, P, fc) {
  const S = [[1, 0, 0], [0, 1, 0], [0, 0, 1]];
  S[k][k] = -1;
  const ref = p => r3v(add(P, mv(S, sub(p, P))));
  if (kind === "body") return { ...q, parts: (q.parts || []).map(p => mirrored(p, "part", k, P, fc)), ...(q.holes ? { holes: q.holes.map(h => mirrored(h, "hole", k, P, fc)) } : {}) };
  if (kind === "hole") return { ...q, at: ref(q.at || [0, 0, 0]), dir: r3v(unit(mv(S, q.dir || [0, 0, -1]))) };
  if (q.shape === "rod") return { ...q, from: ref(q.from || [0, 0, 0]), to: ref(q.to || [0, 0, 20]) };
  if (q.shape === "curved_pipe") return { ...q, points: (q.points || []).map(ref) };
  const flipY = fc && q.axis === "x" && ["cylinder", "cone", "tube"].includes(q.shape);  // flip across a plane its axis lies in
  const D = flipY ? [[1, 0, 0], [0, -1, 0], [0, 0, 1]] : [[-1, 0, 0], [0, 1, 0], [0, 0, 1]];
  const out = { ...q, center: ref(q.center || [0, 0, 0]), rotate: matDeg(matMul(matMul(S, rotMat(q.rotate || [0, 0, 0])), D)) };
  if (Array.isArray(q.points) && ["extrude", "polygon"].includes(q.shape))  // the outline flipped (reversed: same winding)
    out.points = q.points.map(([x, y, ...r]) => (flipY ? [x, r3(-y), ...r] : [r3(-x), y, ...r])).reverse();
  if (q.repeat) {
    const rep = { ...q.repeat };
    if (rep.step && rep.step.some(x => +x)) rep.step = r3v(mv(S, rep.step));
    else {
      rep.axis_point = ref(rep.axis_point || [0, 0, 0]);
      const a = +(rep.angle ?? 360);
      if (k !== 2 && Math.abs(Math.abs(a) - 360) > 0.01) rep.angle = r3(-a);  // copies around Z now go the other way
    }
    out.repeat = rep;
  }
  return out;
}

/** The square handles of a part (Stretch): where each sits, which way is "out", what dragging it by d does (the
 * opposite side stays where it is), and a label for the size it gives. Shapes without handles can only be moved. */
export function handlesFor(p, fc) {
  const c = p.center || [0, 0, 0], T = v => rot(v, p.rotate), H = [], s = p.shape;
  const mk = (id, pos, dir, apply, what) => H.push({ id, pos, dir: unit(dir), apply, what });
  const box = s === "box" || (!fc && ["lattice", "gyroid", "tpms"].includes(s));
  if (box) {
    const size = (p.size || [20, 20, 20]).map(v => Math.abs(+v || 20));
    for (let k = 0; k < 3; k++) for (const sg of [1, -1]) {
      const e = [0, 0, 0];
      e[k] = sg;
      const out = T(e);
      mk(`s${k}${sg}`, add(c, out, size[k] / 2), out, (q0, d) => {
        const sz = (q0.size || [20, 20, 20]).map(v => Math.abs(+v || 20)), n = Math.max(0.2, sz[k] + d), dd = n - sz[k];
        sz[k] = r3(n);
        return { ...q0, size: sz, center: r3v(add(q0.center || [0, 0, 0], out, dd / 2)) };
      }, q => `${"XYZ"[k]} size ${fmt(q.size[k])} mm`);
    }
    return H;
  }
  const lathe = ["cylinder", "cone", "tube"].includes(s);
  if (lathe || (!fc && ["gear", "extrude", "helix"].includes(s)) || (fc && s === "polygon")) {
    const h = +p.height || (fc ? 10 : 20), a = T(fc && lathe ? AXV[p.axis] || AXV.z : AXV.z);
    const lo = fc ? -h / 2 : 0, hi = fc ? h / 2 : h;  // FreeCAD: on its center; PicoGK: from its center up
    const height = (q0, d) => { const h0 = +q0.height || h, n = Math.max(0.2, h0 + d); return [r3(n), n - h0]; };
    mk("top", add(c, a, hi), a, (q0, d) => {
      const [n, dd] = height(q0, d);
      return { ...q0, height: n, center: fc ? r3v(add(q0.center || c, a, dd / 2)) : q0.center };
    }, q => `height ${fmt(q.height)} mm`);
    mk("bottom", add(c, a, lo), a.map(v => -v), (q0, d) => {
      const [n, dd] = height(q0, d);
      return { ...q0, height: n, center: r3v(add(q0.center || c, a, fc ? -dd / 2 : -dd)) };
    }, q => `height ${fmt(q.height)} mm`);
    if (lathe) {
      const [u] = across(a), r = +p.radius || 10, mid = add(c, a, (lo + hi) / 2);
      mk("radius", add(mid, u, r), u, (q0, d) => {
        const n = Math.max(0.1, (+q0.radius || 10) + d), q = { ...q0, radius: r3(n) };
        if (s === "tube") q.wall = r3(Math.min(+q0.wall || 2, n - 0.05));
        return q;
      }, q => `Ø ${fmt(2 * q.radius)} mm`);
      if (s === "cone") {
        const r2 = +(p.radius2 ?? (fc ? 0 : r * 0.5));
        mk("radius2", add(add(c, a, hi), u, r2), u, (q0, d) => ({ ...q0, radius2: r3(Math.max(0, +(q0.radius2 ?? r2) + d)) }),
          q => `top Ø ${fmt(2 * q.radius2)} mm`);
      }
    }
    return H;
  }
  if (s === "sphere") {
    mk("radius", add(c, [1, 0, 0], +p.radius || 10), [1, 0, 0], (q0, d) => ({ ...q0, radius: r3(Math.max(0.1, (+q0.radius || 10) + d)) }),
      q => `Ø ${fmt(2 * q.radius)} mm`);
    return H;
  }
  if (fc && s === "slot") {
    const L = +p.length || 20, W = +p.width || 4, Hh = +p.height || 5, ax = p.axis || "z";
    const dx = p.direction && p.direction !== ax ? p.direction : (ax === "x" ? "y" : "x");
    const X = T(AXV[dx]), Z = T(AXV[ax]), Y = cross(Z, X);
    for (const sg of [1, -1]) mk(`len${sg}`, add(c, X, sg * L / 2), X.map(v => v * sg), (q0, d) => {
      const w = +q0.width || W, l0 = +q0.length || L, n = Math.max(w, l0 + d);
      return { ...q0, length: r3(n), center: r3v(add(q0.center || c, X, sg * (n - l0) / 2)) };
    }, q => `length ${fmt(q.length)} mm`);
    mk("width", add(c, Y, W / 2), Y, (q0, d) => {
      const w0 = +q0.width || W, n = Math.max(0.2, w0 + d);
      return { ...q0, width: r3(n), length: r3(Math.max(+q0.length || L, n)), center: r3v(add(q0.center || c, Y, (n - w0) / 2)) };
    }, q => `width ${fmt(q.width)} mm`);
    for (const sg of [1, -1]) mk(`dep${sg}`, add(c, Z, sg * Hh / 2), Z.map(v => v * sg), (q0, d) => {
      const h0 = +q0.height || Hh, n = Math.max(0.2, h0 + d);
      return { ...q0, height: r3(n), center: r3v(add(q0.center || c, Z, sg * (n - h0) / 2)) };
    }, q => `depth ${fmt(q.height)} mm`);
    return H;
  }
  if (!fc && s === "torus") {
    const r = +p.radius || 10, r2 = +(p.radius2 ?? 4), out = T([1, 0, 0]);
    mk("radius", add(c, out, r + r2), out, (q0, d) => ({ ...q0, radius: r3(Math.max(0.1, (+q0.radius || 10) + d)) }), q => `ring Ø ${fmt(2 * q.radius)} mm`);
    return H;
  }
  if (!fc && s === "rod") {
    const A = p.from || [0, 0, 0], B = p.to || [0, 0, +p.height || 20], w = unit(sub(B, A)), L = Math.hypot(...sub(B, A));
    mk("to", B, w, (q0, d) => ({ ...q0, to: r3v(add(q0.to || B, w, Math.max(d, 0.5 - L))) }), q => `length ${fmt(Math.hypot(...sub(q.to, q.from || A)))} mm`);
    mk("from", A, w.map(v => -v), (q0, d) => ({ ...q0, from: r3v(add(q0.from || A, w, -Math.max(d, 0.5 - L))) }), q => `length ${fmt(Math.hypot(...sub(q.to || B, q.from)))} mm`);
    const [u] = across(w);
    mk("radius", add(add(A, w, L / 2), u, +p.radius || 2), u, (q0, d) => ({ ...q0, radius: r3(Math.max(0.1, (+q0.radius || 2) + d)) }), q => `Ø ${fmt(2 * q.radius)} mm`);
  }
  return H;
}

/** A dent pressed into a surface at `at` (outward normal n): round, square or a finger dimple, w wide, depth deep. */
export function dentPart(at, n, shape, w, depth, fc) {
  const D = unit(n.map(v => -v)), op = fc ? "cut" : "subtract", turn = aim(D);
  w = Math.max(0.5, +w || 10); depth = Math.max(0.2, +depth || 2);
  if (shape === "dimple") {  // a sphere cap: w across at the surface, depth deep
    const R = (w * w / 4 + depth * depth) / (2 * depth);
    return { op, shape: "sphere", radius: r3(R), center: r3v(add(at, D, depth - R)), rotate: [0, 0, 0] };
  }
  if (shape === "square") return { op, shape: "box", size: [r3(w), r3(w), r3(depth + 1)], rotate: turn, center: r3v(add(at, D, (depth - 1) / 2)) };
  return fc ? { op, shape: "cylinder", axis: "z", radius: r3(w / 2), height: r3(depth + 1), rotate: turn, center: r3v(add(at, D, (depth - 1) / 2)) }
    : { op, shape: "cylinder", radius: r3(w / 2), height: r3(depth + 1), rotate: turn, center: r3v(add(at, D, -1)) };
}

/** The M size whose loose (clearance) hole is this wide, ±0.3 mm — for a circle you drew. */
export function screwFor(d) {
  let best = null;
  for (const s of SCREWS) if (Math.abs(CLEARANCE[s] - d) <= 0.3 && (!best || Math.abs(CLEARANCE[s] - d) < Math.abs(CLEARANCE[best] - d))) best = s;
  return best;
}

/** What a typed or spoken hole / dent means: "M3 countersunk", "2 cm hole", "M4 insert 8 mm deep", "a finger dent". */
export function parseSay(text) {
  let t = ` ${String(text || "").toLowerCase().replace(/(\d),(\d)/g, "$1.$2")} `;
  const o = {}, N = "(\\d+(?:\\.\\d+)?)", U = "\\s*(mm|cm|inch|inches|in|\")?";
  const len = (n, u) => +n * (u === "cm" ? 10 : u === "in" || u === '"' || (u || "").startsWith("inch") ? 25.4 : 1);
  let m = t.match(new RegExp(`${N}${U}\\s*(?:deep|depth|adanc|adânc)(?![a-zăâîșțţş]*itur)`)) ||
    t.match(new RegExp(`(?:depth|deep|adancime|adâncime)\\s*(?:of\\s*|de\\s*)?${N}${U}`));
  if (m) { o.depth = len(m[1], m[2]); t = t.replace(m[0], " "); }
  if (/\b(through|thru|all the way|str[aă]pun\w*|de tot|prin tot)\b/.test(t)) o.depth = 0;
  m = t.match(/\bm\s?(2\.5|10|2|3|4|5|6|8)\b(?!\s*(mm|cm|\.\d))/);
  if (m) o.for = "M" + m[1];
  m = t.match(new RegExp(`(?:radius|raza|rază)\\s*(?:of\\s*|de\\s*)?${N}${U}`));
  if (m) o.diameter = 2 * len(m[1], m[2]);
  else {
    m = t.match(new RegExp(`(?:ø|⌀|diameter|diametru|diam|dia)\\s*(?:of\\s*|de\\s*)?${N}${U}`)) ||
      t.match(new RegExp(`${N}\\s*(mm|cm|inches|inch|in|")(?![a-z])`)) || t.match(new RegExp(`(?:^|\\s)${N}\\s*(?=(?:hole|gaur|g[aă]ur|dent|wide|lat))`));
    if (m && !o.for) o.diameter = len(m[1], m[2]);
  }
  if (/\b(heat[- ]?set|inserts?|inser[tț]\w*)\b/.test(t)) o.fit = "insert";
  else if (/\b(nuts?|piuli[tț]\w*)\b/.test(t)) o.fit = "nut";
  else if (/\b(self[- ]?tap\w*|tap|tapped|cuts? (?:its|their)? ?own|autofilet\w*|wood screws?)\b/.test(t)) o.fit = "tap";
  else if (/\b(thread\w*|filet\w*)\b/.test(t)) o.fit = "thread";
  else if (/\b(clearance|loose|goes through|liber)\b/.test(t)) o.fit = "clearance";
  if (/\b(counter ?sunk|counter ?sink|flat[- ]?head|[iî]necat\w*)/.test(t)) o.head = "countersink";
  else if (/\b(counter ?bore\w*|socket[- ]?head|cap cilindric|allen)\b/.test(t)) o.head = "counterbore";
  else if (/\b(no head|plain|fara cap|fără cap)\b/.test(t)) o.head = "";
  if (/\b(dents?|dimples?|recess\w*|pockets?|indent\w*|ad[aâ]nc[iî]tur\w*|scobitur\w*|l[aă]ca[sș]\w*|groap\w*)/.test(t)) o.dent = true;
  if (/\b(square|squared|p[aă]trat\w*|rectang\w*)/.test(t)) o.shape = "square";
  else if (/\b(dimple|finger|deget\w*|spher\w*|grip)/.test(t)) o.shape = "dimple";
  else if (/\b(round|circle|cerc|rotund\w*)/.test(t)) o.shape = "round";
  return o;
}

// ---------- PicoGK <-> FreeCAD: the shapes both have (the others are left out, and listed)
function copiesOf(p) {  // PicoGK's "repeat" (around / in a row) as separate parts: FreeCAD has no repeat
  const rep = p.repeat, n = Math.min(Math.max(Math.round(+rep?.count || 1), 1), 60);
  if (n === 1) return [{ ...p }];
  const out = [], step = rep.step, piv = rep.axis_point || [0, 0, 0], total = +(rep.angle ?? 360);
  for (let k = 0; k < n; k++) {
    const q = { ...p };
    delete q.repeat;
    if (step && step.some(x => +x)) { q.center = r3v(add(p.center || [0, 0, 0], step, k)); out.push(q); continue; }
    const a = total * k / (Math.abs(total - 360) < 0.01 ? n : Math.max(n - 1, 1));
    q.center = r3v(add(rot(sub(p.center || [0, 0, 0], piv), [0, 0, a]), piv));
    q.rotate = [+(p.rotate || [])[0] || 0, +(p.rotate || [])[1] || 0, r3((+(p.rotate || [])[2] || 0) + a)];
    out.push(q);
  }
  return out;
}
function toFreeCAD(p0) {
  const out = [];
  for (const p of copiesOf(p0)) {
    const op = p.op === "subtract" ? "cut" : p.op === "intersect" ? "intersect" : "add", c = p.center || [0, 0, 0];
    const turn = p.rotate || [0, 0, 0], h = +p.height || 20, mid = add(c, rot([0, 0, h / 2], turn));  // PicoGK starts at center
    const base = { op, rotate: r3v(turn) };
    if (p.shape === "box") out.push({ ...base, shape: "box", center: r3v(c), size: p.size || [20, 20, 20], ...(p.round ? { round: p.round } : {}) });
    else if (p.shape === "sphere") out.push({ ...base, shape: "sphere", center: r3v(c), radius: +p.radius || 10 });
    else if (p.shape === "cylinder") out.push({ ...base, shape: "cylinder", axis: "z", center: r3v(mid), radius: +p.radius || 10, height: h, ...(p.thread ? { thread: p.thread } : {}) });
    else if (p.shape === "cone") out.push({ ...base, shape: "cone", axis: "z", center: r3v(mid), radius: +p.radius || 10, radius2: +(p.radius2 ?? (+p.radius || 10) * 0.5), height: h });
    else if (p.shape === "tube") out.push({ ...base, shape: "tube", axis: "z", center: r3v(mid), radius: +p.radius || 10, wall: +p.wall || 2, height: h });
    else if (p.shape === "extrude" && (p.points || []).length >= 3) out.push({ ...base, shape: "polygon", points: p.points, height: h, center: r3v(mid) });
    else if (p.shape === "rod") {
      const A = p.from || [0, 0, 0], B = p.to || [0, 0, h], L = Math.hypot(...sub(B, A)) || 1;
      out.push({ op, shape: "cylinder", axis: "z", radius: +p.radius || 2, height: r3(L), center: r3v(add(A, sub(B, A), 0.5)), rotate: aim(unit(sub(B, A))) });
    } else return null;
  }
  return out;
}
function toPicoGK(p) {
  const op = p.op === "cut" ? "subtract" : p.op === "intersect" ? "intersect" : "add", c = p.center || [0, 0, 0], turn = p.rotate || [0, 0, 0];
  const lathe = ["cylinder", "cone", "tube"].includes(p.shape), h = +p.height || 10;
  const deg = lathe && p.axis && p.axis !== "z" ? matDeg(matMul(rotMat(turn), rotMat(p.axis === "x" ? [0, 90, 0] : [-90, 0, 0]))) : r3v(turn);
  const start = r3v(sub(c, rot([0, 0, h / 2], deg)));  // PicoGK: from its center up
  switch (p.shape) {
    case "box": return [{ op, shape: "box", center: r3v(c), size: p.size || [20, 20, 20], rotate: deg, ...(p.round ? { round: p.round } : {}) }];
    case "sphere": return [{ op, shape: "sphere", center: r3v(c), radius: +p.radius || 10 }];
    case "cylinder": return [{ op, shape: "cylinder", center: start, radius: +p.radius || 10, height: h, rotate: deg, ...(p.thread ? { thread: p.thread } : {}) }];
    case "cone": return [{ op, shape: "cone", center: start, radius: +p.radius || 10, radius2: Math.max(+p.radius2 || 0, 0.05), height: h, rotate: deg }];
    case "tube": return [{ op, shape: "tube", center: start, radius: +p.radius || 10, wall: +p.wall || 2, height: h, rotate: deg }];
    case "polygon": return [{ op, shape: "extrude", points: p.points, height: h, center: start, rotate: deg }];
    case "slot": {  // a stadium -> a box as long and wide (PicoGK has no slot)
      const ax = p.axis || "z", dx = p.direction && p.direction !== ax ? p.direction : (ax === "x" ? "y" : "x");
      const X = AXV[dx], Z = AXV[ax], Y = cross(Z, X), F = [[X[0], Y[0], Z[0]], [X[1], Y[1], Z[1]], [X[2], Y[2], Z[2]]];
      return [{ op, shape: "box", center: r3v(c), size: [+p.length || 20, +p.width || 4, +p.height || 5], rotate: matDeg(matMul(rotMat(turn), F)) }];
    }
    default: return null;
  }
}
/** The design in the other engine: {recipe, dropped: shapes it doesn't have, changed: what became something close}. */
export function convert(recipe, toFC) {
  const r = structuredClone(recipe), dropped = new Set(), changed = new Set();
  for (const b of r.bodies || []) {
    const parts = [];
    for (const p of b.parts || []) {
      const q = toFC ? toFreeCAD(p) : toPicoGK(p);
      if (!q) { dropped.add(p.shape); continue; }
      if (toFC && p.repeat) changed.add("repeated parts became separate parts");
      if (!toFC && p.shape === "slot") changed.add("slots became boxes");
      if (p.shape === "rod") changed.add("rods became cylinders");
      parts.push(...q);
    }
    if (parts[0]) parts[0].op = "add";
    b.parts = parts.length ? parts : [toFC ? { op: "add", shape: "box", center: [0, 0, 10], size: [40, 30, 20] } : { op: "add", shape: "box", center: [0, 0, 15], size: [30, 30, 30] }];
    for (const k of toFC ? ["hollow", "smooth"] : ["fillet", "fillet_edges", "chamfer", "chamfer_edges", "shell", "shell_open"]) {
      if (b[k]) changed.add(toFC ? "hollow / smooth settings were dropped" : "round edges / chamfer / hollow settings were dropped");
      delete b[k];
    }
  }
  if (toFC) r.engine = "freecad"; else delete r.engine;
  delete r.template; delete r.options; delete r.voxel;
  return { recipe: r, dropped: [...dropped], changed: [...changed] };
}

/** A part's box (for the paste offset and "look at it"). */
export function partBox(p, fc) {
  const t = partTris(p, fc), lo = [Infinity, Infinity, Infinity], hi = [-Infinity, -Infinity, -Infinity];
  for (let i = 0; i < t.length; i++) { const k = i % 3; if (t[i] < lo[k]) lo[k] = t[i]; if (t[i] > hi[k]) hi[k] = t[i]; }
  return t.length ? { lo, hi } : { lo: [0, 0, 0], hi: [0, 0, 0] };
}
