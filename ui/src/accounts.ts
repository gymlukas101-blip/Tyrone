// Settings → Accounts: every connected inbox (any number of Gmail accounts + school Outlook) with a name the owner
// picks, the address (this screen only), "Find to-dos in this inbox", and Remove for Gmail accounts.
import type { Api, EmailAccount } from "./bridge";
import { h, toast } from "./dom";
import { loadInto } from "./loader";
import "./todosuggest.css";

const KIND: Record<string, string> = { gmail: "Gmail", outlook: "Outlook" };

function scanNote(a: EmailAccount): string {
  if (!a.scan_todos) return "";
  const s = a.scan ?? {};
  if (s.note) return `To-do check: ${s.note}`;
  if (s.at) return `Checked ${new Date(s.at).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}: `
    + `${s.checked ?? 0} new or flagged email${s.checked === 1 ? "" : "s"}, ${s.new ?? 0} suggested.`;
  return a.kind === "outlook" ? "Checks every 15 minutes while Outlook is open (Monkey never opens it for this)." : "Checks every 15 minutes.";
}

/** The list; fills itself from the API. onRemoved re-renders Settings (connections changed). */
export function emailAccountsList(api: Api, onRemoved: () => void): HTMLElement {
  const box = h("ul", { class: "acct-list", id: "emailAccounts", "aria-label": "Connected email accounts" });
  const draw = (accounts: EmailAccount[]) => box.replaceChildren(...accounts.filter((a) => a.connected).map((a) => {
    const label = h("input", { class: "acct-label", value: a.label, maxlength: 40, "aria-label": `Name for this ${KIND[a.kind]} account`,
                               title: "Your name for this account (Monkey uses it when it reads mail or sends from it)" });
    const saveLabel = async () => {
      const v = label.value.trim();
      if (v === a.label) return;
      const r = await api.email_account_update(a.id, { label: v });
      if (!r.ok) { toast(`⚠ ${r.error ?? "Couldn't rename it"}`); return; }
      toast(`✓ Renamed to ${v || "the default name"}`);
      draw(r.accounts);
    };
    label.addEventListener("change", () => void saveLabel());
    label.addEventListener("keydown", (e) => { if ((e as KeyboardEvent).key === "Enter") { e.preventDefault(); label.blur(); } });
    const scan = h("input", { type: "checkbox", checked: a.scan_todos, "aria-label": `Find to-dos in the ${a.label} inbox` });
    scan.addEventListener("change", async () => {
      const r = await api.email_account_update(a.id, { scan_todos: scan.checked });
      if (!r.ok) { toast(`⚠ ${r.error ?? "Couldn't change that"}`); scan.checked = !scan.checked; return; }
      if (scan.checked) toast("✓ Monkey will suggest to-dos from new unread and flagged mail here (read-only). You accept or dismiss each one.", 6000);
      draw(r.accounts);
    });
    const remove = a.kind === "gmail" ? h("button", { type: "button", class: "ghost mini danger", "aria-label": `Remove the ${a.label} account`,
      onclick: async () => {
        if (!confirm(`Remove the ${a.label} Gmail account from Monkey? (You can sign in again any time.)`)) return;
        await api.google_sign_out(a.id);
        toast(`${a.label} removed`);
        onRemoved();
      } }, "Remove") : null;
    const note = scanNote(a);
    return h("li", { "data-id": a.id },
      h("span", { class: "dot on" }), h("span", { class: "acct-kind" }, KIND[a.kind] ?? a.kind), label,
      h("span", { class: "acct-addr" }, a.address || (a.kind === "outlook" ? "classic Outlook on this PC" : "")),
      h("label", { class: "acct-scan" }, scan, "Find to-dos in this inbox"),
      remove,
      note ? h("span", { class: "acct-note", role: "status" }, note) : null);
  }));
  // slow to answer: a skeleton of the account rows (loader.ts); a failure just leaves the list empty (Settings still works)
  void loadInto(() => box, () => api.email_accounts(), { what: "your email accounts", skel: "rows", rows: 2, art: "bananas", retry: false })
    .then(({ value: r }) => { if (r?.ok) draw(r.accounts); }).catch(() => { /* Settings still works */ });
  return box;
}
