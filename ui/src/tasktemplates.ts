// The task helper's templates in the Tasks dialog, and the extra labels on the HUD (what kind of task it is, and
// what an approval would do). Templates only narrow what Monkey may do; the rules live in Python (permissions.py).
import type { Api } from "./bridge";
import { h } from "./dom";
import "./mailinglists.css";

export interface TaskTemplate { id: string; title: string; blurb: string; example: string; skill: string;
  rules: Record<string, unknown>; deterministic: boolean }

const FALLBACK: TaskTemplate[] = [
  { id: "generic", title: "Anything else", blurb: "Plans with Claude; reads freely, asks before anything that sends, submits, buys, deletes or changes an account.", example: "Download last month's statement PDF from my phone carrier's site", skill: "general", rules: {}, deterministic: false },
  { id: "course", title: "Course modules", blurb: "Canvas or another course site: works through modules and lessons; questions and confirmations stay yours.", example: "Work through the 4 modules of the Title IX training on Canvas", skill: "course", rules: {}, deterministic: false },
];
let cache: TaskTemplate[] | null = null;

export async function loadTemplates(api: Api): Promise<TaskTemplate[]> {
  if (cache) return cache;
  const a = api as Api & { automation_templates?: () => Promise<{ ok: boolean; templates: TaskTemplate[] }> };
  try {
    const r = a.automation_templates ? await a.automation_templates() : null;
    cache = r?.ok && r.templates?.length ? r.templates : FALLBACK;
  } catch { cache = FALLBACK; }
  return cache;
}

export const templateTitle = (id?: string) => (cache ?? FALLBACK).find((t) => t.id === id)?.title ?? "";

/** Picker: one button per template. onPick gets the chosen template. */
export function templatePicker(list: TaskTemplate[], current: string, onPick: (t: TaskTemplate) => void): HTMLElement {
  const box = h("div", { class: "tpl-pick", role: "radiogroup", "aria-label": "What kind of task" });
  const draw = (cur: string) => box.replaceChildren(...list.map((t) => h("button", {
    type: "button", class: `ghost mini${t.id === cur ? " on" : ""}`, role: "radio", "aria-checked": String(t.id === cur), title: t.blurb,
    onclick: () => { draw(t.id); onPick(t); } }, h("b", {}, t.title), h("small", {}, t.blurb))));
  draw(current);
  return box;
}

export const LIMITS = "Never, whatever the task: banking or payment sites, Instagram/Snapchat automation, typing card or payment details, changing passwords or security settings. Spending money always stops for your OK on that exact step.";

/** What an approval would do, shown above Allow once / Don't. */
const KIND: Record<string, string> = {
  spend: "💳 Spends money: Monkey stopped before this step",
  send: "📤 Sends or posts something",
  submit: "📨 Submits a form",
  delete: "🗑 Deletes or removes something",
  account: "⚙ Changes your account",
  upload: "📎 Sends a file from your PC",
};
export function approvalKind(kind?: string): HTMLElement | "" {
  return kind && KIND[kind] ? h("span", { class: `ap-kind k-${kind}` }, KIND[kind]) : "";
}
export function templateChip(id?: string): HTMLElement | "" {
  const t = templateTitle(id);
  return t ? h("span", { class: "tpl-chip", title: "Kind of task" }, t) : "";
}
