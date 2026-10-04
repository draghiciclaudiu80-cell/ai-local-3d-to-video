// The build-project card in a chat: a device made part by part. Shows the checklist (✓ built, ▶ next, ○ to do), the buy
// list, and the buttons to build the next part or assemble. The app keeps the plan in this chat, so a big build finishes
// on a small model. `h` = { next, assemble, close } handlers (chat.js wires them to send / the API).
import { button, el, esc } from "./core.js";

const MARK = { built: "✓", building: "▶", skipped: "—" };

export function projectCard(c, h = {}) {
  const box = el("div", "projcard");
  const pct = c.parts.length ? Math.round(100 * c.done / c.parts.length) : 0;
  box.append(el("div", "projhead",
    `🏗 <b>${esc(c.name)}</b><span class="projcount">${c.done}/${c.parts.length} parts${c.status === "done" ? " · done" : ""}</span>`));
  if (c.goal) box.append(el("div", "small muted", esc(c.goal)));
  const bar = el("div", "projbar");
  bar.append(Object.assign(el("div", "projbarfill"), { style: `width:${pct}%` }));
  box.append(bar);
  const list = el("div", "projlist");
  for (const p of c.parts) {
    const row = el("div", "projrow " + p.status);
    const size = p.size_mm ? ` · ${p.size_mm.join(" × ")} mm` : "";
    row.append(el("span", "projmark", MARK[p.status] || "○"));
    row.append(el("span", "projname", `${p.n}. ${esc(p.name)}${size}`));
    if (p.status === "building") row.append(el("span", "projtag", "building…"));
    if (c.next && p.n === c.next.n && p.status !== "building") row.append(el("span", "projtag next", "next"));
    list.append(row);
  }
  box.append(list);
  if (c.buy?.length) box.append(el("div", "projbuy", `🛒 <b>To buy:</b> ${esc(c.buy.join(", "))}`));
  const row = el("div", "projbtns");
  if (c.next && h.next) row.append(button(`▶ Build part ${c.next.n}: ${esc(c.next.name)}`, "primary small", () => h.next()));
  if (c.done && h.assemble) row.append(button(c.next ? "🧩 Assemble so far" : "🧩 Assemble & buy list", "small", () => h.assemble()));
  if (h.close) row.append(button("✕ Close project", "ghost small", () => h.close()));
  if (row.childElementCount) box.append(row);
  if (c.log?.length) {
    const d = el("details", "projlog", "<summary>Project log</summary>");
    c.log.forEach(l => d.append(el("div", "small muted mono", esc(l))));
    box.append(d);
  }
  return box;
}

// Replace the project card already in a message bubble (several updates can arrive in one turn), or add one before `body`.
export function putProject(d, card, body, h) {
  d.querySelector(".projcard")?.remove();
  d.insertBefore(projectCard(card, h), body || null);
}
