// The user's to-do list panel: quick add (with a visible, correctable due date), check off with Undo, edit, delete
// with Undo, sub-steps, sort, Open / Overdue / Done tabs. Monkey adds to it by voice and can help with an item.
import type { Api } from "./bridge";
import { burst, undoToast } from "./assignments";
import { h, toast } from "./dom";
import { dueDate, dueLabel, isOverdue, splitQuick } from "./todoparse";
import { loadSuggestions, suggestionsSection } from "./todosuggest";

export type Priority = "low" | "normal" | "high";
export interface TodoStep { text: string; done: boolean }
export interface Todo {
  id: string; text: string; notes: string; due: string | null; priority: Priority; list: string;
  status: "open" | "done"; steps: TodoStep[]; source: string; created: number; done_at: number | null;
  origin?: { kind?: string; account?: string; account_label?: string; evidence?: string; subject?: string; link?: string } | null;
}
export interface TodoSettings { reminders: boolean; speak: boolean }
interface Hooks { celebrate: () => void; ask: (text: string) => void; settings?: () => void }

type Tab = "open" | "overdue" | "done";
let cur: {
  root: HTMLElement; api: Api; hooks: Hooks; items: Todo[]; settings: TodoSettings;
  tab: Tab; sort: "due" | "priority"; editing: string | null; drawn: boolean;
} | null = null;

const PRIO_RANK: Record<Priority, number> = { high: 0, normal: 1, low: 2 };
const SOURCE_ICON: Record<string, string> = { voice: "🎙", Monkey: "🐒", typed: "" };
const far = Number.MAX_SAFE_INTEGER;
const dueMs = (t: Todo) => dueDate(t.due)?.getTime() ?? far;

export const todoOpen = () => !!cur && document.body.contains(cur.root);

function sorted(list: Todo[]): Todo[] {
  const s = cur?.sort ?? "due";
  return [...list].sort((a, b) => s === "priority"
    ? PRIO_RANK[a.priority] - PRIO_RANK[b.priority] || dueMs(a) - dueMs(b) || a.created - b.created
    : dueMs(a) - dueMs(b) || PRIO_RANK[a.priority] - PRIO_RANK[b.priority] || a.created - b.created);
}

function views() {
  const items = cur?.items ?? [];
  const open = items.filter((t) => t.status === "open");
  return {
    open: sorted(open),
    overdue: sorted(open.filter((t) => isOverdue(t.due))),
    done: [...items.filter((t) => t.status === "done")].sort((a, b) => (b.done_at ?? 0) - (a.done_at ?? 0)),
  };
}

function checkbox(checked: boolean, label: string) {
  const btn = h("button", { class: `cb ${checked ? "on" : ""}`, type: "button", role: "checkbox",
                            "aria-checked": String(checked), "aria-label": label, title: checked ? "Mark not done" : "Mark done" });
  btn.innerHTML = '<svg viewBox="0 0 28 28" width="28" height="28" aria-hidden="true"><rect class="cb-box" x="3" y="3" width="22" height="22" rx="7"></rect><path class="cb-check" d="M8.5 14.5 L12.5 18.5 L20 10"></path></svg>';
  return btn;
}

/** Date + optional time inputs for a due string ("" = no date). */
function dueInputs(due: string | null, onChange?: () => void) {
  const [d, t] = (due ?? "").split("T");
  const date = h("input", { type: "date", value: d ?? "", "aria-label": "Due date", class: "todo-date" });
  const time = h("input", { type: "time", value: t ?? "", "aria-label": "Due time (optional)", class: "todo-time" });
  const clear = h("button", { type: "button", class: "ghost mini", title: "No due date", "aria-label": "Remove the due date",
                              onclick: () => { date.value = ""; time.value = ""; onChange?.(); } }, "✕");
  date.addEventListener("input", () => onChange?.());
  time.addEventListener("input", () => onChange?.());
  const value = () => (date.value ? date.value + (time.value ? `T${time.value.slice(0, 5)}` : "") : null);
  const set = (v: string | null) => { const [a, b] = (v ?? "").split("T"); date.value = a ?? ""; time.value = b ?? ""; };
  return { el: h("span", { class: "todo-due-in" }, date, time, clear), value, set, date };
}

function prioSelect(v: Priority, label = "Priority") {
  const sel = h("select", { "aria-label": label, class: "todo-prio" },
    ...(["high", "normal", "low"] as Priority[]).map((p) => h("option", { value: p, selected: p === v }, p[0].toUpperCase() + p.slice(1))));
  return sel;
}

// ------------------------------------------------------------------ quick add
function quickAdd() {
  const input = h("input", { id: "todoNew", "aria-label": "New to-do", autocomplete: "off",
                             placeholder: "Add a to-do… try “call the dentist tomorrow 5pm”" });
  let dueTouched = false, prioTouched = false;
  const due = dueInputs(null, () => { dueTouched = true; preview(); });
  const prio = prioSelect("normal");
  prio.addEventListener("change", () => { prioTouched = true; });
  const chip = h("span", { class: "todo-parsed-chip", "aria-live": "polite" });
  const extra = h("div", { class: "todo-parsed", hidden: true }, chip, h("label", {}, "Due ", due.el), h("label", {}, "Priority ", prio));
  let parsed = splitQuick("");

  function preview() {
    parsed = splitQuick(input.value);
    extra.hidden = !input.value.trim();
    if (!dueTouched) due.set(parsed.due);
    if (!prioTouched) prio.value = parsed.priority;
    const d = due.value();
    chip.textContent = d ? `📅 ${dueLabel(d)}` + (isOverdue(d) ? " (already passed)" : "") : "No due date";
    chip.classList.toggle("none", !d);
    if (parsed.list) chip.textContent += ` · #${parsed.list}`;
  }
  input.addEventListener("input", preview);
  const form = h("form", { class: "todo-add", onsubmit: async (e: Event) => {
    e.preventDefault();
    if (!cur || !input.value.trim()) return;
    preview();
    const text = parsed.text || input.value.trim();
    const r = await cur.api.todo_add({ text, due: due.value(), priority: prio.value as Priority, list: parsed.list, notes: "", steps: [] });
    if (!r.ok || !r.item) return toast(`⚠ ${r.error ?? "Couldn't add that"}`);
    input.value = ""; dueTouched = prioTouched = false; due.set(null); prio.value = "normal"; preview();
    cur.items.push(r.item);
    if (cur.tab === "done" || (cur.tab === "overdue" && !isOverdue(r.item.due))) cur.tab = "open";
    draw(r.item.id);
    document.getElementById("todoNew")?.focus();
  } }, input, h("button", { type: "submit", class: "primary" }, "Add"));
  return h("div", { class: "todo-addwrap" }, form, extra);
}

// ------------------------------------------------------------------ rows
function stepsList(t: Todo) {
  if (!t.steps.length) return null;
  return h("ol", { class: "todo-steps", "aria-label": `Steps for ${t.text}` }, ...t.steps.map((st, i) => {
    const cb = checkbox(st.done, `Step ${i + 1}: ${st.text}`);
    cb.classList.add("small");
    cb.addEventListener("click", async () => {
      const steps = t.steps.map((x, j) => (j === i ? { ...x, done: !x.done } : x));
      await save(t, { steps });
    });
    return h("li", { class: st.done ? "done" : "" }, cb, h("span", {}, st.text));
  }));
}

function row(t: Todo, fresh: boolean) {
  const done = t.status === "done";
  const over = !done && isOverdue(t.due);
  const cb = checkbox(done, `${done ? "Mark not done" : "Mark done"}: ${t.text}`);
  const stepsDone = t.steps.filter((s) => s.done).length;
  const why = done ? `done${t.done_at ? " " + new Date(t.done_at * 1000).toLocaleDateString([], { weekday: "short", month: "short", day: "numeric" }) : ""}`
    : [t.due ? (over ? `overdue · was due ${dueLabel(t.due)}` : `due ${dueLabel(t.due)}`) : "no due date",
       t.notes ? t.notes.slice(0, 80) : ""].filter(Boolean).join(" · ");
  const r = h("li", { class: `asg todo-row ${done ? "is-done" : ""} ${over ? "overdue" : ""} ${fresh ? "fresh" : ""}`, "data-id": t.id },
    cb,
    h("div", { class: "asg-main" },
      h("div", { class: "asg-title" },
        h("button", { type: "button", class: "t linklike", title: "Edit", onclick: () => { cur!.editing = t.id; draw(); } }, t.text),
        t.list ? h("span", { class: "course" }, `#${t.list}`) : null,
        over ? h("span", { class: "flag" }, "OVERDUE") : null,
        t.steps.length ? h("span", { class: "course steps-count", title: "Steps done" }, `${stepsDone}/${t.steps.length} steps`) : null,
        SOURCE_ICON[t.source] ? h("span", { class: "src", title: t.source === "voice" ? "Added by voice" : "Added by Monkey" }, SOURCE_ICON[t.source]) : null,
        t.origin?.account_label ? h("span", { class: "src email", title: t.origin.evidence ? `From email: “${t.origin.evidence}”` : "From email" }, `✉ ${t.origin.account_label}`) : null),
      h("div", { class: "asg-why" }, why),
      done ? null : stepsList(t)),
    h("div", { class: "asg-side" },
      done ? h("span", { class: "tier done" }, "done") : h("span", { class: `tier ${t.priority}` }, t.priority),
      h("span", { class: "todo-actions" },
        h("button", { type: "button", class: "ghost mini", "aria-label": `Edit ${t.text}`, title: "Edit", onclick: () => { cur!.editing = t.id; draw(); } }, "✎"),
        h("button", { type: "button", class: "ghost mini", "aria-label": `Delete ${t.text}`, title: "Delete", onclick: () => void remove(t) }, "🗑"))),
  );
  if (!done && t.steps.length) {
    const bar = h("div", { class: "prio normal", title: `${stepsDone} of ${t.steps.length} steps done` });
    bar.style.setProperty("--p", `${Math.round((stepsDone / t.steps.length) * 100)}%`);
    r.append(bar);
  }
  cb.addEventListener("click", () => void toggle(t, r, cb));
  return r;
}

function editor(t: Todo) {
  const text = h("input", { value: t.text, "aria-label": "To-do text", class: "todo-text" });
  const notes = h("textarea", { "aria-label": "Notes", placeholder: "Notes (optional)", rows: 2 }, t.notes);
  const due = dueInputs(t.due);
  const prio = prioSelect(t.priority);
  const list = h("input", { value: t.list, "aria-label": "List or tag (optional)", placeholder: "list / tag", class: "todo-list-in" });
  let steps = t.steps.map((s) => ({ ...s }));
  const stepsBox = h("ol", { class: "todo-steps edit", "aria-label": "Steps" });
  const drawSteps = () => stepsBox.replaceChildren(...steps.map((st, i) => {
    const inp = h("input", { value: st.text, "aria-label": `Step ${i + 1}` });
    inp.addEventListener("input", () => { steps[i].text = inp.value; });
    return h("li", {}, inp, h("button", { type: "button", class: "ghost mini", "aria-label": `Remove step ${i + 1}`,
      onclick: () => { steps.splice(i, 1); drawSteps(); } }, "✕"));
  }));
  drawSteps();
  const newStep = h("input", { placeholder: "Add a step and press Enter", "aria-label": "New step" });
  newStep.addEventListener("keydown", (e) => {
    if (e.key === "Enter") { e.preventDefault(); if (newStep.value.trim()) { steps.push({ text: newStep.value.trim(), done: false }); newStep.value = ""; drawSteps(); } }
  });
  const close = () => { cur!.editing = null; draw(); };
  const form = h("form", { class: "todo-edit", "data-id": t.id, onsubmit: async (e: Event) => {
    e.preventDefault();
    if (!text.value.trim()) return toast("⚠ A to-do needs some text");
    steps = steps.filter((s) => s.text.trim());
    const ok = await save(t, { text: text.value.trim(), notes: notes.value, due: due.value(), priority: prio.value as Priority,
                                list: list.value.trim().replace(/^#/, ""), steps });
    if (ok) close();
  } },
    h("label", {}, "To-do", text),
    h("div", { class: "todo-edit-row" }, h("label", {}, "Due ", due.el), h("label", {}, "Priority ", prio), h("label", {}, "List ", list)),
    h("label", {}, "Notes", notes),
    h("div", { class: "todo-edit-steps" }, h("span", { class: "meta" }, "Steps"), stepsBox, newStep),
    h("div", { class: "todo-edit-btns" },
      h("button", { type: "submit", class: "primary" }, "Save"),
      h("button", { type: "button", class: "ghost", onclick: close }, "Cancel"),
      h("button", { type: "button", class: "ghost", title: "Ask Monkey to break it into steps and help you do it",
                    onclick: () => { cur?.hooks.ask(`Help me get this to-do done: "${t.text}"`); close(); } }, "🐒 Help me do this"),
      h("button", { type: "button", class: "ghost danger", onclick: () => void remove(t) }, "Delete")),
  );
  form.addEventListener("keydown", (e) => { if (e.key === "Escape") { e.preventDefault(); close(); } });
  return h("li", { class: "todo-editing" }, form);
}

// ------------------------------------------------------------------ actions
async function save(t: Todo, changes: Partial<Todo>): Promise<boolean> {
  if (!cur) return false;
  const r = await cur.api.todo_update(t.id, changes);
  if (!r.ok || !r.item) { toast(`⚠ ${r.error ?? "Couldn't save that"}`); return false; }
  replace(r.item);
  draw();
  return true;
}

function replace(item: Todo) {
  if (!cur) return;
  const i = cur.items.findIndex((x) => x.id === item.id);
  if (i >= 0) cur.items[i] = item; else cur.items.push(item);
}

async function toggle(t: Todo, r: HTMLElement, cb: HTMLButtonElement) {
  if (!cur) return;
  const done = t.status !== "done";
  cb.classList.toggle("on", done);
  cb.setAttribute("aria-checked", String(done));
  r.classList.add(done ? "checking" : "unchecking");
  if (done) burst(cb);
  const res = await cur.api.todo_update(t.id, { status: done ? "done" : "open" });
  if (!res.ok || !res.item) {
    toast(`⚠ ${res.error ?? "Couldn't update"}`);
    cb.classList.toggle("on", !done);
    r.classList.remove("checking", "unchecking");
    return;
  }
  if (done) {
    cur.hooks.celebrate();
    undoToast(`✓ Done: "${t.text}"`, async () => {
      const back = await cur?.api.todo_update(t.id, { status: "open" });
      if (back?.ok && back.item) { replace(back.item); draw(); }
    });
  }
  const item = res.item;
  setTimeout(() => { replace(item); draw(); }, done ? 700 : 250);
}

async function remove(t: Todo) {
  if (!cur) return;
  const r = await cur.api.todo_delete(t.id);
  if (!r.ok) return toast(`⚠ ${r.error ?? "Couldn't delete that"}`);
  cur.items = cur.items.filter((x) => x.id !== t.id);
  if (cur.editing === t.id) cur.editing = null;
  draw();
  undoToast(`🗑 Deleted "${t.text}"`, async () => {
    const back = await cur?.api.todo_restore(t.id);
    if (back?.ok && back.item) { replace(back.item); draw(back.item.id); }
  });
}

// ------------------------------------------------------------------ draw
function draw(freshId?: string) {
  if (!cur) return;
  const { root, tab } = cur;
  const v = views();
  const list = v[tab];
  const todayN = v.open.filter((t) => { const d = dueDate(t.due); return d && !isOverdue(t.due) && d.toDateString() === new Date().toDateString(); }).length;
  const headline = v.open.length ? `${v.open.length} to do` + (v.overdue.length ? ` · ${v.overdue.length} overdue` : "") + (todayN ? ` · ${todayN} due today` : "")
    : "All clear";
  const tabBtn = (id: Tab, label: string) => h("button", { type: "button", class: tab === id ? "on" : "", "aria-pressed": String(tab === id),
    onclick: () => { cur!.tab = id; cur!.editing = null; draw(); } }, label);
  const sortBtn = (id: "due" | "priority", label: string) => h("button", { type: "button", class: cur!.sort === id ? "on" : "",
    "aria-pressed": String(cur!.sort === id), onclick: () => { cur!.sort = id; draw(); } }, label);
  const empty = { open: "Nothing to do. Add something above, or tell Monkey “remind me to…”. 🍌",
                  overdue: "Nothing overdue. You're on it. 🔒", done: "Nothing checked off yet." }[tab];
  const body = root.querySelector(".todo-body")!;
  const keepAdd = body.querySelector(".todo-addwrap") ?? quickAdd();
  body.replaceChildren(
    h("div", { class: "asg-head" }, h("div", {},
      h("div", { class: "asg-headline" }, headline),
      h("div", { class: "meta" }, "Monkey can add to this by voice and help you get things done. Ask him “help me with …”."))),
    keepAdd,
    ...[tab === "open" ? suggestionsSection(cur.api, (t) => { cur!.items.push(t); draw(t.id); }, () => draw()) : null].filter((x): x is HTMLElement => !!x),
    h("div", { class: "todo-bar" },
      h("div", { class: "tabs", role: "group", "aria-label": "Show" },
        tabBtn("open", `Open (${v.open.length})`), tabBtn("overdue", `Overdue (${v.overdue.length})`), tabBtn("done", `Done (${v.done.length})`)),
      tab === "done" ? null : h("div", { class: "tabs sort", role: "group", "aria-label": "Sort by" },
        h("span", { class: "meta" }, "Sort:"), sortBtn("due", "Due"), sortBtn("priority", "Priority"))),
    list.length
      ? h("ul", { class: `asg-list todo-list ${cur.drawn ? "settled" : ""}` }, ...list.map((t) => (cur!.editing === t.id ? editor(t) : row(t, t.id === freshId))))
      : h("p", { class: "meta empty" }, empty),
    h("div", { class: "todo-foot" },
      h("label", {}, h("input", { type: "checkbox", checked: cur.settings.reminders, onchange: (e: Event) => void setting("todo_reminders", (e.target as HTMLInputElement).checked) }),
        " Remind me in Monkey when something's due"),
      h("label", {}, h("input", { type: "checkbox", checked: cur.settings.speak, onchange: (e: Event) => void setting("todo_speak_reminders", (e.target as HTMLInputElement).checked) }),
        " Say reminders out loud"),
      cur.hooks.settings ? h("button", { type: "button", class: "linkish", id: "todoRemindSettings", onclick: () => cur?.hooks.settings?.() },
        "Windows & phone notifications…") : null),
  );
  const ed = root.querySelector<HTMLInputElement>(".todo-edit .todo-text");
  if (ed && document.activeElement?.closest(".todo-edit") == null) ed.focus();
  cur.drawn = true;           // rows slide in once; later redraws (a check, an edit) don't replay it for every row
}

async function setting(key: "todo_reminders" | "todo_speak_reminders", on: boolean) {
  if (!cur) return;
  await cur.api.save_settings({ [key]: on });
  if (key === "todo_reminders") cur.settings.reminders = on; else cur.settings.speak = on;
}

export function renderTodos(card: HTMLElement, api: Api, data: { items: Todo[]; settings?: TodoSettings }, hooks: Hooks,
                            tab: Tab = "open") {
  card.classList.add("assign", "todo");
  card.append(h("div", { class: "todo-body" }));
  cur = { root: card, api, hooks, items: data.items ?? [], settings: data.settings ?? { reminders: true, speak: false },
          tab, sort: cur?.sort ?? "due", editing: null, drawn: false };
  draw();
  void loadSuggestions(api).then(() => { if (cur && !cur.editing) draw(); });   // "Suggested from email"
}

/** Monkey changed the list (voice): show it if the panel is open. */
export async function refreshTodos(freshId?: string) {
  if (!cur || !todoOpen()) return;
  const r = await cur.api.todo_list();
  if (!r.ok || !r.items) return;
  cur.items = r.items;
  if (r.settings) cur.settings = r.settings;
  if (!cur.editing) draw(freshId);            // never wipe what the user is typing in the editor; it redraws on close
}

/** An in-app reminder: a note in Monkey's window with Done / Snooze (Windows and phone notifications are sent by
 *  the Python side, Settings → Reminders). */
export function reminderToast(api: Api, t: Todo, onDone: () => void) {
  document.querySelectorAll(`.todo-remind[data-id="${CSS.escape(t.id)}"]`).forEach((n) => n.remove());
  const when = t.due ? (isOverdue(t.due) ? `was due ${dueLabel(t.due)}` : `due ${dueLabel(t.due)}`) : "";
  const el = h("div", { class: "toast todo-remind", role: "alert", "data-id": t.id },
    h("strong", {}, "⏰ " + t.text), " ", h("span", { class: "meta" }, when), " ",
    h("button", { type: "button", class: "ghost mini", onclick: async () => {
      el.remove();
      const r = await api.todo_update(t.id, { status: "done" });
      if (r.ok) { onDone(); toast(`✓ Done: "${t.text}"`); void refreshTodos(); }
    } }, "Done"),
    h("button", { type: "button", class: "ghost mini", onclick: async () => { el.remove(); await api.todo_snooze(t.id, 10); } }, "Snooze 10 min"),
    h("button", { type: "button", class: "ghost mini", "aria-label": "Dismiss reminder", onclick: () => el.remove() }, "✕"));
  document.body.append(el);
  setTimeout(() => el.remove(), 90_000);
  return el;
}

// Tests check this parser against the same cases as the Python one (tests/todo_due_cases.json).
(window as any).__monkeyTodoParse = splitQuick;


