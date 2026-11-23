// "Suggested from email" in the to-do panel: to-dos Monkey found in the inboxes the owner turned on (Settings →
// Accounts → "Find to-dos in this inbox"). Nothing is added until the owner clicks Accept; Dismiss is remembered,
// so the same email never comes back. Email text is shown as a quote, never acted on.
import type { Api, TodoSuggestion } from "./bridge";
import type { Todo } from "./todo";
import { h, toast } from "./dom";
import { dueLabel, isOverdue } from "./todoparse";
import "./todosuggest.css";

let items: TodoSuggestion[] = [];
let collapsed = false;
const busy = new Set<string>();

const SIGNAL: Record<string, string> = { flagged: "⚑ Flagged", task: "☑ Outlook task", ask: "" };
const KIND: Record<string, string> = { gmail: "Gmail", outlook: "Outlook", outlook_task: "Outlook" };

export const suggestionCount = () => items.length;

/** Replace the cached list (from the API or a "todo_suggestions" event). */
export function setSuggestions(list: TodoSuggestion[] | undefined) {
  items = (list ?? []).filter((s) => s.status === "pending");
}

export async function loadSuggestions(api: Api) {
  try {
    const r = await api.todo_suggestions();
    if (r.ok) setSuggestions(r.items);
  } catch { /* the list just stays as it was */ }
}

/** The section, or null when there's nothing waiting. onAccepted gets the new to-do; redraw() repaints the panel. */
export function suggestionsSection(api: Api, onAccepted: (t: Todo) => void, redraw: () => void): HTMLElement | null {
  if (!items.length) return null;
  const remove = (id: string) => { items = items.filter((x) => x.id !== id); };
  const row = (s: TodoSuggestion) => {
    const when = s.due ? (isOverdue(s.due) ? `was due ${dueLabel(s.due)}` : `due ${dueLabel(s.due)}`) : "";
    const accept = h("button", { type: "button", class: "primary mini", "aria-label": `Accept: ${s.text}`, onclick: async () => {
      if (busy.has(s.id)) return;
      busy.add(s.id);
      const r = await api.todo_suggestion_accept(s.id);
      busy.delete(s.id);
      if (!r.ok || !r.item) { toast(`⚠ ${r.error ?? "Couldn't add that"}`); remove(s.id); redraw(); return; }
      remove(s.id);
      onAccepted(r.item);
      toast(`✓ Added to your to-do list: ${r.item.text}`);
    } }, "Accept");
    const dismiss = h("button", { type: "button", class: "ghost mini", "aria-label": `Dismiss: ${s.text}`, onclick: async () => {
      const r = await api.todo_suggestion_dismiss(s.id);
      if (!r.ok) toast(`⚠ ${r.error ?? "Couldn't dismiss that"}`);
      remove(s.id);
      redraw();
    } }, "Dismiss");
    const open = h("button", { type: "button", class: "ghost mini", title: s.kind === "gmail" ? "Open in Gmail" : "Show in Outlook (if it's open)",
      "aria-label": `Open the email: ${s.subject}`, onclick: async () => {
        const r = await api.todo_suggestion_open(s.id);
        if (!r.ok) toast(`⚠ ${r.error ?? "Couldn't open it"}`);
      } }, s.kind === "outlook_task" ? "Open task" : "Open email");
    return h("li", { class: "sug", "data-id": s.id },
      h("div", { class: "sug-main" },
        h("div", { class: "sug-title" }, s.text,
          SIGNAL[s.signal] ? h("span", { class: `sug-flag ${s.signal}` }, SIGNAL[s.signal]) : null),
        h("div", { class: "sug-meta" },
          h("span", { class: "sug-acct", title: `${KIND[s.kind] ?? "Email"} account` }, `✉ ${s.account_label || KIND[s.kind] || "Email"}`),
          s.sender ? ` · from ${s.sender}` : "", when ? ` · ${when}` : ""),
        h("blockquote", { class: "sug-quote", title: s.subject ? `Subject: ${s.subject}` : "" }, `“${s.evidence}”`)),
      h("div", { class: "sug-btns" }, accept, dismiss, open));
  };
  return h("section", { class: `todo-suggest ${collapsed ? "collapsed" : ""}`, "aria-label": "Suggested from email" },
    h("div", { class: "sug-head" },
      h("button", { type: "button", class: "linklike sug-toggle", "aria-expanded": String(!collapsed),
                    onclick: () => { collapsed = !collapsed; redraw(); } },
        `${collapsed ? "▸" : "▾"} Suggested from email (${items.length})`),
      h("span", { class: "meta" }, "Monkey only suggests. Nothing is added until you accept it.")),
    collapsed ? null : h("ul", { class: "sug-list" }, ...items.map(row)));
}
