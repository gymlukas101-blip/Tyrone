// Canvas checklist: ranked assignments with animated checkboxes.
import { countdown, h, s, toast } from "./dom";

export interface Item {
  id: string; title: string; course: string; due: string | null; points: number | null;
  impact_pct: number | null; course_grade: number | null; missing: boolean; priority: number;
  tier: "critical" | "high" | "normal" | "low" | "done"; reason: string; url: string; done: boolean;
  source: string;
}
export interface Board {
  source: "canvas" | "feed" | "none"; todo: Item[]; done: Item[];
  stats: { week_total?: number; week_done?: number; missing?: number; critical?: number };
}
type Toggle = (id: string, done: boolean) => Promise<{ ok: boolean; synced?: boolean; error?: string }>;
type Open = (url: string) => void;

let current: { board: Board; root: HTMLElement; toggle: Toggle; open: Open; tab: "todo" | "done" } | null = null;

function checkbox(checked: boolean) {
  const svg = s("svg", { viewBox: "0 0 28 28", width: 28, height: 28, "aria-hidden": "true" },
    s("rect", { class: "cb-box", x: 3, y: 3, width: 22, height: 22, rx: 7 }),
    s("path", { class: "cb-check", d: "M8.5 14.5 L12.5 18.5 L20 10" }));
  const btn = h("button", {
    class: `cb ${checked ? "on" : ""}`, type: "button", role: "checkbox",
    "aria-checked": String(checked), title: checked ? "Mark not done" : "Mark done",
  }, svg);
  return btn;
}

function burst(at: HTMLElement) {
  const b = h("span", { class: "burst" });
  for (let i = 0; i < 10; i++) {
    const p = h("i", {});
    p.style.setProperty("--a", `${i * 36}deg`);
    b.append(p);
  }
  at.append(b);
  setTimeout(() => b.remove(), 700);
}

function row(it: Item) {
  const cb = checkbox(it.done);
  const r = h("li", { class: `asg ${it.done ? "is-done" : ""}`, "data-id": it.id },
    cb,
    h("div", { class: "asg-main" },
      h("div", { class: "asg-title" },
        h("span", { class: "t" }, it.title),
        h("span", { class: "course" }, it.course),
        it.missing && !it.done ? h("span", { class: "flag" }, "MISSING") : null),
      h("div", { class: "asg-why" }, it.done ? (it.reason || "done") : it.reason || countdown(it.due))),
    h("div", { class: "asg-side" },
      it.done ? null : h("span", { class: `tier ${it.tier}` }, it.tier),
      h("span", { class: "due" }, countdown(it.due))),
  );
  if (!it.done) {
    const bar = h("div", { class: `prio ${it.tier}`, title: `Priority ${it.priority}/100` });
    bar.style.setProperty("--p", `${it.priority}%`);
    r.append(bar);
  }
  r.querySelector(".asg-title .t")!.addEventListener("click", () => it.url && current?.open(it.url));
  cb.addEventListener("click", () => toggleItem(it, r, cb));
  return r;
}

async function toggleItem(it: Item, r: HTMLElement, cb: HTMLButtonElement) {
  if (!current) return;
  const done = !it.done;
  cb.classList.toggle("on", done);
  cb.setAttribute("aria-checked", String(done));
  r.classList.add(done ? "checking" : "unchecking");
  if (done) burst(cb);
  const res = await current.toggle(it.id, done);
  if (!res.ok) {
    toast(`⚠ ${res.error ?? "Couldn't update"}`);
    cb.classList.toggle("on", !done);
    r.classList.remove("checking", "unchecking");
    return;
  }
  if (done && res.synced) toast("✓ Checked off in Canvas too");
  setTimeout(() => moveItem(it.id, done), done ? 700 : 250);
}

/** Moves an item between lists (also used when Monkey checks something off by voice). */
export function markChecked(id: string, done: boolean) {
  if (!current) return;
  const row = current.root.querySelector<HTMLElement>(`li.asg[data-id="${CSS.escape(id)}"]`);
  const cb = row?.querySelector<HTMLButtonElement>(".cb");
  if (row && cb && !row.classList.contains("checking")) {
    cb.classList.toggle("on", done);
    row.classList.add(done ? "checking" : "unchecking");
    if (done) burst(cb);
  }
  setTimeout(() => moveItem(id, done), done ? 700 : 250);
}

function moveItem(id: string, done: boolean) {
  if (!current) return;
  const { board } = current;
  const from = done ? board.todo : board.done;
  const idx = from.findIndex((x) => x.id === id);
  if (idx < 0) return;
  const [it] = from.splice(idx, 1);
  it.done = done;
  if (done) {
    it.tier = "done";
    it.reason = "checked off";
    board.done.unshift(it);
  } else {
    board.todo.push(it);
    board.todo.sort((a, b) => b.priority - a.priority);
  }
  const inWeek = it.due && Math.abs(new Date(it.due).getTime() - Date.now()) < 8 * 864e5;
  if (inWeek && board.stats.week_done != null) board.stats.week_done += done ? 1 : -1;
  draw();
}

function ring(done: number, total: number) {
  const r = 20, c = 2 * Math.PI * r, frac = total ? done / total : 0;
  return s("svg", { viewBox: "0 0 52 52", width: 52, height: 52, class: "ring", role: "img",
                    "aria-label": `${done} of ${total} done this week` },
    s("circle", { cx: 26, cy: 26, r, class: "ring-bg" }),
    s("circle", { cx: 26, cy: 26, r, class: "ring-fg", "stroke-dasharray": `${c * frac} ${c}`,
                  transform: "rotate(-90 26 26)" }),
    s("text", { x: 26, y: 30, "text-anchor": "middle", class: "ring-txt" }, `${done}/${total}`));
}

function draw() {
  if (!current) return;
  const { board, root, tab } = current;
  const st = board.stats;
  const list = tab === "todo" ? board.todo : board.done;
  root.querySelector(".asg-body")!.replaceChildren(
    h("div", { class: "asg-head" },
      ring(st.week_done ?? 0, st.week_total ?? 0),
      h("div", {},
        h("div", { class: "asg-headline" }, `${st.week_done ?? 0} of ${st.week_total ?? 0} done this week`),
        h("div", { class: "meta" },
          [st.missing ? `${st.missing} missing` : "", st.critical ? `${st.critical} critical` : "",
           board.source === "feed" ? "due dates only — add a Canvas token for grades & points" : "ranked by grade impact, due date & your grade"]
            .filter(Boolean).join(" · ")))),
    h("div", { class: "tabs" },
      h("button", { type: "button", class: tab === "todo" ? "on" : "", onclick: () => { current!.tab = "todo"; draw(); } },
        `To do (${board.todo.length})`),
      h("button", { type: "button", class: tab === "done" ? "on" : "", onclick: () => { current!.tab = "done"; draw(); } },
        `Done (${board.done.length})`)),
    list.length
      ? h("ul", { class: "asg-list" }, ...list.map(row))
      : h("p", { class: "meta empty" }, tab === "todo" ? "Nothing left. You're locked in. 🔒" : "Nothing checked off yet."),
  );
}

export function renderAssignments(card: HTMLElement, board: Board, toggle: Toggle, open: Open) {
  card.classList.add("assign");
  const body = h("div", { class: "asg-body" });
  card.append(body);
  current = { board, root: card, toggle, open, tab: "todo" };
  draw();
}
