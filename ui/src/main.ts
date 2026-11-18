import DOMPurify from "dompurify";
import { marked } from "marked";

import { Avatar } from "./avatar";
import { Avatar3D, webglAvailable } from "./avatar3d";
import type { AvatarLike, AvatarState } from "./avatar-types";
import { type Api, type AppState, type Importance, waitForApi } from "./bridge";
import { type Child, fmtTime, h, safeHttp, toast } from "./dom";
import { renderAssignments, markChecked } from "./assignments";
import { renderHealth } from "./health";
import { decorateJungle } from "./jungle";
import { renderAvatarLab } from "./avatarlab";
import { brainEvent, openBrain } from "./brain";
import "@fontsource/lilita-one/latin-400.css";
import "./style.css";
import "./game.css";

const $ = <T extends HTMLElement>(sel: string) => document.querySelector<T>(sel)!;
const md = (text: string) => {
  const div = h("div", { class: "md" });
  div.innerHTML = DOMPurify.sanitize(marked.parse(text, { async: false }) as string);
  div.querySelectorAll("a").forEach((a) => a.addEventListener("click", (e) => { e.preventDefault(); api.open_url(a.href); }));
  return div;
};


// ------------------------------------------------------------------ state
let api: Api;
let appState: AppState;
let importance: Importance = "normal";
let botBubble: HTMLElement | null = null;
// 3D monkey when WebGL works and the model loads; otherwise the SVG monkey.
let avatar: AvatarLike;
const avatarHost = $("#avatar");
const forceSvg = new URLSearchParams(location.search).has("svg");
if (!forceSvg && webglAvailable()) {
  const a3 = new Avatar3D(avatarHost);
  (window as any).__monkeyAvatarObj = a3;
  avatar = a3;
  (window as any).__monkeyAvatar = { ready: false, kind: "3d", clips: [], morphs: [] };
  a3.ready.then(() => {
    (window as any).__monkeyAvatar = { ready: true, kind: "3d", clips: a3.clips, morphs: a3.morphs };
  }).catch((err) => {
    console.warn("3D avatar failed, using SVG:", err);
    avatar = new Avatar(avatarHost);
    (window as any).__monkeyAvatar = { ready: true, kind: "svg", clips: [], morphs: [] };
  });
} else {
  avatar = new Avatar(avatarHost);
  (window as any).__monkeyAvatar = { ready: true, kind: "svg", clips: [], morphs: [] };
}
decorateJungle($("#stage"));
const LABELS: Record<AvatarState, string> = {
  idle: "Chillin' in the jungle", listening: "Ears up…", transcribing: "Got it…", thinking: "Thinking… 🍌", speaking: "Talking",
};
function setState(s: AvatarState) {
  avatar.setState(s);
  $("#stateLabel").textContent = LABELS[s] ?? s;
}

// ------------------------------------------------------------------ log + cards
const log = $("#log");
function addMsg(kind: "user" | "bot" | "sys", text: string) {
  const el = h("div", { class: `msg ${kind}` }, text);
  log.append(el);
  log.scrollTop = log.scrollHeight;
  return el;
}
const cards = $("#cards");
function card(title: string, ...body: Child[]) {
  const c = h("div", { class: "card" },
    h("button", { class: "close", title: "Close", onclick: () => c.remove() }, "✕"),
    h("h3", {}, title), ...body);
  cards.prepend(c);
  while (cards.children.length > 4) cards.lastElementChild!.remove();
  return c;
}

function draftCard(d: any) {
  document.querySelectorAll(`.draft[data-id="${d.draft_id}"]`).forEach((n) => n.remove());
  const subj = h("input", { value: d.subject });
  const body = h("textarea", {}, d.body);
  const status = h("span", { class: "badge" }, d.account === "outlook" ? "wisc.edu Outlook" : "Gmail");
  const c = card("✉️ Draft for your approval",
    h("div", {}, status, " ", h("span", { class: "meta" }, "Nothing is sent until you approve.")),
    h("label", {}, "To"), h("input", { value: [...d.to, ...(d.cc?.length ? ["cc: " + d.cc.join(", ")] : [])].join(", "), readOnly: true }),
    h("label", {}, "Subject"), subj,
    h("label", {}, "Message"), body,
  );
  c.classList.add("draft");
  c.dataset.id = d.draft_id;
  const send = h("button", { class: "send", type: "button" }, "Send");
  send.addEventListener("click", async () => {
    send.disabled = true;
    if (subj.value !== d.subject || body.value !== d.body) {
      const r = await api.edit_draft(d.draft_id, d.token, subj.value, body.value);
      if (!r.ok) { toast(r.error ?? "Couldn't save edits"); send.disabled = false; return; }
    }
    const r = await api.approve(d.draft_id, d.token);
    if (r.ok) {
      c.classList.add("sent");
      c.querySelector(".actions")!.replaceChildren(h("strong", {}, "✓ Sent"));
      addMsg("sys", `Email sent to ${d.to.join(", ")}`);
    } else { toast(r.error ?? "Send failed"); send.disabled = false; }
  });
  c.append(h("div", { class: "actions" },
    send,
    h("button", { class: "ghost", type: "button", onclick: () => api.open_draft(d.draft_id) },
      d.account === "outlook" ? "Open in Outlook" : "Open in Gmail"),
    h("button", { class: "ghost", type: "button", onclick: () => { api.cancel_draft(d.draft_id); c.remove(); } }, "Discard"),
  ));
}

function rankingCard(p: any) {
  card("📋 What matters", h("p", {}, p.summary),
    h("ul", { class: "items" }, ...p.items.map((it: any) => h("li", {},
      h("span", { class: `tier ${it.tier}` }, it.tier),
      h("div", {},
        h("div", {}, it.kind === "event" ? it.title : it.subject),
        h("div", { class: "meta" },
          it.kind === "event" ? `${fmtTime(it.start)} · ${it.source}` : `${it.sender} · ${fmtTime(it.received)}`,
          " — ", it.reason))))));
}

function eventsCard(p: any) {
  if (!p.events.length) return;
  card("📅 Calendar", h("ul", { class: "items" }, ...p.events.map((e: any) => h("li", {},
    h("span", { class: "badge" }, e.source),
    h("div", {}, h("div", {}, e.title), h("div", { class: "meta" }, `${fmtTime(e.start)}${e.location ? " · " + e.location : ""}`))))));
}

function emailsCard(p: any) {
  if (!p.emails.length) return;
  card("📥 Email", h("ul", { class: "items" }, ...p.emails.slice(0, 12).map((e: any) => h("li", {},
    h("span", { class: "badge" }, e.account),
    h("div", {}, h("div", {}, (e.unread ? "● " : "") + e.subject),
      h("div", { class: "meta" }, `${e.sender} · ${fmtTime(e.received)}`))))));
}

function imagesCard(p: any) {
  const okSrc = (u: string) => (/^data:image\/(png|jpeg|webp);base64,/.test(u) ? u : safeHttp(u));
  card(`${p.generated ? "✨" : "🖼️"} ${p.query}`, h("div", { class: "grid" }, ...p.images.filter((i: any) => okSrc(i.src)).map((i: any) =>
    h("img", { src: okSrc(i.thumb || i.src), alt: i.title, title: i.title, loading: "lazy",
               onclick: () => i.page && api.open_url(i.page) }))));
}

function videosCard(p: any) {
  const vids = p.videos as any[];
  if (!vids.length) return;
  const player = h("iframe", {
    class: "video", allow: "autoplay; encrypted-media; picture-in-picture", allowFullscreen: true,
    src: `${vids[0].embed}?autoplay=${p.autoplay ? 1 : 0}`,
  });
  card(`▶️ ${p.query}`, player, h("div", { class: "vlist" }, ...vids.map((v) => h("button", {
    type: "button", onclick: () => { player.src = `${v.embed}?autoplay=1`; },
  }, h("img", { src: safeHttp(v.thumb), alt: "" }), v.title))));
}

function weatherCard(p: any) {
  card(`🌤️ Weather ${p.location ? "· " + p.location : ""}`, h("ul", { class: "items" },
    ...p.periods.map((x: any) => h("li", {}, h("strong", {}, x.temp), h("div", {}, h("div", {}, `${x.name}: ${x.short}`),
      h("div", { class: "meta" }, x.wind))))));
}

function assignmentsCard(board: any) {
  document.querySelectorAll(".card.assign").forEach((c) => c.remove());
  const c = card("✅ Assignments");
  c.querySelector("h3")!.append(h("button", {
    class: "ghost mini", type: "button", title: "Refresh from Canvas",
    onclick: async () => { const r = await api.get_assignments(true); if (r.ok) assignmentsCard(r); else toast(`⚠ ${r.error}`); },
  }, "↻"));
  renderAssignments(c, board, async (id, done) => {
    const r = await api.toggle_assignment(id, done);
    if (r.ok && done) avatar.emote("celebrate");
    return r;
  }, (u) => api.open_url(u));
}

function healthCard(hd: any) {
  document.querySelectorAll(".card.health").forEach((c) => c.remove());
  const label = hd.date === new Date().toISOString().slice(0, 10) ? "today" : hd.date;
  const c = card(`❤️ Health · ${label}`);
  renderHealth(c, hd);
}

// ------------------------------------------------------------------ events from Python
function onEvent(name: string, p: any) {
  switch (name) {
    case "state": setState(p.state); if (p.state === "idle") botBubble = null; break;
    case "level": avatar.setLevel(p.v); break;
    case "visemes": avatar.setVisemes(p); break;
    case "user": addMsg("user", p.text); botBubble = null; break;
    case "delta":
      if (!botBubble) botBubble = addMsg("bot", "");
      botBubble.textContent += p.text; log.scrollTop = log.scrollHeight; break;
    case "done": botBubble = null; break;
    case "route":
      $("#routeChip").textContent = p.label;
      $("#routeChip").title = `${p.task ? p.task.replace(/_/g, " ") + ": " : ""}${p.reason}`; break;
    case "calibration": brainEvent(p); break;
    case "panel": card(p.title, md(p.markdown)); break;
    case "draft": draftCard(p); break;
    case "approval":
      if (p.action === "sent") avatar.emote("celebrate");
      if (p.action === "sent") document.querySelectorAll(".draft:not(.sent)").forEach((c) => {
        c.classList.add("sent"); c.querySelector(".actions")?.replaceChildren(h("strong", {}, "✓ Sent"));
      });
      if (p.action === "cancelled") document.querySelectorAll(".draft:not(.sent)").forEach((c) => c.remove());
      break;
    case "ranking": rankingCard(p); break;
    case "events": eventsCard(p); break;
    case "emails": emailsCard(p); break;
    case "images": imagesCard(p); break;
    case "videos": videosCard(p); break;
    case "weather": weatherCard(p); break;
    case "assignments": assignmentsCard(p); break;
    case "assignment_checked": markChecked(p.id, p.done); if (p.done) avatar.emote("celebrate"); break;
    case "emote": avatar.emote(p.name); break;
    case "health": healthCard(p); break;
    case "cleanup": cleanupCard(p); break;
    case "update":
      if (p.status === "ready") updateToast(p);
      break;
    case "sources":
      card("🔎 Sources", h("div", { class: "sources" }, ...p.sources.map((s: any) =>
        h("a", { href: s.url, onclick: (e: Event) => { e.preventDefault(); api.open_url(s.url); } }, s.title || s.url))));
      break;
    case "opened": addMsg("sys", `Opened ${p.url}`); break;
    case "memory": addMsg("sys", `🧠 Memory ${p.command}: ${p.path ?? ""}`); break;
    case "cost": $("#spend").textContent = `$${p.month.toFixed(2)} this month`; break;
    case "warning": addMsg("sys", "⚠ " + p.message); break;
    case "wake": addMsg("sys", "👂 Hey Monkey"); break;
    case "heard": if (!p.text) addMsg("sys", "Didn't catch that."); break;
    case "error": addMsg("sys", "⚠ " + p.message); setState("idle"); break;
    case "hint": $("#hint").textContent = p.text; break;
  }
}
window.__monkeyEvents = (events) => { for (const [n, p] of events) { try { onEvent(n, p); } catch (e) { console.error(n, e); } } };

// ------------------------------------------------------------------ composer
$("#importance").addEventListener("click", (e) => {
  const b = (e.target as HTMLElement).closest("button");
  if (!b) return;
  importance = b.dataset.v as Importance;
  document.querySelectorAll("#importance button").forEach((x) => x.classList.toggle("on", x === b));
});
$("#composer").addEventListener("submit", (e) => {
  e.preventDefault();
  const input = $<HTMLInputElement>("#input");
  const text = input.value.trim();
  if (!text) return;
  input.value = "";
  api.send_text(text, importance === "normal" ? null : importance);
});
$("#mic").addEventListener("click", () => api.push_to_talk());
$("#newChat").addEventListener("click", () => { api.new_conversation(); log.replaceChildren(); addMsg("sys", "New conversation"); });
$("#settingsBtn").addEventListener("click", () => openSettings());
$("#labBtn").addEventListener("click", () => {
  document.querySelectorAll(".card.lab").forEach((c) => c.remove());
  const c = card("🧪 Avatar Lab");
  renderAvatarLab(c, api);
});

function cleanupCard(plan: { items?: { kind: string; label: string; path: string; status?: string; detail?: string }[] }) {
  document.querySelectorAll(".card.cleanup").forEach((c) => c.remove());
  const items = plan.items ?? [];
  if (!items.length) return toast("No old Monkey installs or downloads found 👍");
  const c = card("🧹 Clean up old Monkey");
  c.classList.add("cleanup");
  const list = h("ul", { class: "items" }, ...items.map((i) => h("li", {},
    h("span", { class: "badge" }, i.kind === "download" ? "file" : i.kind),
    h("div", {}, h("div", {}, i.label), h("div", { class: "meta" }, i.path)))));
  const go = h("button", { type: "button", class: "primary" }, "Clean up");
  const later = h("button", { type: "button", class: "ghost" }, "Not now");
  go.addEventListener("click", async () => {
    go.disabled = true;
    go.textContent = "Cleaning…";
    const r = await api.cleanup_run();
    if (!r.ok) { toast(`⚠ ${r.error}`); go.disabled = false; go.textContent = "Clean up"; return; }
    const done = (r.items ?? []).filter((i) => i.status === "ok").length;
    const failed = (r.items ?? []).filter((i) => i.status === "error");
    list.replaceChildren(...(r.items ?? []).map((i) => h("li", {},
      h("span", { class: `badge` }, i.status === "ok" ? "✓" : "⚠"),
      h("div", {}, h("div", {}, i.label), h("div", { class: "meta" }, i.detail)))));
    go.remove(); later.remove();
    toast(`Cleaned up ${done} item${done === 1 ? "" : "s"}${failed.length ? ` · ${failed.length} couldn't be removed` : ""}`);
    if (done) avatar.emote("celebrate");
  });
  later.addEventListener("click", () => { api.cleanup_dismiss(); c.remove(); });
  c.append(
    h("p", { class: "meta" }, "These are from earlier Monkey/Tyrone versions. Old apps get uninstalled, and downloads go to the Recycle Bin so you can undo. Your memory, settings and keys are kept."),
    list, h("div", { class: "actions draft" }, go, later));
}

function updateToast(u: { available: string }) {
  document.querySelector(".update-toast")?.remove();
  const btn = h("button", { type: "button", class: "primary" }, "Restart & update");
  btn.addEventListener("click", async () => { btn.disabled = true; const r = await api.apply_update(); if (r.error) toast(`⚠ ${r.error}`); });
  document.body.append(h("div", { class: "update-toast" },
    h("strong", {}, `🍌 Monkey ${u.available} is ready`), h("span", {}, "Takes a few seconds; your memory and keys stay put."), btn,
    h("button", { type: "button", class: "ghost mini", onclick: (e: Event) => (e.target as HTMLElement).closest(".update-toast")?.remove() }, "Later")));
}

$("#asgBtn").addEventListener("click", async () => {
  const r = await api.get_assignments(false);
  if (!r.ok) return toast(`⚠ ${r.error}`);
  if (r.source === "none") return toast("Connect Canvas in Settings (token or calendar feed)");
  assignmentsCard(r);
});
$("#healthBtn").addEventListener("click", async () => {
  const r = await api.get_health("today");
  if (!r.ok) return toast(`⚠ ${r.error}`);
  healthCard(r.health);
});
document.addEventListener("keydown", (e) => { if (e.key === "Escape") api.stop_speaking(); });

// ------------------------------------------------------------------ settings
const KEY_INFO: [string, string, string][] = [
  ["anthropic", "Anthropic (Claude)", "Required. console.anthropic.com → API keys."],
  ["fish", "Fish Audio", "Monkey's voice. fish.audio → API keys."],
  ["deepgram", "Deepgram (optional)", "Faster speech recognition. Leave empty to use free local Whisper."],
  ["youtube", "YouTube Data API (optional)", "For showing videos. Google Cloud → APIs → YouTube Data API v3 → API key."],
  ["brave", "Brave Search (optional)", "Better image search. Without it, images come from Wikimedia Commons."],
  ["openai", "OpenAI (optional)", "For generating images and new Monkey designs with GPT Image 2.6 (Avatar Lab)."],
  ["canvas_token", "Canvas API token (optional)", "Unlocks points, grades & missing status for ranking. UW–Madison: request one via the Learn@UW 'Student Request for Canvas Access Token' form (kb.wisc.edu/156712), then activate it in Canvas."],
];

async function openSettings() {
  appState = await api.get_state();
  const s = appState.settings;
  const dlg = $<HTMLDialogElement>("#settings");
  const status = (on: boolean) => h("span", { class: `dot ${on ? "on" : ""}` });
  const keyRow = ([name, label, help]: [string, string, string]) => {
    const hint = appState.key_hints?.[name];
    const inp = h("input", { type: "password", placeholder: appState.keys[name] ? `saved ••••${hint ?? ""}` : "paste key" });
    const note = h("p", { class: "keynote" },
      appState.keys[name] ? `✓ Saved${hint ? ` (ends in ${hint})` : ""}. Stays saved after restarts and updates.` : "");
    const save = async () => {
      if (!inp.value.trim()) return;
      const r = await api.save_key(name, inp.value.trim());
      if (!r.ok) { note.className = "keynote bad"; note.textContent = `⚠ Not saved: ${r.error}`; return; }
      inp.value = ""; toast(`✓ ${label} saved. It'll be there next time you open Monkey.`, 4000);
      await openSettings();
    };
    inp.addEventListener("keydown", (e) => { if ((e as KeyboardEvent).key === "Enter") { e.preventDefault(); save(); } });
    return h("div", {},
      h("div", { class: "field" }, status(!!appState.keys[name]), h("span", {}, label), inp,
        h("button", { class: "ghost", type: "button", onclick: save }, "Save"),
        appState.keys[name] && h("button", { class: "ghost", type: "button", title: "Remove this key", onclick: async () => {
          if (!confirm(`Remove the saved ${label} key?`)) return;
          await api.delete_key(name); toast(`${label} removed`); openSettings();
        } }, "✕")),
      note,
      h("p", { class: "help" }, help),
      name === "anthropic" && h("p", { class: "help maxhelp" },
        "Have Claude Max? It includes $100/month of API credits, so Monkey costs you nothing extra. claude.ai → Settings → Billing → ",
        h("b", {}, "API credits"), " → link a Console org, then create a key at platform.claude.com → API keys and paste it here. ",
        h("a", { href: "#", onclick: (e: Event) => { e.preventDefault(); api.open_url("https://claude.ai/settings/billing"); } }, "Open billing settings"),
        " · ",
        h("a", { href: "#", onclick: (e: Event) => { e.preventDefault(); api.open_url("https://platform.claude.com/settings/keys"); } }, "Create a key")));
  };
  const field = (label: string, key: string, type = "text", extra: Record<string, any> = {}) => {
    const inp = h("input", { type, value: s[key] ?? "", ...extra });
    inp.addEventListener("change", async () => {
      const v = type === "number" ? Number(inp.value) : inp.value;
      appState = await api.save_settings({ [key]: v });
      toast("Saved");
    });
    return h("div", { class: "field" }, h("span", {}, label), inp);
  };
  const resultToast = (r: { ok: boolean; error?: string }, ok: string) => toast(r.ok ? ok : `⚠ ${r.error}`);
  const voiceOut = h("div", {});
  const instr = h("textarea", { rows: 3 },
    "An original adult male character voice, around 40, from New York City. Deep, smooth, slightly raspy baritone, calm laid-back confident delivery, subtle New York accent, warm and a little playful.");

  dlg.replaceChildren(h("div", { class: "settings" },
    h("header", {}, h("strong", {}, "Settings"), h("div", { class: "spacer" }),
      h("button", { class: "icon", onclick: () => dlg.close() }, "✕")),
    h("div", { class: "body" },
      h("section", {}, h("h4", {}, "You"), field("Your first name", "user_name")),
      h("section", {}, h("h4", {}, "API keys"),
        h("p", { class: "help" }, "Encrypted with your Windows account (" + (appState.secrets_backend ?? "DPAPI") +
          ") in Monkey's own folder on this PC. They stay saved through restarts and updates, and never go in the repo or memory exports."),
        ...KEY_INFO.map(keyRow)),
      h("section", {}, h("h4", {}, "Monkey's voice (Fish Audio)"),
        h("p", { class: "help" }, "Design an original voice from a description, pick a candidate, and Monkey keeps it. Or design it on fish.audio and paste the voice ID."),
        instr,
        h("div", { class: "field" },
          h("button", { class: "primary", type: "button", onclick: async () => {
            voiceOut.replaceChildren("Designing voices… (takes ~30s)");
            const r = await api.voice_design(instr.value);
            if (!r.ok) { voiceOut.replaceChildren(`⚠ ${r.error}`); return; }
            voiceOut.replaceChildren(...(r.candidates ?? []).map((b64, i) => h("div", { class: "field" },
              h("audio", { controls: true, src: `data:audio/wav;base64,${b64}` }),
              h("button", { class: "ghost", type: "button", onclick: async () => {
                const c = await api.choose_voice(i); resultToast(c, "Voice saved — that's Monkey now"); openSettings();
              } }, "Use this one"))));
          } }, "Design voices"),
          h("button", { class: "ghost", type: "button", onclick: () => api.test_voice() }, "Test voice")),
        voiceOut,
        field("Fish voice ID", "fish_voice_id", "text", { placeholder: "reference_id from fish.audio" }),
        field("Fish model", "fish_model")),
      h("section", {}, h("h4", {}, "Wake word & mic"),
        h("p", { class: "help" }, `Active wake word: ${appState.wakeword}. Push-to-talk hotkey works anytime.`),
        field("Sensitivity (0.3–0.9)", "wakeword_threshold", "number", { step: "0.05", min: "0.3", max: "0.9" }),
        field("Push-to-talk hotkey", "push_to_talk_hotkey"),
        h("div", { class: "field" }, h("span", {}, "Speech recognition"), (() => {
          const sel = h("select", {}, h("option", { value: "whisper" }, "Local Whisper (free, private)"),
            h("option", { value: "deepgram" }, "Deepgram Nova-3 (faster, needs key)"));
          sel.value = s.stt_engine;
          sel.addEventListener("change", async () => { appState = await api.save_settings({ stt_engine: sel.value }); toast("Saved"); });
          return sel;
        })())),
      h("section", {}, h("h4", {}, "Accounts"),
        h("p", { class: "help" }, "Gmail/Google Calendar: paste your Google OAuth Desktop-client JSON, then Sign in. wisc.edu: needs classic Outlook signed in on this PC. Canvas: Calendar → Calendar Feed → copy link."),
        (() => {
          const ta = h("textarea", { rows: 2, placeholder: appState.keys.google_client ? "Google client JSON saved" : "Google OAuth client JSON" });
          return h("div", { class: "field" }, status(!!appState.keys.google_client), h("span", {}, "Google client"), ta,
            h("button", { class: "ghost", type: "button", onclick: async () => {
              if (!ta.value.trim()) return;
              const r = await api.save_key("google_client", ta.value.trim());
              toast(r.ok ? "✓ Saved" : `⚠ Not saved: ${r.error}`); openSettings();
            } }, "Save"));
        })(),
        h("div", { class: "field" }, status(!!appState.connections.gmail), h("span", {}, "Gmail + Google Calendar"),
          h("button", { class: "primary", type: "button", onclick: async () => {
            const r = await api.google_sign_in(); resultToast(r, "Google connected"); openSettings();
          } }, appState.connections.gmail ? "Reconnect" : "Sign in"),
          appState.connections.gmail && h("button", { class: "ghost", type: "button", onclick: async () => { await api.google_sign_out(); openSettings(); } }, "Sign out")),
        h("div", { class: "field" }, status(!!appState.connections.outlook), h("span", {}, "wisc.edu Outlook"),
          h("button", { class: "ghost", type: "button", onclick: async () => {
            const r = await api.test_outlook(); resultToast(r, "Outlook connected"); openSettings();
          } }, "Test connection")),
        field("Canvas calendar feed URL", "canvas_ics_url", "url", { placeholder: "https://canvas.wisc.edu/feeds/calendars/user_….ics" }),
        field("Canvas site", "canvas_base_url", "url"),
        h("div", { class: "field" }, h("span", {}, "Email writing style"),
          h("button", { class: "ghost", type: "button", onclick: async () => {
            toast("Reading your sent emails… (about a minute)", 6000);
            const r = await api.learn_style(); resultToast(r, "Learned your writing style");
          } }, "Learn my writing style"))),
      h("section", {}, h("h4", {}, "Garmin"),
        h("p", { class: "help" }, "Sleep score, heart rate, HRV, body battery. Your password is used once to sign in and is never saved."),
        (() => {
          const email = h("input", { type: "email", placeholder: "Garmin email" });
          const pw = h("input", { type: "password", placeholder: "Garmin password" });
          const code = h("input", { placeholder: "6-digit code", inputMode: "numeric", hidden: true });
          const go = h("button", { class: "primary", type: "button" }, appState.connections.garmin ? "Reconnect" : "Sign in");
          go.addEventListener("click", async () => {
            go.disabled = true;
            const r = code.hidden ? await api.garmin_login(email.value, pw.value) : await api.garmin_mfa(code.value);
            go.disabled = false;
            if (!r.ok) return toast(`⚠ ${r.error}`);
            if (r.status === "needs_mfa") { code.hidden = false; go.textContent = "Verify code"; toast("Enter the code Garmin sent you"); return; }
            pw.value = ""; toast("Garmin connected"); openSettings();
          });
          return h("div", {},
            h("div", { class: "field" }, status(!!appState.connections.garmin), h("span", {}, "Garmin Connect"), email),
            h("div", { class: "field" }, h("span", {}, ""), pw),
            h("div", { class: "field" }, h("span", {}, ""), code, go,
              appState.connections.garmin && h("button", { class: "ghost", type: "button", onclick: async () => { await api.garmin_logout(); openSettings(); } }, "Sign out")));
        })()),
      h("section", {}, h("h4", {}, "Brain & budget"),
        h("p", { class: "help" }, `This month: $${appState.month_usd.toFixed(2)} of $${appState.budget_usd.toFixed(2)}. ` +
          appState.breakdown.map((b) => `${b.model.replace("claude-", "")}: ${b.calls} calls $${b.usd.toFixed(2)}`).join(" · ")),
        h("label", { class: "field toggle" }, (() => {
          const cb = h("input", { type: "checkbox" }) as HTMLInputElement;
          cb.checked = !!s.max_credits;
          cb.addEventListener("change", async () => {
            appState = await api.save_settings(cb.checked
              ? { max_credits: true, monthly_budget_usd: 95, brain_profile: "best" }
              : { max_credits: false });
            toast(cb.checked ? "Budget set to $95 so Monkey stays inside your free $100 of Max credits" : "Saved", 4000);
            openSettings();
          });
          return cb;
        })(), h("span", {}, "I'm paying with my Claude Max plan's API credits ($100/month)")),
        field("Monthly budget (USD)", "monthly_budget_usd", "number", { min: "1", step: "1" }),
        h("div", { class: "field" }, h("span", {}, "Model"), (() => {
          const sel = h("select", {},
            h("option", { value: "" }, "Automatic (recommended)"),
            h("option", { value: "claude-opus-5-5" }, "Always Opus 5.5"),
            h("option", { value: "claude-sonnet-5-5" }, "Always Sonnet 5.5"),
            h("option", { value: "claude-haiku-5-5" }, "Always Haiku 5.5"));
          sel.value = s.force_model ?? "";
          sel.addEventListener("change", async () => { appState = await api.save_settings({ force_model: sel.value }); toast("Saved"); });
          return sel;
        })()),
        h("div", { class: "field" }, h("span", {}, "Models per task"),
          h("button", { class: "primary", type: "button", onclick: () => openBrain(api) }, "🧠 Open model table & calibrate")),
        h("div", { class: "field" }, h("span", {}, "Brain profile"), (() => {
          const sel = h("select", {},
            h("option", { value: "best" }, "Auto: each task's recommended model (~$29/mo heavy use)"),
            h("option", { value: "saver" }, "Saver: each task's cheapest model that works (~$17/mo)"));
          sel.value = s.brain_profile ?? "best";
          sel.addEventListener("change", async () => { appState = await api.save_settings({ brain_profile: sel.value }); toast("Saved"); });
          return sel;
        })())),
      h("section", {}, h("h4", {}, "Images & updates"),
        h("div", { class: "field" }, h("span", {}, "Image model"), (() => {
          const sel = h("select", {},
            h("option", { value: "gpt-image-2.6-sunburst" }, "GPT Image 2.6 Sunburst (best detail)"),
            h("option", { value: "gpt-image-2.6-flare" }, "GPT Image 2.6 Flare (faster drafts)"));
          sel.value = s.image_model ?? "gpt-image-2.6-sunburst";
          sel.addEventListener("change", async () => { appState = await api.save_settings({ image_model: sel.value }); toast("Saved"); });
          return sel;
        })()),
        (() => {
          const out = h("span", { class: "meta" }, "");
          api.update_state().then((u) => { out.textContent = u.status === "unavailable" ? "Auto-update works after installing with the new MonkeySetup.exe" : `Version ${u.current || appState.version} · ${u.status.replace("_", " ")}`; });
          const auto = h("input", { type: "checkbox", checked: s.auto_update !== false });
          auto.addEventListener("change", async () => { appState = await api.save_settings({ auto_update: auto.checked }); toast("Saved"); });
          return h("div", {},
            h("div", { class: "field" }, h("span", {}, "Updates"), out,
              h("button", { class: "ghost", type: "button", onclick: async () => {
                out.textContent = "Checking…";
                const u = await api.check_update();
                out.textContent = u.status === "ready" ? `Update ${u.available} downloaded` : u.status === "up_to_date" ? "You're on the latest version" : (u.detail || u.status);
                if (u.status === "ready") updateToast(u);
              } }, "Check now"),
              h("button", { class: "ghost", type: "button", onclick: async () => {
                const r = await api.cleanup_plan();
                if (!r.ok) return toast(`⚠ ${r.error}`);
                $<HTMLDialogElement>("#settings").close();
                cleanupCard(r);
              } }, "Clean up old installs")),
            h("label", { class: "field" }, auto, h("span", {}, "Download updates automatically")));
        })()),
      h("section", {}, h("h4", {}, "Memory"),
        h("p", { class: "help" }, `Files: ${appState.memory_files.join(", ")}. Plain markdown you can edit. Export to move Monkey to another PC (encrypted with your password).`),
        field("Sync folder (optional, e.g. OneDrive)", "memory_dir_override", "text", { placeholder: "C:\\Users\\you\\OneDrive\\Monkey" }),
        (() => {
          const pw = h("input", { type: "password", placeholder: "export/import password (8+ chars)" });
          return h("div", { class: "field" }, pw,
            h("button", { class: "ghost", type: "button", onclick: async () => resultToast(await api.export_memory(pw.value), "Exported") }, "Export"),
            h("button", { class: "ghost", type: "button", onclick: async () => resultToast(await api.import_memory(pw.value), "Imported — restart Monkey") }, "Import"),
            h("button", { class: "ghost", type: "button", onclick: () => api.open_memory_folder() }, "Open folder"));
        })()),
      h("p", { class: "help" }, `Monkey ${appState.version}`),
    )));
  if (!dlg.open) dlg.showModal();
}

// ------------------------------------------------------------------ earlier chat (survives restarts)
async function restoreTranscript() {
  let items: { ts: string; role: string; text: string }[] = [];
  try { items = await api.get_transcript(40); } catch { return; }
  if (!items?.length) return;
  const when = new Date(items[items.length - 1].ts);
  const label = isNaN(+when) ? "Earlier" :
    `Earlier · ${when.toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" })} ` +
    when.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
  for (const it of items) addMsg(it.role === "user" ? "user" : "bot", it.text).classList.add("earlier");
  log.append(h("div", { class: "divider" }, h("span", {}, label.replace("Earlier", "↑ Earlier"))));
  log.scrollTop = log.scrollHeight;
}

// ------------------------------------------------------------------ boot
(async () => {
  api = await waitForApi();
  (window as any).__monkeyBooted = true;
  appState = await api.get_state();
  setState("idle");
  $("#hint").textContent = `Say “${appState.wakeword.split(" (")[0]}” or press ${appState.settings.push_to_talk_hotkey}`;
  $("#spend").textContent = `$${appState.month_usd.toFixed(2)} this month`;
  await restoreTranscript();
  if (!appState.keys.anthropic || !appState.settings.first_run_complete) {
    addMsg("sys", "Welcome! Add your Anthropic and Fish Audio keys in Settings to get started.");
    openSettings();
  } else {
    addMsg("sys", "Monkey's ready.");
  }
})();
