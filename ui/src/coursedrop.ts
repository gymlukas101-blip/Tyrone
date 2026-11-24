// "I dropped this class": the confirm that names the class and what goes, the "Removed … Undo" toast, and the
// Hidden classes list in Settings → Accounts. Python decides what belongs to the class (monkey/integrations/courses.py);
// this file only shows it. Local Monkey data only: nothing changes on Canvas.
import { h, toast } from "./dom";
import { busyButton } from "./loader";
import { enter, leave, pop } from "./motion";
import { undoToast } from "./assignments";

export interface CourseRef { key: string; name: string; full?: string }
export interface DropPreview {
  ok: boolean; error?: string; key: string; name: string; full?: string; assignments: number;
  todos: { id: string; text: string }[]; token: string; say?: string;
}
export interface DropResult {
  ok: boolean; error?: string; action?: "dropped" | "restored"; key: string; name: string; full?: string;
  assignments: number; todos: { id: string; text: string }[]; say?: string;
}
export interface HiddenCourse { key: string; name: string; full?: string; hidden_at: string; assignments: number; todos: number }
export interface CourseApi {
  course_drop_preview(key: string): Promise<DropPreview>;
  course_drop(key: string, token: string): Promise<DropResult>;
  course_undrop(key: string): Promise<DropResult>;
  hidden_courses(): Promise<{ ok: boolean; error?: string; items: HiddenCourse[] }>;
}

let api: CourseApi | null = null;
let changed: (r: DropResult) => void = () => {};

/** main.ts: the API and what to refresh after a class is hidden or shown again (Homework, To-do, Today). */
export function initCourseDrop(a: CourseApi, onChanged: (r: DropResult) => void) { api = a; changed = onChanged; }

const n = (k: number, word: string) => `${k} ${word}${k === 1 ? "" : "s"}`;
export const removedText = (r: { name: string; assignments: number; todos: unknown[] }) =>
  `Removed ${n(r.assignments, `${r.name} assignment`)} and ${n(r.todos.length, "to-do")}`;

// ------------------------------------------------------------------ the ⋯ menu on a course group
let openMenu: HTMLElement | null = null;
function closeMenu() {
  const m = openMenu;
  openMenu = null;
  if (!m) return;
  document.removeEventListener("pointerdown", outside, true);
  document.removeEventListener("keydown", onKey, true);
  leave(m, "fade");
  (m as any)._btn?.setAttribute("aria-expanded", "false");
}
function outside(e: Event) { if (openMenu && !openMenu.contains(e.target as Node) && e.target !== (openMenu as any)._btn) closeMenu(); }
function onKey(e: KeyboardEvent) {
  if (e.key !== "Escape" || !openMenu) return;
  e.preventDefault(); e.stopPropagation();
  const b = (openMenu as any)._btn as HTMLElement | undefined;
  closeMenu();
  b?.focus();
}

/** The "⋯" button of a course group in Homework: opens a one-item menu, "I dropped this class". */
export function courseMoreButton(c: CourseRef): HTMLButtonElement {
  const btn = h("button", {
    type: "button", class: "ghost mini cd-more", "aria-haspopup": "menu", "aria-expanded": "false",
    "aria-label": `More for ${c.name}`, title: `More for ${c.name}`,
  }, "⋯") as HTMLButtonElement;
  btn.addEventListener("click", (e) => {
    e.stopPropagation();
    if (openMenu && (openMenu as any)._btn === btn) { closeMenu(); return; }
    closeMenu();
    const item = h("button", { type: "button", role: "menuitem", class: "cd-item" },
      h("span", { class: "cd-item-ico", "aria-hidden": "true" }, "🎒"), "I dropped this class");
    const menu = h("div", { class: "cd-menu", role: "menu", "aria-label": c.name }, item);
    (menu as any)._btn = btn;
    item.addEventListener("click", () => { closeMenu(); void askDropCourse(c, btn); });
    const host = btn.closest("dialog[open]") ?? document.body;
    host.append(menu);
    const r = btn.getBoundingClientRect(), w = Math.max(200, menu.offsetWidth);
    menu.style.left = `${Math.max(8, Math.min(window.innerWidth - w - 8, r.right - w))}px`;
    menu.style.top = `${Math.min(window.innerHeight - menu.offsetHeight - 8, r.bottom + 6)}px`;
    openMenu = menu;
    btn.setAttribute("aria-expanded", "true");
    enter(menu, "drop");
    item.focus();
    document.addEventListener("pointerdown", outside, true);
    document.addEventListener("keydown", onKey, true);
  });
  return btn;
}

// ------------------------------------------------------------------ the confirm
let dlg: HTMLDialogElement | null = null;

/** The ⋯ menu's "I dropped this class": ask Python what would go, then the confirm. */
export async function askDropCourse(c: CourseRef, opener?: HTMLButtonElement) {
  if (!api) return;
  let p: DropPreview;
  try {
    p = opener ? await busyButton(opener, () => api!.course_drop_preview(c.key), "Checking…") : await api.course_drop_preview(c.key);
  } catch (e) { p = { ok: false, error: String(e) } as DropPreview; }
  if (!p.ok) { toast(`⚠ ${p.error ?? "Couldn't check that class."}`); return; }
  confirmDrop(p);
}

/** "Hide MKTG 777 everywhere? 6 assignments, 2 to-dos" with Hide it / Keep it. Also opened by Monkey (voice/chat). */
export function confirmDrop(p: DropPreview) {
  if (!dlg) {
    dlg = h("dialog", { class: "cd-dlg", "aria-labelledby": "cd-title", "aria-describedby": "cd-q" }) as HTMLDialogElement;
    document.body.append(dlg);
  }
  const d = dlg;
  const hide = h("button", { type: "button", class: "primary cd-hide" }, "Hide it") as HTMLButtonElement;
  const keep = h("button", { type: "button", class: "ghost cd-keep", onclick: () => d.close() }, "Keep it");
  const todoList = p.todos.length
    ? h("ul", { class: "cd-todos", "aria-label": "To-dos that will be archived" },
        ...p.todos.slice(0, 5).map((t) => h("li", {}, t.text)),
        p.todos.length > 5 ? h("li", { class: "meta" }, `and ${p.todos.length - 5} more`) : null)
    : null;
  d.dataset.key = p.key;
  d.replaceChildren(h("div", { class: "cd-box" },
    h("header", {}, h("span", { class: "cd-ico", "aria-hidden": "true" }, "🎒"),
      h("h3", { id: "cd-title" }, `Dropped ${p.name}?`)),
    h("p", { id: "cd-q", class: "cd-q" }, "Hide ", h("strong", {}, p.name), p.full ? ` (${p.full})` : "", " everywhere in Monkey?"),
    h("div", { class: "cd-counts" },
      h("div", { class: "cd-count" }, h("strong", {}, String(p.assignments)), h("span", {}, p.assignments === 1 ? "assignment" : "assignments")),
      h("div", { class: "cd-count" }, h("strong", {}, String(p.todos.length)), h("span", {}, p.todos.length === 1 ? "to-do" : "to-dos"))),
    todoList,
    h("p", { class: "meta cd-note" }, "Gone from Homework, Today, the morning brief, reminders and email suggestions. To-dos are archived, not deleted. Nothing changes on Canvas. Settings → Accounts → Hidden classes shows it again."),
    h("div", { class: "cd-actions" }, keep, hide)));
  hide.addEventListener("click", async () => {
    let r: DropResult;
    try { r = await busyButton(hide, () => api!.course_drop(p.key, p.token), "Hiding…"); }
    catch (e) { r = { ok: false, error: String(e) } as DropResult; }
    if (!r.ok) { toast(`⚠ ${r.error ?? "Couldn't hide it."}`); return; }
    d.close();
    droppedToast(r);
    changed(r);
  });
  if (!d.open) d.showModal();
  hide.focus();
}

/** Monkey hid a class (or the owner pressed Hide): what went, with Undo (shows it again). */
export function droppedToast(r: DropResult) {
  undoToast(`🎒 ${removedText(r)}`, async () => {
    if (!api) return;
    const back = await api.course_undrop(r.key);
    if (!back.ok) { toast(`⚠ ${back.error ?? "Couldn't show it again."}`); return; }
    toast(`✓ ${back.name} is back`);
    changed(back);
  }, 12000);
}

/** The confirm Monkey opened is moot (the class was hidden another way): close it. */
export function closeConfirm(key?: string) {
  if (dlg?.open && (!key || dlg.dataset.key === key)) dlg.close();
}

// ------------------------------------------------------------------ Settings → Accounts → Hidden classes
/** The list of hidden classes with "Show again". Fills itself; redraws after a change. */
export function hiddenCoursesSection(): HTMLElement {
  const box = h("div", { class: "cd-hidden", "aria-live": "polite" }, h("p", { class: "meta" }, "Loading…"));
  const draw = async () => {
    if (!api) return;
    let r: Awaited<ReturnType<CourseApi["hidden_courses"]>>;
    try { r = await api.hidden_courses(); } catch (e) { r = { ok: false, error: String(e), items: [] }; }
    if (!r.ok) { box.replaceChildren(h("p", { class: "keynote bad" }, `⚠ ${r.error ?? "Couldn't load hidden classes."}`)); return; }
    if (!r.items.length) {
      box.replaceChildren(h("p", { class: "meta cd-none" }, "No hidden classes. Dropped one? Homework → By class → ⋯ → I dropped this class, or just tell Monkey."));
      return;
    }
    box.replaceChildren(h("ul", { class: "cd-hidden-list" }, ...r.items.map((c) => {
      const btn = h("button", { type: "button", class: "ghost mini cd-show" }, "Show again") as HTMLButtonElement;
      const li = h("li", { "data-key": c.key },
        h("span", { class: "cd-hname" }, c.name, c.full ? h("span", { class: "meta" }, ` · ${c.full}`) : ""),
        h("span", { class: "meta cd-hmeta" }, [c.hidden_at ? `hidden ${c.hidden_at.slice(0, 10)}` : "",
          `${n(c.assignments, "assignment")}`, `${n(c.todos, "to-do")} archived`].filter(Boolean).join(" · ")),
        btn);
      btn.addEventListener("click", async () => {
        let back: DropResult;
        try { back = await busyButton(btn, () => api!.course_undrop(c.key), "Showing…"); }
        catch (e) { back = { ok: false, error: String(e) } as DropResult; }
        if (!back.ok) { toast(`⚠ ${back.error ?? "Couldn't show it again."}`); return; }
        toast(`✓ ${back.name} is back: ${n(back.assignments, "assignment")} and ${n(back.todos.length, "to-do")}`);
        leave(li, "shrink", () => { li.remove(); void draw(); });
        changed(back);
      });
      return li;
    })));
    box.querySelectorAll("li").forEach((li, i) => enter(li, "rise", i * 40));
  };
  void draw();
  (box as any).redraw = draw;
  pop(box, 0.3);
  return box;
}
