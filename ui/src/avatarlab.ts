// Avatar Lab: compare Monkey design prototypes (GPT Image 2.6 Sunburst), pick a favorite,
// leave notes for the Blender modeling pass, and generate more ideas.
import { h, toast } from "./dom";
import type { Api } from "./bridge";
import { loadInto, startLoading } from "./loader";

interface Proto { id: string; title: string; direction: string; traits?: string; hero: string; sheet: string; fresh?: boolean }

function lightbox(src: string, title: string) {
  const box = h("div", { class: "lightbox", onclick: () => box.remove() },
    h("figure", {}, h("img", { src, alt: title }), h("figcaption", {}, title + " — click to close")));
  document.body.append(box);
}

export async function renderAvatarLab(card: HTMLElement, api: Api) {
  card.classList.add("lab");
  let protos: Proto[] = [];
  try {
    protos = await (await fetch("prototypes/index.json")).json();
  } catch {
    card.append(h("p", { class: "meta" }, "No prototypes bundled."));
    return;
  }
  const { value: state } = await loadInto(() => card, () => api.list_prototypes(),
    { what: "the Monkey designs", skel: "tiles", art: "monkey", failed: () => null });
  const grid = h("div", { class: "lab-grid" });

  const tile = (p: Proto) => {
    const fav = state.favorite === p.id;
    const notes = h("textarea", { rows: 2, placeholder: "Notes for the Blender model…" }, state.notes?.[p.id] ?? "");
    notes.addEventListener("change", () => api.save_prototype_note(p.id, notes.value));
    const star = h("button", { type: "button", class: `star ${fav ? "on" : ""}`, title: "Pick as favorite" }, fav ? "★ PICKED" : "☆ PICK");
    star.addEventListener("click", async () => {
      const s = await api.pick_prototype(p.id, notes.value);
      state.favorite = s.favorite;
      grid.querySelectorAll(".star").forEach((b) => { b.classList.remove("on"); b.textContent = "☆ PICK"; });
      star.classList.add("on");
      star.textContent = "★ PICKED";
      toast(`Favorite: ${p.title}`);
    });
    return h("div", { class: `lab-tile ${fav ? "fav" : ""} ${p.fresh ? "fresh" : ""}` },
      h("div", { class: "lab-num" }, p.fresh ? "NEW" : `#${p.id}`),
      h("img", { src: p.hero, alt: p.title, loading: "lazy", onclick: () => lightbox(p.hero, p.title) }),
      h("div", { class: "lab-title" }, p.title),
      h("div", { class: "lab-dir" }, p.direction),
      h("div", { class: "lab-actions" },
        star,
        p.sheet ? h("button", { type: "button", class: "ghost mini", onclick: () => lightbox(p.sheet, `${p.title}: model sheet`) }, "Model sheet") : null),
      notes);
  };
  const draw = () => grid.replaceChildren(...protos.map(tile));
  draw();

  // Generate more ideas with the design rules + your direction.
  const dir = h("input", { placeholder: "New direction, e.g. 'pirate captain with a banana-shaped hat'" });
  const refSel = h("select", {}, h("option", { value: "" }, "No reference"),
    ...protos.map((p) => h("option", { value: p.hero, selected: state.favorite === p.id }, `Base on #${p.id} ${p.title}`)));
  const go = h("button", { type: "button", class: "primary" }, "✨ Generate");
  go.addEventListener("click", async () => {
    if (!dir.value.trim()) return toast("Describe a direction first");
    go.disabled = true;
    go.textContent = "Generating… (~40s)";
    // a placeholder tile at the front of the grid, where the new picture will land
    const slot = h("div", { class: "lab-tile lab-gen-slot" });
    grid.prepend(slot);
    const ld = startLoading(slot, { what: "", art: "vine", skel: "tile",
      msgs: ["Painting a new Monkey…", "Still painting (about 40 seconds)…", "Adding the last bananas…", "Big pictures take a while. Almost there."] });
    let r: Awaited<ReturnType<Api["generate_prototypes"]>>;
    try { r = await api.generate_prototypes(dir.value, 1, refSel.value); } catch (e) { r = { ok: false, error: String(e) } as typeof r; }
    await new Promise<void>((done) => ld.done(done));
    slot.remove();
    go.disabled = false;
    go.textContent = "✨ Generate";
    if (!r.ok) return toast(`⚠ ${r.error}`);
    for (const img of r.images ?? []) {
      protos.unshift({ id: `new-${Date.now()}`, title: dir.value.slice(0, 40), direction: dir.value, hero: img.src, sheet: "", fresh: true });
    }
    draw();
  });

  card.append(
    h("p", { class: "meta" }, `8 prototypes made with ${state.model}. Pick a favorite and leave notes for the Blender model. Click an image to enlarge.`),
    grid,
    h("div", { class: "lab-gen" }, dir, refSel, go),
  );
  if (!state.has_key) card.append(h("p", { class: "meta" }, "Add an OpenAI API key in Settings to generate more."));
}
