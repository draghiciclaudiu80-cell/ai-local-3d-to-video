"""Airgun calculators (like ChairGun / MERO / PCPFill): muzzle energy, the velocity for an energy limit, a trajectory
table (path, holdover, velocity, energy, wind drift; best zero for a kill zone) from the pellet's G1 ballistic
coefficient, and PCP filling from a scuba / carbon tank. For target shooting and pest control — energy limits for
airguns differ by country."""
import math
import re

from units import G, Inputs, Out, claim, fmt, parse

GRAIN = 6.479891e-5  # kg
FTLB = 1.35582  # J
# standard G1 drag coefficient against Mach number
G1 = [(0.0, .2629), (0.05, .2558), (0.10, .2487), (0.15, .2413), (0.20, .2344), (0.25, .2278), (0.30, .2214),
      (0.35, .2155), (0.40, .2104), (0.45, .2061), (0.50, .2032), (0.55, .2020), (0.60, .2034), (0.70, .2165),
      (0.725, .2230), (0.75, .2313), (0.775, .2417), (0.80, .2546), (0.825, .2706), (0.85, .2901), (0.875, .3136),
      (0.90, .3415), (0.925, .3734), (0.95, .4084), (0.975, .4448), (1.0, .4805), (1.025, .5136), (1.05, .5427),
      (1.075, .5677), (1.10, .5883), (1.125, .6053), (1.15, .6191), (1.20, .6393), (1.25, .6518), (1.30, .6589),
      (1.35, .6621), (1.40, .6625), (1.50, .6573), (1.60, .6474), (1.80, .6210), (2.00, .5934)]
CALIBRE = {".177": 4.5, ".20": 5.0, ".22": 5.5, ".25": 6.35, ".30": 7.62, ".357": 9.0, ".45": 11.43, ".50": 12.7}


def cd_g1(mach: float) -> float:
    if mach <= G1[0][0]:
        return G1[0][1]
    for (m0, c0), (m1, c1) in zip(G1, G1[1:]):
        if mach <= m1:
            return c0 + (c1 - c0) * (mach - m0) / (m1 - m0)
    return G1[-1][1]


def _bare(inp: Inputs, names) -> tuple:
    r = inp._raw(names)
    if r is None:
        return None, ""
    s = str(r[0]).strip()
    m = re.match(r"^\s*(\d+(?:[.,]\d+)?)\s*(.*)$", s)
    return (float(m.group(1).replace(",", ".")), (m.group(2) or r[1] or "").strip().lower()) if m else (None, "")


def velocity(inp: Inputs, need=True):
    """Muzzle velocity in m/s; a bare number above 400 is fps (airgun speeds are 150–330 m/s, 500–1100 fps)."""
    v, u = _bare(inp, ["velocity", "muzzle_velocity", "speed", "fps", "mv", "v"])
    if v is not None:
        if not u:
            u = "fps" if (inp.has("fps") or v > 400) else "m/s"
        return parse(f"{v} {u}", "speed")
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*(fps|ft/s|m/s|mps)\b", inp.question, re.I)
    if m:
        claim(inp.qs, m.start(1))
        return parse(f"{m.group(1)} {m.group(2)}", "speed")
    if need:
        inp.missing.append("the muzzle velocity (fps or m/s, from a chronograph)")
    return None


def pellet_mass(inp: Inputs, need=True):
    """Pellet / slug weight in kg; a bare number ≥ 4 is grains (pellets 7–35 gr = 0.5–2.3 g)."""
    v, u = _bare(inp, ["pellet_weight", "pellet", "weight", "mass", "grains", "slug", "projectile"])
    if v is not None:
        if not u:
            u = "gr" if (inp.has("grains") or v >= 4) else "g"
        return parse(f"{v} {u}", "mass")
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*(gr|grains?|grain|g|grams?)\b", inp.question, re.I)
    if m:
        u = "gr" if m.group(2).lower().startswith("gr") and m.group(2).lower() not in ("grams", "gram") else "g"
        claim(inp.qs, m.start(1))
        return parse(f"{m.group(1)} {u}", "mass")
    if need:
        inp.missing.append("the pellet weight (grains or grams)")
    return None


def energy(inp: Inputs) -> dict:
    o = Out()
    m = pellet_mass(inp)
    v = velocity(inp, need=False)
    lim = inp.num(["limit", "energy_limit", "max_energy", "energy"], "energy", "energy limit", text_ok=False)
    if lim is None:
        mm = re.search(r"(\d+(?:[.,]\d+)?)\s*(j|joules?|ft[\s.-]?lbs?|fpe|ft·lb)\b", inp.question, re.I)
        if mm:
            val = float(mm.group(1).replace(",", "."))
            lim = val if mm.group(2).lower().startswith("j") else val * FTLB
        else:
            lim = None
    else:
        lim = lim * 3600  # Wh -> J
    if not m:
        return o.done()
    o.add("Pellet", f"{fmt(m / GRAIN)} gr = {fmt(m * 1000)} g")
    if v:
        e = 0.5 * m * v * v
        o.add("Muzzle velocity", f"{fmt(v)} m/s = {fmt(v / 0.3048)} fps")
        o.add("Muzzle energy", f"{fmt(e)} J = {fmt(e / FTLB)} ft·lb")
        o.add("Momentum", f"{fmt(m * v * 1000)} g·m/s")
        if not lim:
            o.add("Against common limits", "; ".join(f"{n} ({fmt(l)} J): {'OVER' if e > l else 'under'}" for n, l in
                                                    (("UK rifle, no certificate", 16.27), ("UK pistol", 8.13),
                                                     ("Germany, F mark", 7.5))))
    if lim:
        vmax = math.sqrt(2 * lim / m)
        o.add(f"Fastest for {fmt(lim)} J ({fmt(lim / FTLB)} ft·lb)", f"{fmt(vmax)} m/s = {fmt(vmax / 0.3048)} fps with this pellet")
        if v:
            o.verdict = f"{'Under' if 0.5 * m * v * v <= lim else 'OVER'} the {fmt(lim)} J limit ({fmt(0.5 * m * v * v)} J)."
    if not (v or lim):
        inp.missing.append("the velocity (or the energy limit)")
    o.note("Energy limits differ by country (e.g. UK 12 ft·lb rifles / 6 ft·lb pistols without a certificate, Germany 7.5 J with the F mark) — check your local law.")
    return o.done()


def _air(temp_c: float, alt_m: float, pressure_pa=None):
    p = pressure_pa or 101325 * (1 - 2.25577e-5 * alt_m) ** 5.25588
    tk = temp_c + 273.15
    return p / (287.05 * tk), 331.3 * math.sqrt(1 + temp_c / 273.15)


def _fly(v0: float, bc_si: float, rho: float, c: float, xmax: float, wind: float, dt: float = 0.0004):
    """Flat launch (bore level): [(x, drop y, drift z, speed, time)] every step. Small angles add x·tanθ later."""
    x = y = z = t = 0.0
    vx, vy, vz = v0, 0.0, 0.0
    out = [(0.0, 0.0, 0.0, v0, 0.0)]

    def acc(vx_, vy_, vz_):
        rx, rz = vx_, vz_ - wind  # air-relative velocity (crosswind along z)
        vr = math.sqrt(rx * rx + vy_ * vy_ + rz * rz)
        k = rho * cd_g1(vr / c) * math.pi / (8 * bc_si)
        return -k * vr * rx, -k * vr * vy_ - G, -k * vr * rz
    while x < xmax and t < 5:
        ax, ay, az = acc(vx, vy, vz)  # midpoint (RK2)
        mx, my, mz = vx + ax * dt / 2, vy + ay * dt / 2, vz + az * dt / 2
        ax, ay, az = acc(mx, my, mz)
        x, y, z = x + mx * dt, y + my * dt, z + mz * dt
        vx, vy, vz = vx + ax * dt, vy + ay * dt, vz + az * dt
        t += dt
        out.append((x, y, z, math.sqrt(vx * vx + vy * vy + vz * vz), t))
    return out


def _at(path, x):
    for a, b in zip(path, path[1:]):
        if b[0] >= x:
            f = (x - a[0]) / max(b[0] - a[0], 1e-9)
            return tuple(a[i] + f * (b[i] - a[i]) for i in range(5))
    return path[-1]


def trajectory(inp: Inputs) -> dict:
    o = Out()
    v0 = velocity(inp)
    m = pellet_mass(inp)
    bc = inp.num(["bc", "ballistic_coefficient", "g1"], "number", "ballistic coefficient", text_ok=False)
    mm = re.search(r"\bbc\s*(?:of|=|:|is)?\s*(0?[.,]\d+)", inp.question, re.I)
    if bc is None and mm:
        bc = float(mm.group(1).replace(",", "."))
        claim(inp.qs, mm.start(1))
    cal = re.search(r"(?<![\d.])(\.177|\.20|\.22|\.25|\.30|\.357|\.45|\.50)\b", inp.question)
    if cal:
        claim(inp.qs, cal.start(1))
    if bc is None:
        bc = 0.025
        inp.assumed.append("BC 0.025 (a typical domed pellet — give the real one from the tin or the maker's site for good numbers)")
    if not (v0 and m):
        return o.done()
    imperial = bool(re.search(r"\byards?\b|\byds?\b", inp.question.lower())) or inp.text(["units"], "").startswith("imp")
    unit_l = "yd" if imperial else "m"
    lunit = 0.9144 if imperial else 1.0
    sight = inp.num(["scope_height", "sight_height", "height_over_bore", "scope"], "length", "scope height", default=0.045,
                    hints=["scope height", "sight height", "over bore", "scope", "height", "sight"], show="45 mm", lone=False)
    zero = inp.num(["zero", "zero_range", "zeroed_at", "zero_distance"], "length", "zero range", default=30 * lunit,
                   hints=["zero", "zeroed", "sighted", "zeroing"], show=f"30 {unit_l}", lone=False)
    rmax = inp.num(["max_range", "range", "distance", "to"], "length", "longest range", default=50 * lunit,
                   hints=["out to", "range", "max", "distance", "up to", "to"], show=f"50 {unit_l}", lone=False)
    step = inp.num(["step", "every"], "length", "step", default=(10 if imperial else 5) * lunit, text_ok=False,
                   show=f"{10 if imperial else 5} {unit_l}")
    wind = inp.num(["wind", "crosswind", "wind_speed"], "speed", "crosswind", hints=["wind", "breeze", "crosswind"], lone=False)
    show_wind = wind if wind else 2.0
    temp = inp.num(["temperature", "temp"], "temp", "temperature", default=15.0, hints=["°c", "temperature", "degrees"], show="15 °C")
    alt = inp.num(["altitude", "elevation"], "length", "altitude", default=0.0, text_ok=False, show="sea level")
    kz = inp.num(["kill_zone", "killzone", "target_size", "vital_zone"], "length", "kill zone", default=0.025, hints=["kill zone", "killzone", "vital"], show="25 mm")
    rho, c = _air(temp, alt)
    bc_si = bc * 703.0696
    path = _fly(v0, bc_si, rho, c, max(rmax, zero) + step, show_wind)
    pz = _at(path, zero)
    tan_t = (sight - pz[1]) / zero  # bore angled up so the pellet crosses the line of sight at the zero range
    e0 = 0.5 * m * v0 * v0
    o.add("Setup", f"{fmt(m / GRAIN)} gr at {fmt(v0 / 0.3048)} fps ({fmt(v0)} m/s), BC {fmt(bc, 3)} (G1), scope {fmt(sight * 1000)} mm, "
                   f"zero {fmt(zero / lunit)} {unit_l}, {fmt(temp)} °C")
    o.add("Muzzle energy", f"{fmt(e0)} J ({fmt(e0 / FTLB)} ft·lb)")
    rows, r = [], step
    while r <= rmax + 1e-9:
        x, y, zd, sp, t = _at(path, r)
        hp = x * tan_t + y - sight  # + = above the line of sight
        mrad = -hp / x * 1000
        hold = "aim dead on" if abs(hp) < 0.002 else f"aim {fmt(abs(hp) * (39.37 if imperial else 100), 2)} {'in' if imperial else 'cm'} {'high' if hp < 0 else 'low'}"
        rows.append(f"{fmt(r / lunit)} {unit_l}: {'+' if hp >= 0 else '−'}{fmt(abs(hp) * 1000, 2)} mm → {hold} ({mrad:+.1f} mrad / {mrad * 3.4377:+.1f} MOA); "
                    f"{fmt(sp / 0.3048)} fps, {fmt(0.5 * m * sp * sp)} J, {fmt(t, 2)} s; wind {fmt(abs(zd) * 1000, 2)} mm")
        r += step
    o.add("Range table", "\n" + "\n".join(rows))
    o.add("Wind", f"drift for a {fmt(show_wind)} m/s ({fmt(show_wind * 2.237)} mph) full crosswind" + ("" if wind else " (example)"))
    # kill zone: where the pellet stays within ±kz/2 of the line of sight with this zero; and the best zero for it
    def band(tt):
        inside = [p[0] for p in path[1:] if abs(p[0] * tt + p[1] - sight) <= kz / 2]
        near = next((p[0] for p in path[1:] if abs(p[0] * tt + p[1] - sight) <= kz / 2), None)
        far = None
        if near is not None:
            for p in path[1:]:
                if p[0] > near and abs(p[0] * tt + p[1] - sight) > kz / 2:
                    far = p[0]
                    break
        return near, far or (inside[-1] if inside else None)
    near, far = band(tan_t)
    if near is not None and far:
        o.add(f"Kill zone ±{fmt(kz * 500)} mm", f"from {fmt(near / lunit)} to {fmt(far / lunit)} {unit_l} with this zero")
    best = None
    for zz in [lunit * k for k in range(8, int(min(rmax, 80 * lunit) / lunit) + 1)]:
        tt = (sight - _at(path, zz)[1]) / zz
        if max(p[0] * tt + p[1] - sight for p in path[1:]) > kz / 2:
            continue
        nb, fb = band(tt)
        if nb is not None and fb and (best is None or fb > best[2]):
            best = (zz, nb, fb)
    if best:
        tt = (sight - _at(path, best[0])[1]) / best[0]
        rel = [(p[0], p[0] * tt + p[1] - sight) for p in path[1:]]
        cross = [a[0] for a, b in zip(rel, rel[1:]) if (a[1] < 0) != (b[1] < 0)]
        far_z = cross[-1] if cross else best[0]
        o.add("Best zero for that kill zone", f"{fmt(far_z / lunit)} {unit_l}"
              + (f" (the pellet also crosses the crosshair at {fmt(cross[0] / lunit)} {unit_l})" if len(cross) > 1 else "")
              + f" → within ±{fmt(kz * 500)} mm from {fmt(best[1] / lunit)} to {fmt(best[2] / lunit)} {unit_l}")
    o.note("G1 drag model; pellet BCs fall a little at long range — check against real groups at 2–3 distances and adjust the BC.")
    return o.done()


def pcp_fill(inp: Inputs) -> dict:
    o = Out()
    vt = inp.num(["tank_volume", "tank", "bottle", "scuba", "cylinder_volume", "tank_size"], "volume", "tank size", need=True,
                 hints=["tank", "bottle", "scuba", "cylinder", "carbon", "litre", "liter"])
    pt = inp.num(["tank_pressure", "tank_bar", "bottle_pressure"], "pressure", "tank pressure", need=True, hints=["tank", "bottle", "scuba", "at"])
    vg_raw = inp._raw(["reservoir", "gun_volume", "reservoir_volume", "gun_reservoir", "cylinder", "gun"])
    vg = None
    if vg_raw:
        vg = parse(vg_raw[0], "volume", vg_raw[1] or "ml")
    if vg is None:
        mm = re.search(r"(\d+(?:[.,]\d+)?)\s*(cc|ml|cm3)\b", inp.question, re.I)
        vg = parse(f"{mm.group(1)} {mm.group(2)}", "volume") if mm else None
    if vg is None:
        inp.missing.append("the gun's reservoir size (cc)")
    pf = inp.num(["fill_pressure", "fill_to", "fill"], "pressure", "fill pressure", hints=["fill to", "fill", "full"])
    pr = inp.num(["refill_pressure", "refill_at", "empty", "refill"], "pressure", "refill pressure", hints=["refill", "down to", "empty", "drops to"])
    if not (vt and pt and vg):
        return o.done()
    if not pf:
        pf = 200e5
        inp.assumed.append("fill to 200 bar")
    if pr is None:
        pr = 100e5
        inp.assumed.append("refill at 100 bar")
    if pt > 310e5:
        o.warn("Above 310 bar is beyond common scuba / carbon tanks — check the number.")
    p, fills, log = pt, 0, []
    while fills < 500:
        need = (pf - pr) * vg / vt
        if p - need < pf:
            break
        p -= need
        fills += 1
        if fills <= 3 or fills % 10 == 0:
            log.append(f"after {fills}: tank {fmt(p / 1e5)} bar")
    eq = (p * vt + pr * vg) / (vt + vg)
    o.add("Full fills", f"{fills} fills from {fmt(pr / 1e5)} to {fmt(pf / 1e5)} bar (tank {fmt(vt * 1000)} l at {fmt(pt / 1e5)} bar, gun {fmt(vg * 1e6)} cc)")
    o.add("Tank pressure", (", ".join(log) + "; " if log else "") + f"after the last full fill {fmt(p / 1e5)} bar")
    o.add("Then a part fill", f"the gun only gets to {fmt(eq / 1e5)} bar")
    shots = inp.num(["shots", "shots_per_fill"], "count", "shots per fill", hints=["shots"])
    per = inp.num(["bar_per_shot", "drop_per_shot"], "pressure", "pressure drop per shot", text_ok=False)
    if not shots and per:
        shots = (pf - pr) / per
    if shots:
        o.add("Shots", f"{fmt(shots)} per fill → about {fmt(shots * fills)} shots from the tank")
    o.note("Fill slowly (the air heats up and the gauge drops a little after cooling), never above the gun's rated pressure; "
           "tanks need regular inspections. Ideal-gas estimate — real air above 200 bar gives ~5–10 % fewer fills.")
    return o.done()


CALCS = {
    "energy": (energy, "Airgun muzzle energy / velocity for an energy limit",
               "energy muzzle energy joules ft-lb ftlb fpe fps grains pellet chrono chronograph velocity limit energie"),
    "trajectory": (trajectory, "Airgun trajectory: drop, holdover, kill zone, wind (ChairGun-style)",
                   "trajectory holdover hold over drop zero zeroed scope mildot mil-dot mrad moa ballistic bc kill zone range table chairgun mero wind drift"),
    "pcp_fill": (pcp_fill, "PCP filling from a scuba / carbon tank (PCPFill-style)",
                 "pcp fill fills scuba tank carbon bottle buddy bottle reservoir refill cylinder bar air rifle umplere"),
}
