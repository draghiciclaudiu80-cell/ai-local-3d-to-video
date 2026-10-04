import { $, api, button, el, esc, icon, onPage, tabs } from "./core.js";
import { editableRecipe, view3d, viewAssembly } from "./viewer3d.js";
import { openPaper, openPrint } from "./print3d.js";

const HINT = {
  movie: "Finished movies with sound.",
  clip: "Short clips — movie scenes and single videos.",
  image: "Generated images. Click one to view it large.",
  model: "3D models (PicoGK). Click one to turn it in 3D; Save downloads the STL for 3D printing.",
};
const NAME = { movie: "movies", clip: "clips", image: "images", model: "3D models" };
const KEEP = { movie: "Clips and images are not affected.", clip: "Finished movies are not affected.", image: "Movies and clips are not affected.", model: "Pictures and videos are not affected." };
// (no "Join selected" button / tick boxes any more — the user didn't want them; videos are joined from the chat)
const folder = tabs("galTabs", "galFolder", "movie", () => load());
const inFolder = (g, f) => f === "clip" ? g.kind === "video" || g.kind === "clip" : g.kind === f;

async function load() {
  const f = folder();
  const all = await api("/api/gallery");
  const counts = { movie: 0, clip: 0, image: 0, model: 0 };
  all.forEach(g => { for (const k in counts) if (inFolder(g, k)) counts[k]++; });
  $("galTabs").querySelectorAll("button").forEach(b => b.textContent = `${{ movie: "Movies", clip: "Clips", image: "Images", model: "3D" }[b.dataset.t]} (${counts[b.dataset.t]})`);
  $("galHint").textContent = HINT[f];
  $("galClear").hidden = !counts[f];
  $("galClear").innerHTML = `${icon("trash")}Delete all ${NAME[f]}`;
  const items = all.filter(g => inFolder(g, f));
  const grid = $("galGrid");
  grid.innerHTML = items.length ? "" : `<div class="empty" style="grid-column:1/-1">Nothing here yet.</div>`;
  for (const g of items) {
    const t = el("div", "tile");
    if (g.kind === "model") {  // a 3D model: its preview picture; click to turn it in 3D
      const img = Object.assign(el("img"), { src: `/media/${g.file.replace(/\.stl$/, ".png")}`, loading: "lazy", alt: g.prompt, title: "Click to turn it in 3D" });
      img.onclick = async () => {  // a device (several parts) opens with every part in its colour
        const v = el("div", "m3view"); img.replaceWith(v);
        const parts = await fetch(`/media/${g.file.replace(/\.stl$/, ".parts.json")}`).then(r => r.ok ? r.json() : null).catch(() => null);
        const light = `/media/${g.file.replace(/\.stl$/, ".view.stl")}`;
        if (parts) {  // a device: the same options as in the chat — explode / assemble, parts, downloads, fit check
          const panel = el("div", "m3panel");
          v.after(panel);
          viewAssembly(parts, v, panel, esc);
        }
        else view3d((await fetch(light, { method: "HEAD" }).then(r => r.ok).catch(() => false)) ? light : `/media/${g.file}`, v);
      };
      t.append(img);
      t.dataset.recipe = `/media/${g.file.replace(/\.stl$/, ".json")}`;
    } else if (g.kind === "image") {
      const img = Object.assign(el("img"), { src: `/media/${g.file}`, loading: "lazy", alt: g.prompt });
      img.onclick = () => { $("lightbox").hidden = false; $("lightbox").firstChild.src = img.src; };
      t.append(img);
    } else {
      t.append(Object.assign(el("video"), { src: `/media/${g.file}`, controls: true, preload: "metadata" }));
    }
    const meta = el("div", "meta", `<span title="${esc(g.prompt)}">${esc(g.prompt || "(untitled)")}</span>`);
    const acts = el("div", "acts");
    if (g.kind === "image") acts.append(button(`${icon("print")}Print`, "sm", () => openPaper({ kind: "image", url: `/media/${g.file}`, name: (g.prompt || "picture").slice(0, 40) })));
    if (g.kind === "model") acts.append(button(`${icon("print")}3D print`, "sm", async () => {
      let m = { name: g.prompt || "model", stl: `/media/${g.file}` };
      try { const f = await fetch(`/media/${g.file.replace(/\.stl$/, ".parts.json")}`); if (f.ok) m = { ...m, ...(await f.json()) }; } catch {}
      openPrint(m);
    }));
    if (g.kind === "model") acts.append(button("Edit in 3D", "sm", async () => {
      try {
        let rec = await (await fetch(t.dataset.recipe)).json();
        if (rec.mode === "code") {  // a Python-code design: its code replayed into parts
          try { rec = await editableRecipe(rec, g.prompt); } catch (e) { return alert(e.message); }
        } else if (rec.engine === "blender" || rec.engine === "mesh")
          return alert("This one is pieces cut / mirrored from a mesh — edit the original instead, or ask in the chat.");
        window.dispatchEvent(new CustomEvent("edit3d", { detail: { recipe: rec } }));
      }
      catch { alert("This model was made before designs were saved — ask the chat to make it again."); }
    }));
    const save = Object.assign(el("a", "btn sm", `${icon("save")}Save`), { href: `/media/${g.file}`, download: g.file });
    if (g.kind === "model") fetch(`/media/${g.file.replace(/\.stl$/, ".parts.json")}`, { method: "HEAD" })
      .then(r => { if (r.ok) Object.assign(save, { href: `/media/${g.file.replace(/\.stl$/, ".zip")}`, download: g.file.replace(/\.stl$/, ".zip") }); }).catch(() => {});
    acts.append(save,
      button(`${icon("trash")}Delete`, "sm danger", async () => {
        if (!confirm("Delete this permanently?")) return;
        await api(`/api/gallery/${g.id}`, { method: "DELETE" }); load();
      }));
    t.append(meta, acts);
    grid.append(t);
  }
}
$("lightbox").onclick = () => { $("lightbox").hidden = true; };
$("galClear").onclick = async () => {  // "Delete all movies / clips / images" — whichever tab is open
  const f = folder(), items = (await api("/api/gallery")).filter(g => inFolder(g, f));
  if (!items.length || !confirm(`Delete all ${items.length} ${NAME[f]} permanently? ${KEEP[f]}`)) return;
  const b = $("galClear");
  b.disabled = true;
  let n = 0;
  try { for (const g of items) { await api(`/api/gallery/${g.id}`, { method: "DELETE" }); b.textContent = `Deleting… ${++n}/${items.length}`; } }
  catch (e) { alert(e.message); }
  b.disabled = false; load();
};

onPage("gallery", load);
