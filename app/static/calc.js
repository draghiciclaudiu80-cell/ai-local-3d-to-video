// A calculator's answer in the chat (engineering, fluids, electronics, airgun, parts inventory): the exact numbers on a
// card — the AI's sentences under it explain them. Copy puts the card's text on the clipboard.
import { button, el, esc } from "./core.js";

const ICONS = { engineering: "🔧", fluids: "💧", electronics: "🔌", airgun: "🎯", inventory: "📦", robotics: "🦾" };
const BAD = /^(NOT|TOO|OVER|Far too|The wheels SLIP|It sinks|Missing|Needs a heatsink|Nothing|It can't)/;

export function calcCard(c) {
  const box = el("div", "calccard");
  const head = el("div", "calchead", `${ICONS[c.group] || "🧮"} <b>${esc(c.title || "Calculator")}</b>`);
  const copy = button("Copy", "ghost small", () => {
    const text = [c.title, ...(c.lines || []).map(([k, v]) => `${k}: ${v}`), c.verdict || "", ...(c.warnings || [])]
      .filter(Boolean).join("\n");
    navigator.clipboard?.writeText(text).then(() => { copy.textContent = "Copied"; setTimeout(() => (copy.textContent = "Copy"), 1200); });
  });
  head.append(copy);
  box.append(head);
  const rows = el("div", "calclines");
  for (const [k, v] of c.lines || []) {
    const s = String(v ?? "");
    rows.append(el("div", "calck", esc(k)));
    rows.append(s.includes("\n") ? el("pre", "calcv calcpre", esc(s.trim())) : el("div", "calcv", esc(s)));
  }
  if ((c.lines || []).length) box.append(rows);
  if (c.picture) box.append(Object.assign(el("img", "calcimg"), { src: c.picture, alt: c.title || "", loading: "lazy" }));
  if (c.verdict) box.append(el("div", "calcverdict " + (BAD.test(c.verdict) ? "bad" : "good"), esc(c.verdict)));
  (c.warnings || []).forEach(w => box.append(el("div", "calcwarn", "⚠ " + esc(w))));
  if (c.missing?.length) box.append(el("div", "calcmiss", "Still needed: " + esc(c.missing.join("; "))));
  const more = [...(c.notes || []), ...(c.assumed?.length ? ["Assumed (you didn't say): " + c.assumed.join("; ")] : [])];
  if (more.length) {
    const d = el("details", "calcmore", `<summary>Notes${c.assumed?.length ? " and assumptions" : ""}</summary>`);
    more.forEach(n => d.append(el("div", "small muted", esc(n))));
    box.append(d);
  }
  return box;
}
