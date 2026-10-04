// 3D viewer (plain WebGL — no downloads): STL files, and "blueprints" of a design before it's built.
// Mouse: drag to turn, right-drag (or Shift-drag) to move the view, wheel to zoom towards the pointer, double-click to
// reset, right-CLICK = a menu (tool.menu). Touch / pen: one finger turns, two fingers zoom and move, a long press = the
// menu. Z is up (like PicoGK). Create › 3D adds picking (pick), arrows / handles drawn on top (setOverlay) and tools.
const VS = `attribute vec3 p; attribute vec3 n; uniform mat4 m; uniform mat4 r; uniform vec3 o; varying vec3 vn;
void main() { vn = (r * vec4(n, 0.0)).xyz; gl_Position = m * vec4(p + o, 1.0); }`;
const FS = `precision mediump float; varying vec3 vn; uniform vec4 c;
void main() { float d = abs(dot(normalize(vn), normalize(vec3(-0.4, 0.6, 0.7))));
  gl_FragColor = vec4(c.rgb * (0.32 + 0.68 * d), c.a); }`;
export const COLORS = { add: [0.29, 0.84, 0.59, 1], subtract: [0.95, 0.35, 0.35, 0.35], intersect: [0.4, 0.6, 1, 0.3],
  pattern: [0.29, 0.84, 0.59, 0.55] };
export const SEL = [1, 0.8, 0.2];  // the selected part / hole in Create › 3D

// 4x4 matrices, column-major (as WebGL wants them)
const mul = (a, b) => {
  const o = new Float32Array(16);
  for (let i = 0; i < 4; i++) for (let j = 0; j < 4; j++) {
    let s = 0;
    for (let k = 0; k < 4; k++) s += a[k * 4 + j] * b[i * 4 + k];
    o[i * 4 + j] = s;
  }
  return o;
};
const rotZ = t => new Float32Array([Math.cos(t), Math.sin(t), 0, 0, -Math.sin(t), Math.cos(t), 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]);
const tilt = e => new Float32Array([1, 0, 0, 0, 0, Math.sin(e), -Math.cos(e), 0, 0, Math.cos(e), Math.sin(e), 0, 0, 0, 0, 1]);
const move = (x, y, z) => new Float32Array([1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, x, y, z, 1]);
const scale = s => new Float32Array([s, 0, 0, 0, 0, s, 0, 0, 0, 0, s, 0, 0, 0, 0, 1]);
const persp = (fov, aspect, near, far) => {
  const f = 1 / Math.tan(fov / 2);
  return new Float32Array([f / aspect, 0, 0, 0, 0, f, 0, 0, 0, 0, (far + near) / (near - far), -1, 0, 0, 2 * far * near / (near - far), 0]);
};

// 3-vectors
const dot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
const add3 = (a, b, k = 1) => [a[0] + b[0] * k, a[1] + b[1] * k, a[2] + b[2] * k];
const sub3 = (a, b) => [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
const cross = (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
const unit = a => { const l = Math.hypot(a[0], a[1], a[2]) || 1; return [a[0] / l, a[1] / l, a[2] / l]; };
export const v3 = { dot, add: add3, sub: sub3, cross, unit };

// ---------- meshes: {pos, nor (Float32Array, 9 floats per triangle), color}
function withNormals(pos, color) {
  const nor = new Float32Array(pos.length);
  for (let i = 0; i < pos.length; i += 9) {
    const ax = pos[i + 3] - pos[i], ay = pos[i + 4] - pos[i + 1], az = pos[i + 5] - pos[i + 2];
    const bx = pos[i + 6] - pos[i], by = pos[i + 7] - pos[i + 1], bz = pos[i + 8] - pos[i + 2];
    let nx = ay * bz - az * by, ny = az * bx - ax * bz, nz = ax * by - ay * bx;
    const l = Math.hypot(nx, ny, nz) || 1;
    for (let k = 0; k < 9; k += 3) { nor[i + k] = nx / l; nor[i + k + 1] = ny / l; nor[i + k + 2] = nz / l; }
  }
  return { pos, nor, color };
}

export function parseStl(buf, color = COLORS.add) {
  const dv = new DataView(buf), n = dv.getUint32(80, true), pos = new Float32Array(n * 9);
  for (let i = 0; i < n; i++) for (let k = 0; k < 9; k++) pos[i * 9 + k] = dv.getFloat32(84 + i * 50 + 12 + k * 4, true);
  return withNormals(pos, color);
}

function grid(nu, nv, f) {  // a (u, v) surface -> triangles
  const out = [];
  for (let i = 0; i < nu; i++) for (let j = 0; j < nv; j++) {
    const a = f(i / nu, j / nv), b = f((i + 1) / nu, j / nv), c = f((i + 1) / nu, (j + 1) / nv), d = f(i / nu, (j + 1) / nv);
    out.push(...a, ...b, ...c, ...a, ...c, ...d);
  }
  return out;
}
const TAU = Math.PI * 2;
function lathe(c, r1, r2, h, inner = 0) {  // cylinder / cone / tube around Z, from the bottom center c
  const side = (ra, rb) => grid(32, 1, (u, v) => {
    const r = ra + (rb - ra) * v;
    return [c[0] + r * Math.cos(u * TAU), c[1] + r * Math.sin(u * TAU), c[2] + h * v];
  });
  const cap = (z, ro, ri) => grid(32, 1, (u, v) => {
    const r = ro + (ri - ro) * v;
    return [c[0] + r * Math.cos(u * TAU), c[1] + r * Math.sin(u * TAU), z];
  });
  const out = [...side(r1, r2), ...cap(c[2], r1, inner), ...cap(c[2] + h, r2, inner)];
  if (inner > 0) out.push(...side(inner, inner));
  return out;
}
function boxTris(c, s) {
  const [hx, hy, hz] = s.map(v => Math.abs(v) / 2), P = (x, y, z) => [c[0] + x * hx, c[1] + y * hy, c[2] + z * hz], out = [];
  const q = (a, b, cc, d) => out.push(...a, ...b, ...cc, ...a, ...cc, ...d);
  q(P(-1, -1, -1), P(-1, 1, -1), P(1, 1, -1), P(1, -1, -1)); q(P(-1, -1, 1), P(1, -1, 1), P(1, 1, 1), P(-1, 1, 1));
  q(P(-1, -1, -1), P(1, -1, -1), P(1, -1, 1), P(-1, -1, 1)); q(P(1, 1, -1), P(-1, 1, -1), P(-1, 1, 1), P(1, 1, 1));
  q(P(1, -1, -1), P(1, 1, -1), P(1, 1, 1), P(1, -1, 1)); q(P(-1, 1, -1), P(-1, -1, -1), P(-1, -1, 1), P(-1, 1, 1));
  return out;
}
const sphereTris = r => grid(24, 16, (u, v) => [r * Math.sin(v * Math.PI) * Math.cos(u * TAU), r * Math.sin(v * Math.PI) * Math.sin(u * TAU), r * Math.cos(v * Math.PI)]);

// ---------- screws: the same hole sizes as the engines (skills/threads-fasteners), for drawing and the editor
export const SCREWS = ["M2", "M2.5", "M3", "M4", "M5", "M6", "M8", "M10"];
export const CLEARANCE = { M2: 2.4, "M2.5": 2.9, M3: 3.4, M4: 4.5, M5: 5.5, M6: 6.6, M8: 8.6, M10: 10.6 };
const TAP = { M2: 1.7, "M2.5": 2.2, M3: 2.6, M4: 3.5, M5: 4.3, M6: 5.1, M8: 6.9, M10: 8.7 };
const INSERT = { M2: 3.2, "M2.5": 3.6, M3: 4.1, M4: 5.6, M5: 6.4, M6: 8.0, M8: 10.0, M10: 12.0 };
const INSERT_LEN = { M2: 4.0, "M2.5": 5.0, M3: 5.7, M4: 8.1, M5: 9.5, M6: 12.7, M8: 12.7, M10: 15.0 };
const NUT_AF = { M2: 4.3, "M2.5": 5.3, M3: 5.8, M4: 7.3, M5: 8.3, M6: 10.3, M8: 13.3, M10: 16.3 };
const NUT_H = { M2: 1.9, "M2.5": 2.3, M3: 2.7, M4: 3.5, M5: 4.3, M6: 5.5, M8: 6.8, M10: 8.7 };
const CBORE = { M2: [4.4, 2.2], "M2.5": [5.0, 2.7], M3: [6.5, 3.2], M4: [8.0, 4.2], M5: [9.5, 5.2], M6: [11.0, 6.2], M8: [14.0, 8.2], M10: [17.5, 10.2] };
const CSINK = { M2: 4.4, "M2.5": 5.4, M3: 7.1, M4: 9.4, M5: 11.6, M6: 13.8, M8: 18.3, M10: 22.4 };
const PITCH = { M2: 0.4, "M2.5": 0.45, M3: 0.5, M4: 0.7, M5: 0.8, M6: 1.0, M8: 1.25, M10: 1.5, M12: 1.75, M16: 2.0, M20: 2.5, M24: 3.0, M30: 3.5 };
export const FITS = [["clearance", "goes through (loose)"], ["tap", "cuts its own thread"], ["insert", "heat-set insert"],
  ["nut", "nut pocket (hex)"], ["thread", "printed thread"]];
/** ISO coarse pitch of the metric size nearest to diameter d (FreeCAD's threads). */
export const isoPitch = d => PITCH[Object.keys(PITCH).reduce((a, k) => (Math.abs(+k.slice(1) - d) < Math.abs(+a.slice(1) - d) ? k : a))];
/** A round printed thread's pitch (PicoGK): coarse on purpose — fine threads don't print. */
export const roundPitch = d => (d >= 8 ? Math.max(2.5, Math.round(d / 4 * 2) / 2) : Math.max(1, Math.round(d / 4 * 4) / 4));
const r1 = x => Math.round(x * 10) / 10;

/** A hole (Create › 3D): its drill diameter, real depth (0 = through), counterbore / countersink / nut, a label. */
export function holeInfo(h) {
  const size = SCREWS.includes(h.for) ? h.for : null, fit = FITS.some(f => f[0] === h.fit) ? h.fit : "clearance";
  const o = { size, fit, head: size && ["counterbore", "countersink"].includes(h.head) ? h.head : "", depth: Math.max(0, +h.depth || 0) };
  if (size && fit === "thread") o.d = +size.slice(1);
  else if (size) {
    o.d = { clearance: CLEARANCE, tap: TAP, insert: INSERT, nut: CLEARANCE }[fit][size];
    if (fit === "tap" && !o.depth) o.depth = r1(3 * +size.slice(1));  // a screw cuts ~3x its size into plastic
    if (fit === "insert") o.depth = o.depth || INSERT_LEN[size] + 1;
  } else o.d = Math.max(0.3, +h.diameter || 3);
  if (o.head === "counterbore") o.cbore = CBORE[size];
  if (o.head === "countersink") o.csink = CSINK[size];
  if (size && fit === "nut") o.nut = [NUT_AF[size], NUT_H[size]];
  const what = { clearance: "screw goes through", tap: "screw cuts its own thread", insert: "heat-set insert", nut: "screw + nut (hex pocket)", thread: "printed thread" }[fit];
  o.label = (size ? `${size} ${what}` : `Ø${r1(o.d)} mm${fit === "thread" ? " printed thread" : ""}`) + (o.head ? ` + ${o.head}` : "");
  return o;
}

// ---------- blueprint: a design (one body or a whole device) drawn from its shapes, before the engine builds it.
// PicoGK: a shape in its own frame (cylinders / cones / extrusions start at their center and go up), turned by rotate
// [x,y,z] (X, then Y, then Z), moved to center, then copied by repeat. FreeCAD: every shape sits ON its center
// (cylinders along "axis"). Not the exact result (cuts aren't carved) — "Build" makes that.
export const BODY_COLORS = ["#4ad696", "#5aa9ff", "#ffb347", "#ff6f91", "#c39bff", "#7fdbda", "#f9f871", "#ff9671", "#a0c878", "#e678dc"];
const D2R = Math.PI / 180;
/** p turned like the parts: X, then Y, then Z (degrees). */
export function rot(p, deg) {
  let [x, y, z] = p;
  if (!deg) return [x, y, z];
  const [a, b, c] = deg.map(d => (+d || 0) * D2R);
  [y, z] = [y * Math.cos(a) - z * Math.sin(a), y * Math.sin(a) + z * Math.cos(a)];
  [x, z] = [x * Math.cos(b) + z * Math.sin(b), -x * Math.sin(b) + z * Math.cos(b)];
  [x, y] = [x * Math.cos(c) - y * Math.sin(c), x * Math.sin(c) + y * Math.cos(c)];
  return [x, y, z];
}
function prism(pts, h) {  // a flat outline pulled up to height h (fan triangulation: fine for a preview)
  const out = [], n = pts.length;
  for (let i = 0; i < n; i++) {
    const [x0, y0] = pts[i], [x1, y1] = pts[(i + 1) % n];
    out.push(x0, y0, 0, x1, y1, 0, x1, y1, h, x0, y0, 0, x1, y1, h, x0, y0, h);
    if (i > 0 && i < n - 1) out.push(pts[0][0], pts[0][1], 0, x1, y1, 0, x0, y0, 0, pts[0][0], pts[0][1], h, x0, y0, h, x1, y1, h);
  }
  return out;
}
function turned(prof) {  // a [r, z] profile turned around the up axis
  const out = [];
  for (let i = 0; i < prof.length; i++) {
    const [r0, z0] = prof[i], [r1_, z1] = prof[(i + 1) % prof.length];
    out.push(...grid(32, 1, (u, v) => { const r = r0 + (r1_ - r0) * v, z = z0 + (z1 - z0) * v; return [r * Math.cos(u * TAU), r * Math.sin(u * TAU), z]; }));
  }
  return out;
}
function rings(r, h, P, z0) {  // a thread drawn as rings, one per turn (the real one is a helix)
  const out = [], tr = Math.max(0.12 * P, 0.12), n = Math.max(0, Math.min(60, Math.floor(h / P)));
  for (let k = 0; k < n; k++) {
    const z = z0 + (h - n * P) / 2 + (k + 0.5) * P;
    out.push(...grid(20, 5, (u, v) => { const a = u * TAU, b = v * TAU, q = r + tr * Math.cos(b); return [q * Math.cos(a), q * Math.sin(a), z + tr * Math.sin(b)]; }));
  }
  return out;
}
function localShape(p) {
  const r = +p.radius || 10, r2 = +(p.radius2 ?? r * 0.5), h = +p.height || 20, s = p.size || [20, 20, 20], o = [0, 0, 0];
  switch (p.shape) {
    case "sphere": return sphereTris(r);
    case "box": case "lattice": case "gyroid": return boxTris(o, s);
    case "cylinder": return p.thread ? [...lathe(o, r, r, h), ...rings(r, h, +p.thread.pitch || roundPitch(2 * r), 0)] : lathe(o, r, r, h);
    case "cone": return lathe(o, r, r2, h);
    case "tube": return lathe(o, r, r, h, Math.max(r - (+p.wall || 2), 0.1));
    case "torus": return grid(32, 16, (u, v) => { const a = u * TAU, b = v * TAU; return [(r + r2 * Math.cos(b)) * Math.cos(a), (r + r2 * Math.cos(b)) * Math.sin(a), r2 * Math.sin(b)]; });
    case "extrude": return (p.points || []).length >= 3 ? prism(p.points, h) : [];
    case "revolve": return (p.points || []).length >= 3 ? turned(p.points) : [];
    case "gear": { const m = +p.module || 1.5, ra = m * (+p.teeth || 20) / 2 + m * 0.5; return lathe(o, ra, ra, h, +p.bore || 0); }
    case "helix": return lathe(o, r + r2, r + r2, h, Math.max(r - r2, 0.1));
    case "tpms": return boxTris(o, s);
    case "quasicrystal": { const q = (+p.radius || 30) * 1.5; return grid(20, 12, (u, v) => [q * Math.sin(v * Math.PI) * Math.cos(u * TAU), q * Math.sin(v * Math.PI) * Math.sin(u * TAU), q * Math.cos(v * Math.PI)]); }
    case "rover_wheel": return lathe([0, 0, -60], 128, 128, 120, 20);
    default: return [];
  }
}
function rodTris(p) {  // a rod between two points, in assembly coordinates
  const a = p.from || [0, 0, 0], b = p.to || [0, 0, +p.height || 20], r = +p.radius || 2;
  const d = [b[0] - a[0], b[1] - a[1], b[2] - a[2]], L = Math.hypot(...d) || 1, w = d.map(x => x / L);
  const t = Math.abs(w[2]) < 0.9 ? [0, 0, 1] : [1, 0, 0];
  let u = [w[1] * t[2] - w[2] * t[1], w[2] * t[0] - w[0] * t[2], w[0] * t[1] - w[1] * t[0]];
  const ul = Math.hypot(...u); u = u.map(x => x / ul);
  const v = [w[1] * u[2] - w[2] * u[1], w[2] * u[0] - w[0] * u[2], w[0] * u[1] - w[1] * u[0]];
  const loc = lathe([0, 0, 0], r, +(p.radius2 ?? r), L), out = [];
  for (let i = 0; i < loc.length; i += 3) for (let j = 0; j < 3; j++) out.push(a[j] + loc[i] * u[j] + loc[i + 1] * v[j] + loc[i + 2] * w[j]);
  return out;
}
function pathTris(p) {  // a curved pipe: straight pieces between its path points (the engine makes it smooth)
  const pts = p.points || [], out = [];
  for (let i = 0; i + 1 < pts.length; i++) out.push(...rodTris({ from: pts[i], to: pts[i + 1], radius: +p.radius || 5 }));
  return out;
}
function placed(p) {  // a PicoGK part's triangles in the design, with its repeat copies
  const base = p.shape === "rod" ? rodTris(p) : p.shape === "curved_pipe" ? pathTris(p) : localShape(p);
  if (!base.length) return [];
  const c = p.center || [0, 0, 0], one = [];
  for (let i = 0; i < base.length; i += 3) {
    const own = p.shape === "rod" || p.shape === "curved_pipe";
    const q = own ? [base[i], base[i + 1], base[i + 2]] : rot([base[i], base[i + 1], base[i + 2]], p.rotate);
    one.push(q[0] + (own ? 0 : +c[0] || 0), q[1] + (own ? 0 : +c[1] || 0), q[2] + (own ? 0 : +c[2] || 0));
  }
  const rep = p.repeat, n = Math.min(Math.max(Math.round(+rep?.count || 1), 1), 200);
  if (n === 1) return one;
  const out = [], step = rep.step, piv = rep.axis_point || [0, 0, 0], total = +(rep.angle ?? 360);
  for (let k = 0; k < n; k++) {
    const a = total * D2R * k / (Math.abs(total - 360) < 0.01 ? n : Math.max(n - 1, 1));
    for (let i = 0; i < one.length; i += 3) {
      if (step && step.some(x => +x)) { out.push(one[i] + step[0] * k, one[i + 1] + step[1] * k, one[i + 2] + step[2] * k); continue; }
      const x = one[i] - piv[0], y = one[i + 1] - piv[1];
      out.push(x * Math.cos(a) - y * Math.sin(a) + piv[0], x * Math.sin(a) + y * Math.cos(a) + piv[1], one[i + 2]);
    }
  }
  return out;
}
const AXV = { x: [1, 0, 0], y: [0, 1, 0], z: [0, 0, 1] };
function along(t, axis) {  // a shape made along Z, turned to lie along axis x / y
  if (axis !== "x" && axis !== "y") return t;
  const out = new Array(t.length);
  for (let i = 0; i < t.length; i += 3) {
    const x = t[i], y = t[i + 1], z = t[i + 2];
    if (axis === "x") { out[i] = z; out[i + 1] = x; out[i + 2] = y; } else { out[i] = y; out[i + 1] = z; out[i + 2] = x; }
  }
  return out;
}
function fcShape(p) {  // FreeCAD's shapes around 0 (each sits on its center)
  const r = +p.radius || 10, h = +p.height || 10, s = p.size || [20, 20, 20], c = [0, 0, -h / 2];
  switch (p.shape) {
    case "box": return boxTris([0, 0, 0], s);
    case "cylinder": return along(p.thread ? [...lathe(c, r, r, h), ...rings(r, h, +p.thread.pitch || isoPitch(2 * r), -h / 2)] : lathe(c, r, r, h), p.axis);
    case "cone": return along(lathe(c, r, Math.max(+p.radius2 || 0, 0.001), h), p.axis);
    case "tube": return along(lathe(c, r, r, h, Math.max(r - (+p.wall || 2), 0.05)), p.axis);
    case "sphere": return sphereTris(r);
    case "slot": {
      const L = +p.length || 20, W = +p.width || 4, H = +p.height || 5, st = Math.max(0, L - W);
      const loc = [...boxTris([0, 0, 0], [Math.max(st, 0.01), W, H]), ...lathe([-st / 2, 0, -H / 2], W / 2, W / 2, H), ...lathe([st / 2, 0, -H / 2], W / 2, W / 2, H)];
      const ax = p.axis || "z", dx = p.direction && p.direction !== ax ? p.direction : (ax === "x" ? "y" : "x");
      const X = AXV[dx], Z = AXV[ax], Y = cross(Z, X), out = new Array(loc.length);
      for (let i = 0; i < loc.length; i += 3) for (let j = 0; j < 3; j++) out[i + j] = loc[i] * X[j] + loc[i + 1] * Y[j] + loc[i + 2] * Z[j];
      return out;
    }
    case "polygon": return (p.points || []).length >= 3 ? prism(p.points, h).map((v, i) => (i % 3 === 2 ? v - h / 2 : v)) : [];
    default: return [];
  }
}
function placedFC(p) {
  const base = fcShape(p), c = p.center || [0, 0, 0], out = [];
  for (let i = 0; i < base.length; i += 3) {
    const q = rot([base[i], base[i + 1], base[i + 2]], p.rotate);
    out.push(q[0] + (+c[0] || 0), q[1] + (+c[1] || 0), q[2] + (+c[2] || 0));
  }
  return out;
}
/** The 3D printer's plate under a design (lo / hi = the design's box): a flat sheet with a 20 mm grid, green when the
 * design fits, red when it's too big. Not picked, not counted when the view frames the design. */
export const fitsBed = (size, bed) => size[2] <= bed[2] + 0.01 && ((size[0] <= bed[0] && size[1] <= bed[1]) || (size[1] <= bed[0] && size[0] <= bed[1]));
export function plateMeshes(lo, hi, bed, ok = null) {  // ok: decided by the caller (a device: every part on its own)
  const [W, D] = bed, cx = (lo[0] + hi[0]) / 2, cy = (lo[1] + hi[1]) / 2, z = lo[2] - 0.3;
  const size = [hi[0] - lo[0], hi[1] - lo[1], hi[2] - lo[2]];
  const fits = ok ?? fitsBed(size, bed);
  const quad = (x0, y0, x1, y1, zz) => [x0, y0, zz, x1, y0, zz, x1, y1, zz, x0, y0, zz, x1, y1, zz, x0, y1, zz];
  const x0 = cx - W / 2, y0 = cy - D / 2, w = Math.max(0.35, W / 450), lines = [];
  for (let x = 0; x <= W + 1e-6; x += 20) lines.push(...quad(x0 + x - w, y0, x0 + x + w, y0 + D, z + 0.05));
  for (let y = 0; y <= D + 1e-6; y += 20) lines.push(...quad(x0, y0 + y - w, x0 + W, y0 + y + w, z + 0.05));
  const sheet = withNormals(new Float32Array(quad(x0, y0, x0 + W, y0 + D, z)), [0.55, 0.6, 0.65, 0.12]);
  const grid = withNormals(new Float32Array(lines), fits ? [0.29, 0.84, 0.59, 0.4] : [1, 0.35, 0.35, 0.7]);
  for (const m of [sheet, grid]) { m.nopick = true; m.nofit = true; }
  return { meshes: [sheet, grid], fits, size };
}

/** A part's triangles where it sits in the design (either engine). */
export const partTris = (p, fc) => (fc ? placedFC(p) : placed(p));

/** Two directions across D (u level when it can be; u x v = D). */
export function across(D) {
  const L = Math.hypot(D[0], D[1]), u = L > 1e-9 ? [D[1] / L, -D[0] / L, 0] : [1, 0, 0];
  return [u, cross(D, u)];
}
function aimed(t, base, D) {  // triangles made along Z -> along direction D, starting at base
  const [u, v] = across(D), out = new Array(t.length);
  for (let i = 0; i < t.length; i += 3) for (let j = 0; j < 3; j++) out[i + j] = base[j] + t[i] * u[j] + t[i + 1] * v[j] + t[i + 2] * D[j];
  return out;
}
const hexagon = af => { const r = af / Math.sqrt(3); return [0, 1, 2, 3, 4, 5].map(i => [r * Math.cos(i * Math.PI / 3), r * Math.sin(i * Math.PI / 3)]); };
/** A hole as the drill it is: from 1 mm outside the surface, `far` long when it goes through. */
export function holeTris(h, far) {
  const o = holeInfo(h), D = unit(h.dir || [0, 0, -1]), start = add3(h.at || [0, 0, 0], D, -1), L = (o.depth || far) + 1;
  const out = aimed(lathe([0, 0, 0], o.d / 2, o.d / 2, L), start, D);
  if (o.cbore) out.push(...aimed(lathe([0, 0, 0], o.cbore[0] / 2, o.cbore[0] / 2, o.cbore[1] + 1), start, D));
  if (o.csink) out.push(...aimed(lathe([0, 0, 1], o.csink / 2, o.d / 2, (o.csink - o.d) / 2), start, D), ...aimed(lathe([0, 0, 0], o.csink / 2, o.csink / 2, 1), start, D));
  if (o.nut) out.push(...aimed(prism(hexagon(o.nut[0]), o.nut[1] + 1), start, D));
  if (o.fit === "thread") out.push(...aimed(rings(o.d / 2, L - 1, +h.pitch || isoPitch(o.d), 1), start, D));
  return out;
}
function throughLen(solid, h) {  // a through hole drawn until the drill leaves the last material in its way
  const D = unit(h.dir || [0, 0, -1]), o = add3(h.at || [0, 0, 0], D, -1);
  let far = 0;
  for (const t of solid) for (let i = 0; i < t.length; i += 9) {
    const e1 = [t[i + 3] - t[i], t[i + 4] - t[i + 1], t[i + 5] - t[i + 2]], e2 = [t[i + 6] - t[i], t[i + 7] - t[i + 1], t[i + 8] - t[i + 2]];
    const pv = cross(D, e2), det = dot(e1, pv);
    if (Math.abs(det) < 1e-12) continue;
    const tv = [o[0] - t[i], o[1] - t[i + 1], o[2] - t[i + 2]], u = dot(tv, pv) / det;
    if (u < 0 || u > 1) continue;
    const qv = cross(tv, e1), v = dot(D, qv) / det;
    if (v < 0 || u + v > 1) continue;
    const d = dot(e2, qv) / det;
    if (d > far) far = d;
  }
  return far > 0 ? far : 0;  // measured from 1 mm outside: that's the length the drill needs
}
function exitLen(lo, hi, h) {  // how far a through hole runs before it leaves the body's box (drawn that long)
  const D = unit(h.dir || [0, 0, -1]), S = h.at || [0, 0, 0];
  let t = Infinity;
  for (let k = 0; k < 3; k++) if (Math.abs(D[k]) > 1e-9) t = Math.min(t, ((D[k] > 0 ? hi[k] : lo[k]) - S[k]) / D[k]);
  return Math.max(1, Number.isFinite(t) ? t : Math.hypot(hi[0] - lo[0], hi[1] - lo[1], hi[2] - lo[2])) + 1;
}
const rgba = (h, a = 1, k = 1) => [parseInt(h.slice(1, 3), 16) / 255 * k, parseInt(h.slice(3, 5), 16) / 255 * k, parseInt(h.slice(5, 7), 16) / 255 * k, a];

/** A design -> meshes. `selected` = the body being edited (the others are drawn a little darker); `sel` = the part /
 * hole selected in Create › 3D ({kind, body, index}). Every mesh knows what it is (m.ref) for picking. */
export function blueprint(recipe, selected = -1, sel = null) {
  const fc = recipe?.engine === "freecad";
  const bodies = recipe?.bodies?.length ? recipe.bodies : [{ parts: recipe?.parts || [], holes: recipe?.holes || [] }];
  const meshes = [];
  bodies.forEach((b, bi) => {
    const dim = selected >= 0 && bi !== selected ? 0.6 : 1, lo = [Infinity, Infinity, Infinity], hi = [-Infinity, -Infinity, -Infinity], solid = [];
    (b.parts || []).forEach((p, i) => {
      const tris = fc ? placedFC(p) : placed(p);
      if (!tris.length) return;
      const op = i ? (p.op || "add") : "add", cut = op === "subtract" || op === "cut", on = (sel?.kind === "part" && sel.body === bi && sel.index === i) || (sel?.kind === "body" && sel.body === bi);
      let color = cut ? COLORS.subtract : op === "intersect" ? COLORS.intersect : b.reference ? [0.6, 0.62, 0.66, 0.45]
        : ["lattice", "gyroid"].includes(p.shape) ? rgba(BODY_COLORS[bi % BODY_COLORS.length], 0.55, dim) : rgba(BODY_COLORS[bi % BODY_COLORS.length], 1, dim);
      if (on) color = [...SEL, color[3] < 1 ? 0.55 : 1];
      const m = withNormals(new Float32Array(tris), color);
      m.body = bi;
      m.ref = { kind: "part", body: bi, index: i };
      m.cut = cut;
      if (on && color[3] < 1) m.xray = true;  // a selected cut is seen through the part it cuts
      if (!cut) { solid.push(tris); for (let k = 0; k < tris.length; k++) { const a = k % 3; if (tris[k] < lo[a]) lo[a] = tris[k]; if (tris[k] > hi[a]) hi[a] = tris[k]; } }
      meshes.push(m);
    });
    (b.holes || []).forEach((h, i) => {
      const on = (sel?.kind === "hole" && sel.body === bi && sel.index === i) || (sel?.kind === "body" && sel.body === bi);
      const m = withNormals(new Float32Array(holeTris(h, lo[0] < Infinity ? throughLen(solid, h) || exitLen(lo, hi, h) : 100)), on ? [...SEL, 0.85] : [0.98, 0.3, 0.3, 0.5]);
      m.body = bi;
      m.ref = { kind: "hole", body: bi, index: i };
      m.xray = m.front = true;  // holes are always seen (drawn through the part) — and picked first
      meshes.push(m);
    });
  });
  return meshes;
}

// ---------- picking: which mesh is under the pointer
function bounds(m) {
  if (m._lo) return;
  const lo = [Infinity, Infinity, Infinity], hi = [-Infinity, -Infinity, -Infinity], p = m.pos;
  for (let i = 0; i < p.length; i += 3) for (let k = 0; k < 3; k++) { if (p[i + k] < lo[k]) lo[k] = p[i + k]; if (p[i + k] > hi[k]) hi[k] = p[i + k]; }
  m._lo = lo; m._hi = hi;
}
function hitMesh(m, o, d) {  // the nearest triangle the ray o + t d hits (Möller–Trumbore), after a box test
  bounds(m);
  const off = m.offset || [0, 0, 0], O = [o[0] - off[0], o[1] - off[1], o[2] - off[2]];
  let t0 = -Infinity, t1 = Infinity;
  for (let k = 0; k < 3; k++) {
    if (Math.abs(d[k]) < 1e-12) { if (O[k] < m._lo[k] - 1e-6 || O[k] > m._hi[k] + 1e-6) return null; continue; }
    let a = (m._lo[k] - O[k]) / d[k], b = (m._hi[k] - O[k]) / d[k];
    if (a > b) [a, b] = [b, a];
    t0 = Math.max(t0, a); t1 = Math.min(t1, b);
    if (t0 > t1 + 1e-9) return null;
  }
  if (t1 < 0) return null;
  const p = m.pos;
  let best = Infinity, bi = -1;
  for (let i = 0; i < p.length; i += 9) {
    const e1x = p[i + 3] - p[i], e1y = p[i + 4] - p[i + 1], e1z = p[i + 5] - p[i + 2];
    const e2x = p[i + 6] - p[i], e2y = p[i + 7] - p[i + 1], e2z = p[i + 8] - p[i + 2];
    const px = d[1] * e2z - d[2] * e2y, py = d[2] * e2x - d[0] * e2z, pz = d[0] * e2y - d[1] * e2x;
    const det = e1x * px + e1y * py + e1z * pz;
    if (Math.abs(det) < 1e-12) continue;
    const inv = 1 / det, tx = O[0] - p[i], ty = O[1] - p[i + 1], tz = O[2] - p[i + 2];
    const u = (tx * px + ty * py + tz * pz) * inv;
    if (u < 0 || u > 1) continue;
    const qx = ty * e1z - tz * e1y, qy = tz * e1x - tx * e1z, qz = tx * e1y - ty * e1x;
    const v = (d[0] * qx + d[1] * qy + d[2] * qz) * inv;
    if (v < 0 || u + v > 1) continue;
    const t = (e2x * qx + e2y * qy + e2z * qz) * inv;
    if (t > 1e-6 && t < best) { best = t; bi = i; }
  }
  return bi < 0 ? null : { t: best, tri: bi };
}

/** A viewer in `host`. Returns { show(meshes, keepView), redraw, pick, project, ray, pxSize, setTool, setOverlay, focus }. */
export function makeViewer(host) {
  const canvas = document.createElement("canvas");
  canvas.className = "view3d";
  canvas.title = "Drag to turn · right-drag or Shift-drag to move the view · wheel to zoom · double-click to reset";
  host.append(canvas);
  const over = document.createElement("canvas");  // the editor's arrows, handles and hole circle: drawn on top
  over.className = "view3d-over";
  host.append(over);
  const g2 = over.getContext("2d");
  const gl = canvas.getContext("webgl", { antialias: true, alpha: true, premultipliedAlpha: false });
  if (!gl) {
    host.textContent = "The 3D view isn't available here.";
    return { show() {}, redraw() {}, pick: () => null, project: () => [0, 0, -1], ray: () => ({ o: [0, 0, 0], d: [0, 0, -1] }),
      pxSize: () => 1, setTool() {}, setOverlay() {}, focus() {} };
  }
  const prog = gl.createProgram();
  for (const [type, src] of [[gl.VERTEX_SHADER, VS], [gl.FRAGMENT_SHADER, FS]]) {
    const sh = gl.createShader(type); gl.shaderSource(sh, src); gl.compileShader(sh); gl.attachShader(prog, sh);
  }
  gl.linkProgram(prog); gl.useProgram(prog);
  const aP = gl.getAttribLocation(prog, "p"), aN = gl.getAttribLocation(prog, "n");
  const uM = gl.getUniformLocation(prog, "m"), uR = gl.getUniformLocation(prog, "r"), uC = gl.getUniformLocation(prog, "c"),
    uO = gl.getUniformLocation(prog, "o");
  gl.enableVertexAttribArray(aP); gl.enableVertexAttribArray(aN);
  const FOV = 0.7, TH = Math.tan(FOV / 2);
  let items = [], home = [0, 0, 0], target = [0, 0, 0], radius = 1, az = 0.6, el = 0.5, dist = 3.2, queued = false;
  let tool = null, overlay = null, cam = null;
  const camera = () => {  // where the eye is and which way is right / up / back (world), plus the full matrix
    const w = canvas.clientWidth || 1, h = canvas.clientHeight || 1, r = mul(tilt(el), rotZ(az));
    const view = mul(move(0, 0, -dist), mul(r, mul(scale(1 / radius), move(-target[0], -target[1], -target[2]))));
    const right = [r[0], r[4], r[8]], up = [r[1], r[5], r[9]], back = [r[2], r[6], r[10]];
    return { w, h, rot: r, right, up, back, eye: add3(target, back, dist * radius), mvp: mul(persp(FOV, w / h, 0.02, 80), view) };
  };
  const cur = () => cam || (cam = camera());
  const project = p => {  // world -> [x, y] in CSS pixels of the canvas, + depth (w > 0: in front of the eye)
    const c = cur(), m = c.mvp;
    const x = m[0] * p[0] + m[4] * p[1] + m[8] * p[2] + m[12], y = m[1] * p[0] + m[5] * p[1] + m[9] * p[2] + m[13];
    const w = m[3] * p[0] + m[7] * p[1] + m[11] * p[2] + m[15];
    return [(x / w + 1) / 2 * c.w, (1 - y / w) / 2 * c.h, w];
  };
  const ray = (x, y) => {  // the line from the eye through pixel (x, y)
    const c = cur(), nx = (2 * x / c.w - 1) * TH * (c.w / c.h), ny = (1 - 2 * y / c.h) * TH;
    return { o: c.eye, d: unit([0, 1, 2].map(j => c.right[j] * nx + c.up[j] * ny - c.back[j])) };
  };
  const pxSize = p => { const c = cur(); return 2 * TH * Math.max(-dot(sub3(p, c.eye), c.back), 1e-6) / c.h; };  // mm per pixel at p
  const draw = () => {
    queued = false;
    const dpr = window.devicePixelRatio || 1, w = Math.round(canvas.clientWidth * dpr), h = Math.round(canvas.clientHeight * dpr);
    if (canvas.width !== w || canvas.height !== h) { canvas.width = w; canvas.height = h; }
    if (over.width !== w || over.height !== h) { over.width = w; over.height = h; }
    cam = camera();
    gl.viewport(0, 0, w, h); gl.clearColor(0, 0, 0, 0); gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
    gl.uniformMatrix4fv(uM, false, cam.mvp); gl.uniformMatrix4fv(uR, false, cam.rot);
    for (const pass of [0, 1, 2]) {  // solid parts, then see-through ones, then x-ray ones (holes: always seen)
      if (pass === 0) { gl.enable(gl.DEPTH_TEST); gl.disable(gl.BLEND); gl.depthMask(true); }
      else if (pass === 1) { gl.enable(gl.BLEND); gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA); gl.depthMask(false); }
      else gl.disable(gl.DEPTH_TEST);
      for (const it of items) {
        const m = it.mesh;
        if (m.hidden || (m.xray ? 2 : m.color[3] < 1 ? 1 : 0) !== pass) continue;
        gl.uniform3fv(uO, m.offset || [0, 0, 0]);
        gl.bindBuffer(gl.ARRAY_BUFFER, it.bp); gl.vertexAttribPointer(aP, 3, gl.FLOAT, false, 0, 0);
        gl.bindBuffer(gl.ARRAY_BUFFER, it.bn); gl.vertexAttribPointer(aN, 3, gl.FLOAT, false, 0, 0);
        gl.uniform4fv(uC, m.color);
        gl.drawArrays(gl.TRIANGLES, 0, it.count);
      }
    }
    gl.depthMask(true); gl.enable(gl.DEPTH_TEST);
    g2.setTransform(1, 0, 0, 1, 0, 0); g2.clearRect(0, 0, over.width, over.height);
    if (overlay) { g2.setTransform(dpr, 0, 0, dpr, 0, 0); try { overlay(g2, api); } catch (e) { console.error(e); } }
  };
  const redraw = () => { if (!queued) { queued = true; requestAnimationFrame(draw); } };
  const panBy = (dx, dy) => {  // the model follows the pointer
    cam = camera();
    const s = pxSize(target);
    target = add3(add3(target, cam.right, -dx * s), cam.up, dy * s);
    cam = null; redraw();
  };
  const zoomAt = (p, f) => {  // closer / further, keeping the point under the pointer where it is
    cam = camera();
    const nd = Math.max(0.12, Math.min(30, dist * f)), { o, d } = ray(p[0], p[1]), den = dot(d, cam.back);
    if (Math.abs(den) > 1e-9) target = add3(target, sub3(add3(o, d, dot(sub3(target, o), cam.back) / den), target), 1 - nd / dist);
    dist = nd; cam = null; redraw();
  };
  const pick = (x, y, keep) => {  // "front" meshes (holes) first: they're drawn on top, so that's what you see
    const { o, d } = ray(x, y);
    let best = null;
    for (const pass of [true, false]) {
      for (const it of items) {
        const m = it.mesh;
        if (m.hidden || m.nopick || !!m.front !== pass || (keep && !keep(m))) continue;
        const h = hitMesh(m, o, d);
        if (h && (!best || h.t < best.t)) best = { ...h, mesh: m };
      }
      if (best) break;
    }
    if (!best) return null;
    const P = best.mesh.pos, i = best.tri, A = [P[i], P[i + 1], P[i + 2]];
    let n = unit(cross(sub3([P[i + 3], P[i + 4], P[i + 5]], A), sub3([P[i + 6], P[i + 7], P[i + 8]], A)));
    if (dot(n, d) > 0) n = [-n[0], -n[1], -n[2]];  // the side facing you: the outside you clicked on
    const point = add3(o, d, best.t);
    return { mesh: best.mesh, point, at: sub3(point, best.mesh.offset || [0, 0, 0]), normal: n, ray: { o, d } };
  };
  // pointers: mouse (left turns, right / middle / Shift moves the view), touch and pen (two fingers zoom and move)
  const pts = new Map();
  let gest = null;
  const at = e => { const r = canvas.getBoundingClientRect(); return [e.clientX - r.left, e.clientY - r.top]; };
  canvas.oncontextmenu = e => e.preventDefault();
  canvas.onpointerdown = e => {
    canvas.setPointerCapture(e.pointerId);
    const p = at(e);
    pts.set(e.pointerId, p);
    if (pts.size >= 2) {  // a second finger: zoom + move the view (whatever the first one started is dropped)
      clearTimeout(gest?.long);
      if (gest?.kind === "tool") tool?.cancel?.();
      const [a, b] = [...pts.values()];
      gest = { kind: "pinch", span: Math.hypot(a[0] - b[0], a[1] - b[1]), mid: [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2] };
      return;
    }
    cam = null;
    if (e.button === 0 && tool?.down?.(p, e)) gest = { kind: "tool", start: p, moved: false };
    else gest = e.button !== 0 || e.shiftKey ? { kind: "pan", last: p, start: p, button: e.button, moved: false } : { kind: "orbit", last: p, start: p, moved: false };
    if (e.pointerType !== "mouse" && tool?.menu) {  // a long press without moving = the right-click menu
      const g = gest;
      g.long = setTimeout(() => {
        if (gest !== g || g.moved || pts.size !== 1) return;
        if (g.kind === "tool") tool?.cancel?.();
        gest = null;
        tool.menu(p, e);
      }, 600);
    }
  };
  canvas.onpointermove = e => {
    const p = at(e);
    if (pts.has(e.pointerId)) pts.set(e.pointerId, p);
    if (!gest) { if (tool?.hover && e.pointerType !== "touch") canvas.style.cursor = tool.hover(p, e) || ""; return; }
    if (gest.kind === "pinch") {
      if (pts.size < 2) return;
      const [a, b] = [...pts.values()], span = Math.hypot(a[0] - b[0], a[1] - b[1]), mid = [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2];
      if (span > 1 && gest.span > 1) zoomAt(mid, gest.span / span);
      panBy(mid[0] - gest.mid[0], mid[1] - gest.mid[1]);
      Object.assign(gest, { span, mid });
      return;
    }
    if (!gest.moved && Math.hypot(p[0] - gest.start[0], p[1] - gest.start[1]) > 4) { gest.moved = true; clearTimeout(gest.long); }
    if (gest.kind === "tool") { cam = null; tool?.move?.(p, e); return; }
    const dx = p[0] - gest.last[0], dy = p[1] - gest.last[1];
    gest.last = p;
    if (gest.kind === "pan") { if (gest.moved) panBy(dx, dy); return; }
    if (!gest.moved) return;  // a click's little wobble doesn't turn the model
    az += dx * 0.01; el = Math.max(-1.45, Math.min(1.45, el + dy * 0.01));
    cam = null; redraw();
  };
  const end = e => {
    const p = at(e), mine = pts.delete(e.pointerId);
    if (!gest || !mine) return;
    if (gest.kind === "pinch") { if (!pts.size) gest = null; return; }
    const g = gest;
    gest = null;
    clearTimeout(g.long);
    if (g.kind === "tool") { tool?.up?.(p, e); return; }
    if (g.kind === "orbit" && !g.moved && e.type === "pointerup") { cam = null; tool?.click?.(p, e); }
    if (g.kind === "pan" && g.button === 2 && !g.moved && e.type === "pointerup") { cam = null; tool?.menu?.(p, e); }
  };
  canvas.onpointerup = end;
  canvas.onpointercancel = end;
  canvas.onpointerleave = () => { if (!gest) tool?.leave?.(); };
  canvas.onwheel = e => { e.preventDefault(); zoomAt(at(e), Math.exp(e.deltaY * 0.0012)); };
  canvas.ondblclick = e => {
    if (tool?.dblclick?.(at(e), e)) return;
    az = 0.6; el = 0.5; dist = 3.2; target = [...home]; cam = null; redraw();
  };
  new ResizeObserver(() => { cam = null; redraw(); }).observe(canvas);
  const api = {
    canvas, over,
    show(meshes, keepView = false) {
      for (const it of items) { gl.deleteBuffer(it.bp); gl.deleteBuffer(it.bn); }
      items = meshes.map(m => {
        const bp = gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER, bp); gl.bufferData(gl.ARRAY_BUFFER, m.pos, gl.STATIC_DRAW);
        const bn = gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER, bn); gl.bufferData(gl.ARRAY_BUFFER, m.nor, gl.STATIC_DRAW);
        return { bp, bn, mesh: m, count: m.pos.length / 3 };
      });
      if (!keepView || !meshes.length) {
        const lo = [Infinity, Infinity, Infinity], hi = [-Infinity, -Infinity, -Infinity];
        for (const m of meshes) if (!m.nofit) for (let i = 0; i < m.pos.length; i++) { lo[i % 3] = Math.min(lo[i % 3], m.pos[i]); hi[i % 3] = Math.max(hi[i % 3], m.pos[i]); }
        if (meshes.length) {
          home = lo.map((x, j) => (x + hi[j]) / 2); radius = Math.hypot(hi[0] - lo[0], hi[1] - lo[1], hi[2] - lo[2]) / 2 || 1;
          target = [...home];
        }
      }
      cam = null; redraw();
    },
    redraw() { cam = null; redraw(); },  // after changing a mesh's .hidden / .offset, or the overlay
    pick, project, ray, pxSize,
    setTool(t) { tool = t; canvas.style.cursor = ""; },
    setOverlay(f) { overlay = f; redraw(); },
    focus(lo, hi) {  // look at this box (the selected part: F)
      target = lo.map((x, j) => (x + hi[j]) / 2);
      dist = Math.max(0.12, Math.min(30, Math.max(Math.hypot(hi[0] - lo[0], hi[1] - lo[1], hi[2] - lo[2]), 2) / radius / (2 * TH) * 1.5));
      cam = null; redraw();
    },
  };
  return api;
}

const hex = (h, a = 1) => [parseInt(h.slice(1, 3), 16) / 255, parseInt(h.slice(3, 5), 16) / 255, parseInt(h.slice(5, 7), 16) / 255, a];

import { cutAndPrint, openPrint } from "./print3d.js";

// ---------- the right-click menu (3D views: Create › 3D and the chat's 3D cards)
let menuEl = null;
const menuOff = e => { if (menuEl && !menuEl.contains(e.target)) closeMenu(); };
const menuEsc = e => { if (e.key === "Escape") { e.stopPropagation(); e.preventDefault(); closeMenu(); } };
export function closeMenu() {
  menuEl?.remove();
  menuEl = null;
  document.removeEventListener("pointerdown", menuOff, true);
  document.removeEventListener("keydown", menuEsc, true);
  window.removeEventListener("blur", closeMenu);
}
/** A menu at (x, y) on the page: items [{label, key, act, disabled, danger} | {sep: true}]. */
export function popMenu(x, y, items) {
  closeMenu();
  const m = document.createElement("div");
  m.className = "ctxmenu";
  m.oncontextmenu = e => e.preventDefault();
  for (const it of items) {
    if (it.sep) { if (m.lastChild && m.lastChild.tagName !== "HR") m.append(document.createElement("hr")); continue; }
    const b = document.createElement("button");
    b.className = "mi" + (it.danger ? " danger" : "");
    b.disabled = !!it.disabled;
    b.innerHTML = `<span></span>${it.key ? "<kbd></kbd>" : ""}`;
    b.firstChild.textContent = it.label;
    if (it.key) b.lastChild.textContent = it.key;
    b.onclick = () => { closeMenu(); it.act?.(); };
    m.append(b);
  }
  if (m.lastChild?.tagName === "HR") m.lastChild.remove();
  document.body.append(m);
  const r = m.getBoundingClientRect();
  m.style.left = Math.max(4, Math.min(x, innerWidth - r.width - 6)) + "px";
  m.style.top = Math.max(4, Math.min(y, innerHeight - r.height - 6)) + "px";
  menuEl = m;
  setTimeout(() => {
    document.addEventListener("pointerdown", menuOff, true);
    document.addEventListener("keydown", menuEsc, true);
    window.addEventListener("blur", closeMenu);
  }, 0);
}
export function download(url, name) {  // "Save …": the browser's own download (same as the Download buttons)
  const a = Object.assign(document.createElement("a"), { href: url, download: name || "" });
  document.body.append(a);
  a.click();
  a.remove();
}
const safeName = n => String(n || "model").replace(/[^\w -]/g, "").trim() || "model";

/** Explode / assemble: every group (a part of the device) moves away from the middle, k = 0 (assembled) .. 1.5. */
export function exploder(meshes, v, group = (m, i) => i) {
  const ids = meshes.map(group), boxes = {};
  meshes.forEach((m, i) => {
    const b = boxes[ids[i]] || (boxes[ids[i]] = { lo: [Infinity, Infinity, Infinity], hi: [-Infinity, -Infinity, -Infinity] });
    for (let k = 0; k < m.pos.length; k++) { b.lo[k % 3] = Math.min(b.lo[k % 3], m.pos[k]); b.hi[k % 3] = Math.max(b.hi[k % 3], m.pos[k]); }
  });
  const centers = {};
  for (const id in boxes) centers[id] = boxes[id].lo.map((x, j) => (x + boxes[id].hi[j]) / 2);
  const all = Object.values(centers), mid = [0, 1, 2].map(j => all.reduce((s, c) => s + c[j], 0) / Math.max(all.length, 1));
  let k = 0, anim = 0;
  const set = x => {
    k = x;
    meshes.forEach((m, i) => { m.offset = centers[ids[i]].map((c, j) => (c - mid[j]) * k); });
    v.redraw();
  };
  return {
    groups: all.length, get k() { return k; }, set,
    animateTo(target, ms = 650, onStep) {  // eased, like the parts sliding apart / back together
      const from = k, t0 = performance.now(), id = ++anim;
      const step = now => {
        if (id !== anim) return;
        const t = Math.min((now - t0) / ms, 1), e = t < 0.5 ? 2 * t * t : 1 - (-2 * t + 2) ** 2 / 2;
        set(from + (target - from) * e);
        onStep?.(k);
        if (t < 1) requestAnimationFrame(step);
      };
      requestAnimationFrame(step);
    },
  };
}

/** A whole device: every part in its colour, parts list with show / hide + download, explode slider, fit check. */
export async function viewAssembly(info, host, panel, h) {
  host.innerHTML = `<div class="muted small" style="padding:12px">Loading ${info.parts.length} parts…</div>`;
  const meshes = await Promise.all(info.parts.map(async p => parseStl(await (await fetch(p.view || p.stl)).arrayBuffer(), hex(p.color, p.reference ? 0.45 : 1))));
  host.innerHTML = "";
  const v = makeViewer(host);
  v.show(meshes);
  const ex = exploder(meshes, v);
  if (!panel) return { v, meshes, ex };
  const fit = !info.collisions?.length
    ? `<span class="fitok">✓ Fit check: ${info.checked_pairs ?? ""} part pairs checked — nothing collides</span>`
    : `<span class="fitbad">⚠ Collisions: ${info.collisions.map(c => `${h(c.a)} ↔ ${h(c.b)} (${c.volume_mm3 != null ? c.volume_mm3 + " mm³" : (c.crossing_faces ?? "?") + " crossing faces"})`).join(", ")}</span>`;
  panel.innerHTML = `<div class="small">${fit}</div>
    <div class="row small" style="align-items:center"><button class="btn sm exbtn">Explode</button>
      <input type="range" min="0" max="1.5" step="0.05" value="0" class="grow" title="How far apart"></div>
    <div class="m3parts"></div>
    <div class="row"><a class="btn sm" href="${info.zip}" download>Download all parts (zip)</a><span class="grow"></span></div>
    ${info.notes ? `<details class="small"><summary>How it goes together</summary><div class="muted">${h(info.notes)}</div></details>` : ""}`;
  const slider = panel.querySelector("input[type=range]"), btn = panel.querySelector(".exbtn");
  const label = () => { btn.textContent = ex.k > 0.05 ? "Assemble" : "Explode"; };
  slider.oninput = () => { ex.set(+slider.value); label(); };
  btn.onclick = () => ex.animateTo(ex.k > 0.05 ? 0 : 0.8, 650, k => { slider.value = k; label(); });
  const list = panel.querySelector(".m3parts");
  info.parts.forEach((p, i) => {
    const row = document.createElement("label");
    row.className = "m3part";
    const size = (p.size_mm || []).map(x => Math.round(x)).join("×");
    row.innerHTML = `<input type="checkbox" checked style="min-height:0"><span class="sw" style="background:${p.color}"></span>
      <span class="grow">${h(p.name)} <span class="muted">${size} mm${p.reference ? " · buy" : p.grams ? ` · ${p.grams} g` : ""}</span></span>
      ${p.reference ? "" : `<a class="btn sm ghost" href="${p.stl}" download="${h(p.name.replace(/[^\w -]/g, ""))}.stl">STL</a>`}`;
    row.querySelector("input").onchange = e => { meshes[i].hidden = !e.target.checked; v.redraw(); };
    list.append(row);
  });
  return { v, meshes, ex };
}

export async function view3d(url, host) {
  const v = makeViewer(host);
  v.show([parseStl(await (await fetch(url)).arrayBuffer())]);
  return v;
}

// A chat / gallery card for a 3D model: preview picture, "Turn in 3D", "Edit in 3D", download
// Edit in 3D: a PicoGK / FreeCAD design as it is; a Python-code (Blender) design is first replayed into parts
const codeModel = m => m.recipe?.mode === "code" && !!m.recipe?.code;
export async function editableRecipe(r, name) {
  if (r?.mode !== "code") return r;
  const res = await fetch("/api/model3d/editable", { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ code: r.code, name }) });
  const j = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(j.detail || "This design can't be edited as parts.");
  return j.recipe;
}

export function model3dCard(m, h) {
  const size = (m.size_mm || []).map(x => Math.round(x)).join(" × ");
  const editable = (m.recipe && (!m.plugin || m.plugin === "picogk" || m.plugin === "freecad")) || codeModel(m);
  const box = document.createElement("div");
  box.className = "model3d";
  box.innerHTML = `<div class="m3view"><img src="${m.preview}" alt=""><button class="btn sm m3turn">Turn in 3D</button></div>
    <div class="m3meta"><div class="m3info"><b>${h(m.name || "3D model")}</b><span class="muted small">${size ? size + " mm" : ""}${m.triangles ? " · " + Number(m.triangles).toLocaleString() + " triangles" : ""}</span></div>
    ${editable ? `<button class="btn sm m3edit" title="Change it yourself: select, move, stretch and copy parts, add holes, dents and threads">Edit in 3D</button>` : ""}
    <button class="btn sm m3print" title="G-code for your 3D printer — sliced on this PC, no internet">🖨 Print</button>
    ${m.glb ? `<a class="btn sm" href="${m.glb}" download="${h((m.name || "model").replace(/[^\w -]/g, ""))}.glb" title="One file with colours, for other 3D apps (Blender, Windows 3D Viewer…)">GLB</a>` : ""}
    ${m.step ? `<a class="btn sm" href="${m.step}" download="${h((m.name || "model").replace(/[^\w -]/g, ""))}.step" title="The exact CAD file (FreeCAD, Fusion, CNC software) — holes and sizes exactly as designed">STEP</a>` : ""}
    ${m.parts ? `<a class="btn sm" href="${m.zip}" download>All parts (zip)</a>` : `<a class="btn sm" href="${m.stl}" download="${h((m.name || "model").replace(/[^\w -]/g, ""))}.stl">Download STL</a>`}</div>
    ${m.parts ? `<div class="m3panel"><div class="small">${m.parts.filter(p => !p.reference).length} printed parts · ${m.collisions?.length ? `<span class="fitbad">⚠ ${m.collisions.length} collision(s)</span>` : `<span class="fitok">✓ everything fits</span>`} — press Turn in 3D for each part</div></div>` : ""}`;
  const edit = async part => {  // the design saved next to the model is the full one (every part and hole)
    let r = m.recipe;
    try { const f = await fetch(m.stl.replace(/\.stl$/, ".json")); if (f.ok) r = await f.json(); } catch {}
    try { r = await editableRecipe(r?.mode === "code" ? r : codeModel(m) ? m.recipe : r, m.name); } catch (e) { return alert(e.message); }
    window.dispatchEvent(new CustomEvent("edit3d", { detail: { recipe: r, fromChat: true, ...(part != null ? { part } : {}) } }));
  };
  const menu = (e, v, meshes) => {  // right-click: edit it here, save its files, look at it
    let part = null;
    if (v && meshes && m.parts) {
      const hit = v.pick(e.clientX - v.canvas.getBoundingClientRect().left, e.clientY - v.canvas.getBoundingClientRect().top);
      const i = hit ? meshes.indexOf(hit.mesh) : -1;
      if (i >= 0) part = i;
    }
    const p = part != null ? m.parts[part] : null, nm = safeName(m.name);
    popMenu(e.clientX, e.clientY, [
      ...(editable ? [{ label: p ? `Edit “${p.name}” in 3D` : "Edit in 3D", act: () => edit(part) }, { sep: true }] : []),
      { label: p ? `🖨 Print “${p.name}” — G-code…` : "🖨 Print — G-code for my printer…", act: () => openPrint(m, part != null ? { part } : {}) },
      { label: "✂ Cut into pieces that fit my printer…", act: () => cutAndPrint(m) },
      { sep: true },
      ...[["↔", "left / right"], ["↕", "front / back"], ["⇅", "up / down"]].map(([a, w], k) => ({  // a left hand from a right one
        label: `⇋ Mirror copy ${a} ${w}`, act: () => window.dispatchEvent(new CustomEvent("mirror3d", { detail: { model: m, axis: k, inChat: !!box.closest("#log") } })),
      })),
      { sep: true },
      ...(p && !p.reference ? [{ label: `Save “${p.name}” (STL)`, act: () => download(p.stl, safeName(p.name) + ".stl") }] : []),
      m.parts ? { label: "Save all parts (zip)", act: () => download(m.zip, nm + ".zip") } : { label: "Save STL (to print)", act: () => download(m.stl, nm + ".stl") },
      ...(m.step ? [{ label: "Save STEP (CAD)", act: () => download(m.step, nm + ".step") }] : []),
      ...(m.glb ? [{ label: "Save GLB (colours)", act: () => download(m.glb, nm + ".glb") }] : []),
      ...(v ? [{ sep: true }, { label: "Reset the view", key: "double-click", act: () => v.canvas.dispatchEvent(new MouseEvent("dblclick")) }] : []),
    ]);
  };
  const open = async () => {
    const host = box.querySelector(".m3view"); host.innerHTML = "";
    if (m.parts) { const r = await viewAssembly(m, host, box.querySelector(".m3panel"), h); r.v.setTool({ menu: (pt, e) => menu(e, r.v, r.meshes) }); }
    else { const v = await view3d(m.view || m.stl, host); v.setTool({ menu: (pt, e) => menu(e, v, null) }); }
  };
  box.querySelector(".m3turn").onclick = open;
  box.querySelector("img").onclick = open;
  box.querySelector("img").oncontextmenu = e => { e.preventDefault(); menu(e, null, null); };
  const ed = box.querySelector(".m3edit");
  if (ed) ed.onclick = () => edit(null);
  box.querySelector(".m3print").onclick = () => openPrint(m);
  return box;
}
