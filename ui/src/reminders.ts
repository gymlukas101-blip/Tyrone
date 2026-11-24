// Settings → Reminders: where a due to-do reminds you. In Monkey's window (and out loud), as a Windows notification,
// and on your phone through ntfy (free, no account). The phone topic is made by Monkey, kept encrypted on the PC,
// and shown here only so you can subscribe to it; its QR code is drawn locally (nothing is sent anywhere to make it).
import qrcode from "qrcode-generator";
import type { Api, AppState } from "./bridge";
import { h, toast } from "./dom";
import { loadInto } from "./loader";

export interface PhoneStatus { state: "idle" | "ok" | "failed"; at: number | null; detail: string }
export interface ReminderChannels {
  ok: boolean; error?: string;
  windows?: { enabled: boolean; available: boolean; detail: string };
  phone?: { enabled: boolean; configured: boolean; server: string; topic: string; subscribe_url: string;
            has_token: boolean; show_text: boolean; status: PhoneStatus };
}

const DEFAULT_SERVER = "https://ntfy.sh";
const clock = (ts: number) => new Date(ts * 1000).toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });

export function phoneStatusText(st?: PhoneStatus): string {
  if (!st || st.state === "idle" || !st.at) return "";
  return st.state === "ok" ? `✓ Last phone notification went out at ${clock(st.at)}.`
    : `Last phone notification didn't go through (${clock(st.at)}): ${st.detail}. Reminders still show on this PC.`;
}

/** The QR code for the topic's address, as an inline SVG made right here. */
export function qrSvg(text: string): string {
  const qr = qrcode(0, "M");
  qr.addData(text);
  qr.make();
  return qr.createSvgTag({ cellSize: 4, margin: 2, scalable: true });
}

function toggle(id: string, checked: boolean, label: string, onChange: (on: boolean) => void, disabled = false) {
  const cb = h("input", { type: "checkbox", id, checked, disabled }) as HTMLInputElement;
  cb.addEventListener("change", () => onChange(cb.checked));
  return h("label", { class: "field toggle", for: id }, cb, h("span", {}, label));
}

/** The Reminders section. `saved` hands the new app state back to Settings after a save. */
export function reminderSettings(api: Api, s: Record<string, any>, saved: (st: AppState) => void): HTMLElement {
  const sec = h("section", { class: "remind", id: "set-reminders" }, h("h4", {}, "Reminders"));
  const body = h("div", {});
  sec.append(body);
  let ch: ReminderChannels = { ok: false };
  let phoneMsg = "";                                 // the test button's last answer, kept across redraws

  const save = async (changes: Record<string, any>) => {
    const st = await api.save_settings(changes);
    Object.assign(s, changes);
    saved(st);
  };
  const reload = async () => {
    ch = await api.reminder_channels();
    draw();
  };

  function windowsBlock() {
    const w = ch.windows;
    const status = h("p", { class: `help win-status ${w && !w.available ? "keynote bad" : ""}` },
      !w ? "" : w.available ? `${w.detail} If Monkey's window is in front with its own note on, you get that note instead, not both.`
        : w.detail);
    return h("div", { class: "win" },
      toggle("remWin", !!w?.enabled, "Windows notifications (Action Center), also while Monkey is hidden in the tray",
        async (on) => { await save({ todo_windows_notify: on }); await reload(); toast("Saved"); }, !!w && !w.available),
      status,
      h("div", { class: "field" }, h("button", { class: "ghost", type: "button", id: "winTest", disabled: !w?.available, onclick: async () => {
        const r = await api.windows_test_notification();
        toast(r.ok ? "✓ Sent. Look at the bottom-right corner of the screen (or Action Center)." : `⚠ ${r.error}`, 6000);
      } }, "Send a test Windows notification")));
  }

  function phoneBlock() {
    const p = ch.phone;
    const head = h("h5", {}, "📱 On your phone (ntfy)");
    const intro = h("p", { class: "help" }, "Free, no account: you install the ntfy app, and Monkey sends reminders to a private channel " +
      "(a “topic”) that only your phone listens to.");
    if (!p?.configured) {
      return h("div", { class: "phone", id: "phoneReminders" }, head, intro,
        h("div", { class: "field" }, h("button", { class: "primary", type: "button", id: "phoneSetup", onclick: async () => {
          const r = await api.phone_setup(false);
          if (!r.ok) return toast(`⚠ ${r.error}`);
          ch = r; draw();
        } }, "Set up my phone")));
    }
    const result = h("span", { class: "meta", id: "phoneTestResult", role: "status" }, phoneMsg);
    const testBtn = h("button", { class: "ghost", type: "button", id: "phoneTest" }, "Send test notification") as HTMLButtonElement;
    testBtn.addEventListener("click", async () => {
      testBtn.disabled = true; result.textContent = "Sending…";
      const r = await api.phone_test();
      testBtn.disabled = false;
      phoneMsg = r.ok ? "✓ Sent. It should be on your phone in a few seconds." : `⚠ Not sent: ${r.error}`;
      if (ch.phone && r.status) ch.phone.status = r.status;
      draw();
    });
    const copy = h("button", { class: "ghost mini", type: "button", onclick: async () => {
      try { await navigator.clipboard.writeText(p.topic); toast("✓ Topic copied"); }
      catch { window.getSelection()?.selectAllChildren(topic); toast("Selected: press Ctrl+C to copy"); }
    } }, "Copy");
    const topic = h("code", { class: "topic", id: "phoneTopic" }, p.topic);
    const qr = h("div", { class: "qr", id: "phoneQr", role: "img", "aria-label": "QR code with the topic's address" });
    qr.innerHTML = qrSvg(p.subscribe_url);
    const otherServer = p.server !== DEFAULT_SERVER;
    const serverIn = h("input", { value: p.server, "aria-label": "ntfy server address", id: "ntfyServer" }) as HTMLInputElement;
    const tokenIn = h("input", { type: "password", id: "ntfyToken", "aria-label": "ntfy access token",
                                 placeholder: p.has_token ? "saved (encrypted)" : "only if your server needs one" }) as HTMLInputElement;
    const status = phoneStatusText(p.status);
    return h("div", { class: "phone", id: "phoneReminders" }, head,
      toggle("remPhone", p.enabled, "Send reminders to my phone", async (on) => { await save({ todo_phone_notify: on }); await reload(); toast("Saved"); }),
      h("ol", { class: "steps help" },
        h("li", {}, "Install the free ", h("b", {}, "ntfy"), " app on your phone: Google Play or F-Droid (Android), App Store (iPhone)."),
        h("li", {}, "In the app tap ", h("b", {}, "+"), " and subscribe to this topic: ", topic, copy,
          otherServer ? h("span", {}, ` Turn on “Use another server” and enter ${p.server}.`) : null),
        h("li", {}, "Or scan this with the phone's camera to open the topic:", qr),
        h("li", {}, testBtn, " ", result)),
      h("p", { class: "help" }, "The topic name works like a password: anyone who has it can read your reminders. Monkey made a long random " +
        "one and keeps it encrypted on this PC. Don't post it anywhere. ",
        h("button", { class: "ghost mini", type: "button", id: "phoneRenew", onclick: async () => {
          if (!confirm("Make a new topic? Your phone stops getting reminders until you subscribe to the new one.")) return;
          const r = await api.phone_setup(true);
          if (!r.ok) return toast(`⚠ ${r.error}`);
          phoneMsg = ""; ch = r; draw(); toast("New topic made: subscribe to it on your phone");
        } }, "New topic")),
      toggle("remPhoneText", p.show_text, "Show the to-do on my phone (off: it only says “You have a reminder”)",
        async (on) => { await save({ todo_phone_show_text: on }); await reload(); toast("Saved"); }),
      h("p", { class: "help", id: "phonePrivacy" }, "With this on, the text (for example “Call the dentist, due today 5:00 PM”) travels through the " +
        `ntfy server (${otherServer ? p.server : "ntfy.sh, a free public service"}), which passes it to your phone and keeps it for up to ` +
        "12 hours. Turn it off to keep your to-dos off that server."),
      h("details", { id: "ntfyAdvanced" }, h("summary", {}, "Own ntfy server or access token (optional)"),
        h("div", { class: "field" }, h("span", {}, "Server"), serverIn,
          h("button", { class: "ghost", type: "button", onclick: async () => {
            const r = await api.phone_save_server(serverIn.value);
            if (!r.ok) return toast(`⚠ ${r.error}`, 7000);
            serverIn.value = r.server ?? serverIn.value; await reload(); toast("✓ Server saved");
          } }, "Save")),
        h("div", { class: "field" }, h("span", {}, "Access token"), tokenIn,
          h("button", { class: "ghost", type: "button", onclick: async () => {
            if (!tokenIn.value.trim()) return;
            const r = await api.save_key("ntfy_token", tokenIn.value.trim());
            tokenIn.value = "";
            if (!r.ok) return toast(`⚠ ${r.error}`);
            await reload(); toast("✓ Token saved (encrypted)");
          } }, "Save"),
          p.has_token ? h("button", { class: "ghost", type: "button", title: "Remove the token", onclick: async () => {
            await api.delete_key("ntfy_token"); await reload(); toast("Token removed");
          } }, "✕") : null),
        h("p", { class: "help" }, "Only for a server that needs sign-in. Paste the token here, never in a chat. It's saved encrypted on this PC like your other keys.")),
      h("p", { class: `help ${p.status?.state === "failed" ? "keynote bad" : ""}`, id: "phoneStatus" }, status));
  }

  function draw() {
    if (!ch.ok) {
      body.replaceChildren(h("p", { class: "help keynote bad" }, `⚠ ${ch.error ?? "Couldn't load the reminder settings."}`));
      return;
    }
    body.replaceChildren(
      h("p", { class: "help" }, "When a to-do has a due time, Monkey reminds you a few minutes before, once (Snooze brings it back). " +
        "He has to be running; hidden in the tray is fine. Each place below is its own switch."),
      toggle("remInApp", s.todo_reminders !== false, "In Monkey's window (a note with Done and Snooze)",
        async (on) => { await save({ todo_reminders: on }); toast("Saved"); }),
      toggle("remSpeak", !!s.todo_speak_reminders, "Also say it out loud", async (on) => { await save({ todo_speak_reminders: on }); toast("Saved"); }),
      windowsBlock(),
      phoneBlock());
  }

  // first load: a skeleton of the two blocks if the app is slow to answer (loader.ts); errors keep draw()'s message
  void loadInto(() => body, () => api.reminder_channels(), { what: "your reminder settings", skel: "block", rows: 4, art: "bananas", failed: () => null })
    .then(({ value }) => { ch = value; draw(); });
  return sec;
}
