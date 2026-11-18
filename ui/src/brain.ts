// Settings → Brain: which model + effort Monkey uses for each task, and the "Calibrate models" benchmark.
import type { Api, CalResults, Policy, PolicyRow } from "./bridge";
import { h, toast } from "./dom";

const TIERS: [keyof Pick<PolicyRow, "min" | "default" | "max">, string, string][] = [
  ["min", "⚡ Quick", "Cheapest that works (used when you press ⚡ Quick or say 'quick')"],
  ["default", "Auto", "What Monkey uses normally"],
  ["max", "★ Important", "The most worth paying for (★ Important / 'this is important')"],
];
const money = (v: number) => (v < 0.01 ? `$${v.toFixed(4)}` : `$${v.toFixed(v < 1 ? 3 : 2)}`);

let progressEl: HTMLElement | null = null;
let refresh: (() => void) | null = null;

/** Called from the main event stream with "calibration" progress events. */
export function brainEvent(p: any) {
  if (progressEl) {
    if (p.finished) {
      progressEl.textContent = p.error ? `⚠ ${p.error}` : "Done! Rate the answers below.";
      refresh?.();
    } else {
      const pct = p.total ? Math.round((100 * p.done) / p.total) : 0;
      progressEl.replaceChildren(
        h("div", { class: "calbar" }, h("i", { style: `width:${pct}%` })),
        h("span", {}, `${p.done}/${p.total} · ${p.task} on ${p.config}`));
    }
  }
}

export async function openBrain(api: Api) {
  let dlg = document.getElementById("brain") as HTMLDialogElement | null;
  if (!dlg) {
    dlg = h("dialog", { id: "brain" });
    document.body.append(dlg);
  }
  const d = dlg;
  const render = async (view: "table" | "results" = "table") => {
    const pol = await api.get_policy();
    const body = view === "results" ? await resultsView(api, pol, () => render("table")) : tableView(api, pol, render);
    d.replaceChildren(h("div", { class: "settings brain" },
      h("header", {}, h("strong", {}, "🧠 Brain: models per task"), h("div", { class: "spacer" }),
        h("button", { class: "icon", onclick: () => { progressEl = null; refresh = null; d.close(); } }, "✕")),
      h("div", { class: "body" }, body)));
  };
  refresh = () => render("results");
  await render();
  if (!d.open) d.showModal();
}

function choiceSelect(api: Api, pol: Policy, row: PolicyRow, tier: "min" | "default" | "max", rerender: () => void) {
  const sel = h("select", { title: TIERS.find((t) => t[0] === tier)![2] });
  for (const m of pol.models) {
    const g = h("optgroup", { label: m.name });
    for (const e of pol.efforts) g.append(h("option", { value: `${m.id}|${e}` }, `${m.name.split(" ")[0]} · ${e}`));
    sel.append(g);
  }
  sel.value = `${row[tier].model}|${row[tier].effort}`;
  sel.addEventListener("change", async () => {
    const [model, effort] = sel.value.split("|");
    const r = await api.set_policy_entry(row.id, tier, model, effort);
    toast(r.ok ? `Saved: ${row.label} → ${tier === "default" ? "Auto" : tier} ${sel.selectedOptions[0].textContent}` : `⚠ ${r.error}`);
    rerender();
  });
  return sel;
}

function tableView(api: Api, pol: Policy, rerender: (v?: "table" | "results") => void) {
  const rows = pol.rows.map((r) => {
    const m = r.measured;
    return h("tr", { class: r.internal ? "internal" : "" },
      h("td", { class: "task", title: r.why }, h("b", {}, r.label), h("small", {}, r.why)),
      ...TIERS.map(([tier]) => h("td", {}, choiceSelect(api, pol, r, tier, () => rerender()))),
      h("td", { class: "num" },
        h("b", {}, money(r.default.usd)), h("small", {}, `${r.default.first_words_s}s to first words`),
        h("small", {}, `${money(r.default.per_month_usd)}/mo`),
        m && h("small", { class: "measured", title: `Measured ${m.date}` }, `✓ measured ${money(m.usd)} · ${m.first_words_s}s`)));
  });
  const progress = h("div", { class: "calprogress" });
  progressEl = progress;
  return h("div", {},
    h("p", { class: "help" },
      "Each task has three settings: ⚡ Quick (cheapest that works), Auto (normal) and ★ Important (most worth paying for). " +
      "Costs and speeds are estimates from Monkey's real prompt sizes and Anthropic's prices; calibrate to measure them. " +
      "Monkey keeps a copy of this table in his memory (model_policy.md), so you can also ask him."),
    h("div", { class: "totals" },
      h("span", {}, "Estimated per month: "),
      h("b", {}, `Auto ${money(pol.totals.default)}`), " · ",
      h("span", {}, `all Quick ${money(pol.totals.min)}`), " · ",
      h("span", {}, `all Important ${money(pol.totals.max)}`)),
    h("div", { class: "tablewrap" }, h("table", { class: "policy" },
      h("thead", {}, h("tr", {}, h("th", {}, "Task"), ...TIERS.map(([, label, tip]) => h("th", { title: tip }, label)),
        h("th", {}, "Auto cost"))),
      h("tbody", {}, ...rows))),
    h("div", { class: "field" },
      h("button", { class: "primary", type: "button", disabled: pol.calibrating, onclick: async () => {
        if (!confirm(`Calibrate models?\n\nMonkey runs a sample request for every task on its Quick, Auto and Important ` +
                     `settings (about 50 runs, ~5 minutes). Canvas, Garmin, email and calendar data are fake and nothing ` +
                     `is sent or changed. Estimated cost: about ${money(pol.calibration_estimate)} of your API credits.`)) return;
        const r = await api.calibrate_start();
        if (!r.ok) return toast(`⚠ ${r.error}`);
        progress.textContent = "Starting…";
      } }, pol.calibrating ? "Calibrating…" : `Calibrate models (≈${money(pol.calibration_estimate)})`),
      pol.calibrating && h("button", { class: "ghost", type: "button", onclick: () => api.calibrate_cancel() }, "Cancel"),
      pol.has_results && h("button", { class: "ghost", type: "button", onclick: () => rerender("results") }, "Rate last results"),
      h("button", { class: "ghost", type: "button", onclick: async () => {
        if (!confirm("Reset every task to Monkey's recommended models?")) return;
        await api.reset_policy(""); toast("Reset to recommended"); rerender();
      } }, "Reset to recommended")),
    progress);
}

async function resultsView(api: Api, _pol: Policy, back: () => void) {
  const res: CalResults = await api.calibration_results();
  if (!res.ok) return h("p", {}, res.error ?? "No results yet.");
  const picks: Record<string, string> = {};
  const tasks = Object.entries(res.tasks);
  const blocks = tasks.map(([id, t]) => {
    picks[id] = "all";
    const name = `pick-${id}`;
    const radio = (value: string, checked = false) => {
      const r = h("input", { type: "radio", name, value, checked }) as HTMLInputElement;
      r.addEventListener("change", () => { picks[id] = value; });
      return r;
    };
    return h("section", { class: "calresult" },
      h("h4", {}, t.label), h("p", { class: "help" }, `“${t.sample}”`),
      h("div", { class: "runs" }, ...t.runs.map((r, i) => h("label", { class: "run" + (r.error ? " failed" : "") },
        h("div", { class: "runhead" }, radio(String(i)), h("b", {}, r.label),
          h("span", {}, `${money(r.usd)} · ${r.first_words_s}s first words · ${r.total_s}s total`)),
        h("div", { class: "answer" }, r.error ? `⚠ ${r.error}` : r.answer || "(no text)")))),
      h("label", { class: "allfine" }, radio("all", true), " All fine: use the cheapest"));
  });
  return h("div", {},
    h("p", { class: "help" }, `Calibrated ${res.date}${res.complete ? "" : " (stopped early)"} · spent ${money(res.spent_usd)}. ` +
      "For each task, pick the answer you like best (Monkey makes it the Auto choice) or leave “All fine” to use the cheapest."),
    ...blocks,
    h("div", { class: "field" },
      h("button", { class: "primary", type: "button", onclick: async () => {
        const r = await api.calibration_apply(picks);
        if (!r.ok) return toast(`⚠ ${r.error}`);
        toast(r.changed?.length ? `Updated ${r.changed.length} task(s). Monkey remembers this.` : "Saved: measured numbers recorded.", 4000);
        back();
      } }, "Save my choices"),
      h("button", { class: "ghost", type: "button", onclick: back }, "Back to table")));
}
