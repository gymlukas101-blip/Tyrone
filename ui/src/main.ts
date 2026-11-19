import DOMPurify from "dompurify";
import { marked } from "marked";

import { Avatar } from "./avatar";
import { Avatar3D, webglAvailable } from "./avatar3d";
import type { AvatarLike, AvatarState } from "./avatar-types";
import { type Api, type AppState, type Brief, type Importance, waitForApi } from "./bridge";
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
let sentenceBuf = "";
// 3D monkey when WebGL works and the model loads; otherwise the SVG monkey.
let avatar: AvatarLike;
const avatarHost = $("#avatar");
const forceSvg = new URLSearchParams(location.search).has("svg");
if (!forceSvg && webglAvailable()) {
  // ?model=rt.glb loads models/rt.glb instead (previewing a Blender export in the demo build).
  const alt = new URLSearchParams(location.search).get("model");
  const a3 = new Avatar3D(avatarHost, alt && /^[\w.-]+\.glb$/.test(alt) ? `models/${alt}` : undefined);
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

/** Hook the recorded sound kit into the avatar's sound engine (bundled files + sounds made on this PC). */
let soundsAttached = false;
function attachSounds(s: Record<string, any>) {
  const a3 = (window as any).__monkeyAvatarObj as Avatar3D | undefined;
  if (!a3) return;
  a3.sfx.rejects = new Set<string>(s.sfx_rejects ?? []);
  if (soundsAttached) return;
  soundsAttached = true;
  void a3.sfx.attach({
    bundled: async () => (await (await fetch("sfx/index.json")).json()).cues ?? {},
    user: async () => (await api.get_user_sounds()) ?? {},
    userData: async (rel) => {
      const b64 = await api.get_sound(rel);
      if (!b64) return null;
      const bin = atob(b64); const out = new Uint8Array(bin.length);
      for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
      return out.buffer;
    },
  });
  // Quiet, short UI clicks (common tier: very low level, cooldown in the engine).
  document.addEventListener("pointerdown", (e) => {
    if ((e.target as HTMLElement)?.closest("button")) a3.sfx.play("ui_click");
  }, { capture: true });
}

/** Settings → Sound: make Monkey's vocal set on this PC (Fish free model), and a Sound Lab to audition takes. */
function soundSection(s: Record<string, any>) {
  const a3 = (window as any).__monkeyAvatarObj as Avatar3D | undefined;
  const status = h("span", { class: "meta", id: "voiceKitStatus" }, "");
  const lab = h("div", { class: "soundlab" });
  const rejects = new Set<string>(s.sfx_rejects ?? []);
  const renderLab = () => {
    const cues = a3?.sfx.cues() ?? {};
    const names = Object.keys(cues).sort((x, y) => Number(y.startsWith("vocal/")) - Number(x.startsWith("vocal/")) || x.localeCompare(y));
    lab.replaceChildren(...(names.length ? names.map((cue) => h("div", { class: "cue" },
      h("span", { class: "name" }, cue.replace("vocal/", "🗣 ").replace(/_/g, " ")),
      ...cues[cue].map((src, i) => {
        const take = a3!.sfx.takeOf(src);
        const b = h("button", { type: "button", class: "take" + (rejects.has(take) ? " off" : ""),
          title: "Click to play · right-click to turn this take on/off" }, String(i + 1));
        b.addEventListener("click", () => void a3!.sfx.preview(src));
        b.addEventListener("contextmenu", async (e) => {
          e.preventDefault();
          if (rejects.has(take)) rejects.delete(take); else rejects.add(take);
          b.classList.toggle("off", rejects.has(take));
          appState = await api.save_settings({ sfx_rejects: [...rejects] });
          a3!.sfx.rejects = new Set(rejects);
        });
        return b;
      }))) : [h("p", { class: "help" }, "No recorded sounds loaded yet.")]));
  };
  renderLab();
  const make = h("button", { class: "ghost", type: "button", onclick: async () => {
    const r = await api.make_voice_kit(4);
    status.textContent = r.ok ? "Starting…" : `⚠ ${r.error}`;
  } }, "🎙 Make Monkey's voice set (optional)");
  voiceKitHooks = { status, done: async () => { await a3?.sfx.reloadUser(); renderLab(); } };
  return h("section", {}, h("h4", {}, "Sound"),
    h("p", { class: "help" }, "Monkey's grunts, laughs, yawns and snorts are made in his own Fish voice with Fish's free model " +
      "(free until Nov 30, 2026) and saved on this PC, so they keep working after that. Takes about 3–5 minutes, once. " +
      "It also saves a clean sample of his voice for the offline voice."),
    h("div", { class: "field" }, h("span", {}, "Monkey's voice set"), make, status),
    offlineVoiceRow(s),
    h("details", {}, h("summary", {}, "Sound Lab: hear every sound (click a number; right-click to turn a take off)"), lab));
}
/** Settings → Voice & sound → Backup voice: Pocket TTS clone of Monkey's voice, free forever, runs on this PC. */
function offlineVoiceRow(s: Record<string, any>) {
  const st = h("span", { class: "meta", id: "offlineVoiceStatus" }, "Checking…");
  const refresh = async () => {
    const v = await api.offline_voice_state();
    st.textContent = v.downloading ? "Downloading…" : !v.installed ? "Not downloaded yet (about 200 MB, one time)"
      : v.own_voice ? "✓ On: if the main voice is down, Monkey uses this (sounds like him)" : "✓ On: if the main voice is down, Monkey uses this (a generic voice; the voice set above makes it sound like him)";
    dl.textContent = v.installed ? "Download again" : "⬇ Download";
    dl.className = v.installed ? "ghost" : "primary";
    (dl as HTMLButtonElement).disabled = !!v.downloading;
    test.disabled = !v.installed;
  };
  const dl = h("button", { class: "primary", type: "button", onclick: async () => {
    (dl as HTMLButtonElement).disabled = true;
    const r = await api.download_offline_voice();
    st.textContent = r.ok ? "Starting download…" : `⚠ ${r.error}`;
    if (!r.ok) (dl as HTMLButtonElement).disabled = false;
  } }, "⬇ Download");
  const test = h("button", { class: "ghost", type: "button", onclick: async () => {
    const r = await api.test_offline_voice();
    toast(r.ok ? (r.own_voice ? "🔊 That's the backup voice (Monkey's own)" : "🔊 That's the backup voice (generic until you make Monkey's voice set)") : `⚠ ${r.error}`);
  } }, "▶ Hear it");
  const mode = h("select", {},
    h("option", { value: "fallback" }, "Use it when the main voice is down (recommended)"),
    h("option", { value: "only" }, "Always use it (never the Fish voice)"),
    h("option", { value: "off" }, "Don't use it (the plain Windows voice is the backup)"));
  mode.value = s.offline_voice ?? "fallback";
  mode.addEventListener("change", async () => { appState = await api.save_settings({ offline_voice: mode.value }); toast("Saved"); });
  offlineVoiceRefresh = refresh;
  void refresh();
  return h("div", {},
    h("div", { class: "field" }, h("span", {}, "Backup voice (works offline)"), dl, test, st),
    h("div", { class: "field" }, h("span", {}, ""), mode));
}
let offlineVoiceRefresh: (() => Promise<void>) | null = null;
function offlineVoiceEvent(p: any) {
  const st = document.getElementById("offlineVoiceStatus");
  if (p.finished) {
    toast(p.ok ? `✓ Backup voice downloaded (${p.mb} MB)` : `⚠ ${p.error}`, p.ok ? 4000 : 9000);
    void offlineVoiceRefresh?.();
    if (!p.ok && st) setTimeout(() => { st.textContent = `⚠ ${p.error}`; }, 300);   // never stuck on "Starting download…"
    return;
  }
  if (st) st.textContent = p.what === "unpacking" ? "Unpacking…" :
    `Downloading ${Math.round(p.done / 1e6)} / ${Math.round(p.total / 1e6) || "?"} MB`;
}
let voiceKitHooks: { status: HTMLElement; done: () => Promise<void> } | null = null;
function voiceKitEvent(p: any) {
  const st = voiceKitHooks?.status ?? document.getElementById("voiceKitStatus");
  if (p.finished) {
    const n = Object.values(p.made ?? {}).reduce((a: number, b: any) => a + Number(b), 0);
    const msg = p.ok ? `✓ Made ${n} sounds${p.reference ? " + voice sample" : ""}` : `⚠ ${p.error ?? "Stopped"}`;
    if (st) st.textContent = msg;
    toast(msg);
    if (p.ok) {
      void voiceKitHooks?.done();
      if (!voiceKitHooks) void ((window as any).__monkeyAvatarObj as Avatar3D | undefined)?.sfx.reloadUser();
      ((window as any).__monkeyAvatarObj as Avatar3D | undefined)?.sfx.play("vocal/woohoo");
    }
    return;
  }
  if (st) st.textContent = `${Math.round((100 * p.done) / Math.max(1, p.total))}% · ${p.what}`;
}

/** Apply Settings → Look & feel to the 3D avatar (juice level, SFX volume, sleep timer). */
/** Show only the header buttons that do something for this person; tech details only when asked for. */
function applyChrome(st: AppState) {
  const tech = !!st.settings.show_tech_details;
  document.body.classList.toggle("tech", tech);
  ($("#labBtn") as HTMLElement).hidden = !tech;
  ($("#healthBtn") as HTMLElement).hidden = !st.connections.garmin;
}

function applyLook(s: Record<string, any>) {
  const a3 = (window as any).__monkeyAvatarObj as Avatar3D | undefined;
  if (!a3) return;
  const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const juice = s.juice_level && s.juice_level !== "auto" ? s.juice_level : reduce ? "calm" : "full";
  a3.ready.then(() => a3.configure({ juice, volume: (s.sfx_volume ?? 70) / 100, sleepAfterMin: s.sleep_after_min ?? 8 }));
}
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
  // One card per kind: asking again replaces the old one instead of stacking a duplicate (drafts are per email).
  if (!title.startsWith("✉️")) cards.querySelectorAll<HTMLElement>(".card").forEach((old) => { if (old.dataset.title === title) old.remove(); });
  const c = h("div", { class: "card" },
    h("button", { class: "close", title: "Close", onclick: () => c.remove() }, "✕"),
    h("h3", {}, title), ...body);
  c.dataset.title = title;
  // Older cards fold to their title bar (click to open) so the conversation stays readable.
  cards.querySelectorAll<HTMLElement>(".card").forEach((old) => {
    if (!(old.classList.contains("draft") && !old.classList.contains("sent"))) old.classList.add("folded");
  });
  c.querySelector("h3")!.addEventListener("click", () => {
    if (c.classList.contains("folded")) {
      cards.querySelectorAll<HTMLElement>(".card").forEach((o) => { if (o !== c && !(o.classList.contains("draft") && !o.classList.contains("sent"))) o.classList.add("folded"); });
      c.classList.remove("folded");
    }
  });
  cards.prepend(c);
  while (cards.children.length > 4) cards.lastElementChild!.remove();
  return c;
}

/** Settings → Memory with "What Monkey knows about you" open. */
async function openMemory() {
  settingsOpenDetails.add("memoryInspector");
  await openSettings("memory");
  const box = document.querySelector<HTMLDetailsElement>("#memoryInspector");
  if (box && !box.open) box.open = true;
  setTimeout(() => jumpTo($<HTMLDialogElement>("#settings"), "memory", false), 200);
}

/** Fold every card to its title bar (unsent drafts stay open) so the conversation is readable. */
function foldCards() {
  cards.querySelectorAll<HTMLElement>(".card").forEach((c) => {
    if (!(c.classList.contains("draft") && !c.classList.contains("sent"))) c.classList.add("folded");
  });
}

function draftCard(d: any) {
  document.querySelectorAll(`.draft[data-id="${d.draft_id}"]`).forEach((n) => n.remove());
  const subj = h("input", { value: d.subject });
  const body = h("textarea", {}, d.body);
  const status = h("span", { class: "badge" }, d.account === "outlook" ? "wisc.edu Outlook" : "Gmail");
  const c = card("✉️ Draft: check it, then Send",
    h("div", {}, status, " ", h("span", { class: "meta" }, "Not sent yet. Edit anything, then click Send.")),
    h("label", {}, "To"), h("input", { value: [...d.to, ...(d.cc?.length ? ["cc: " + d.cc.join(", ")] : [])].join(", "), readOnly: true }),
    h("label", {}, "Subject"), subj,
    h("label", {}, "Message"), body,
  );
  c.classList.add("draft");
  c.dataset.id = d.draft_id;
  const send = h("button", { class: "send", type: "button", title: "Send this email now" }, "Send email");
  send.addEventListener("click", async () => {
    send.disabled = true;
    if (subj.value !== d.subject || body.value !== d.body) {
      const r = await api.edit_draft(d.draft_id, d.token, subj.value, body.value);
      if (!r.ok) { toast(r.error ?? "Couldn't save edits"); send.disabled = false; return; }
    }
    const r = await api.approve(d.draft_id, d.token);
    if (r.ok) {
      c.classList.add("sent");
      const when = new Date().toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
      c.querySelector("h3")!.textContent = `✅ Sent to ${d.to.join(", ")}`;
      const sub = c.querySelector(".meta");
      if (sub) sub.textContent = `Sent at ${when}. It's in your ${d.account === "outlook" ? "Outlook" : "Gmail"} Sent folder.`;
      subj.readOnly = true; (body as HTMLTextAreaElement).readOnly = true;
      c.querySelector(".actions")!.replaceChildren(h("strong", {}, `✓ Sent at ${when}`));
      addMsg("sys", `Email sent to ${d.to.join(", ")} at ${when}`);
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
  card("📅 Calendar", p.label ? h("p", { class: "help" }, h("strong", {}, p.label)) : "",
    p.events.length ? h("ul", { class: "items" }, ...p.events.map((e: any) => h("li", {},
      h("span", { class: "badge" }, ({ calendar: "your calendar", ics: "your calendar", google: "Google", canvas: "Canvas", outlook: "Outlook" } as Record<string, string>)[e.source] ?? e.source),
      h("div", {}, h("div", {}, e.title), h("div", { class: "meta" }, `${e.when ?? fmtTime(e.start)}${e.location ? " · " + e.location : ""}`)))))
      : h("p", { class: "help" }, "Nothing on your calendar then."));
}

function emailsCard(p: any) {
  if (!p.emails.length) return;
  // Click an email to have Monkey read it to you (testers expected rows to open).
  card("📥 Email", h("ul", { class: "items" }, ...p.emails.slice(0, 12).map((e: any) => h("li", {
      class: "clickable", title: "Click to have Monkey read it", role: "button", tabindex: "0",
      onclick: () => { api.send_text(`Read me the email "${e.subject}" from ${e.sender} (id ${e.id}, ${e.account}).`, null); } },
    h("span", { class: "badge" }, e.account === "gmail" ? "Gmail" : e.account === "outlook" ? "Outlook" : e.account),
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
    case "state":
      setState(p.state);
      if (p.state === "idle") botBubble = null;
      $("#convChip").hidden = !(p.conversation && p.state === "listening");
      break;
    case "level": avatar.setLevel(p.v); break;
    case "visemes": avatar.setVisemes(p); break;
    case "user": addMsg("user", p.text); botBubble = null; break;
    case "delta": {
      if (!botBubble) botBubble = addMsg("bot", "");
      botBubble.textContent += p.text; log.scrollTop = log.scrollHeight;
      // talk gestures: one per finished sentence at most (the avatar rate-limits)
      sentenceBuf += p.text;
      const m = sentenceBuf.match(/^(.*?[.!?])(\s|$)/s);
      if (m) { (avatar as any).gestureFor?.(m[1]); sentenceBuf = sentenceBuf.slice(m[0].length); }
      break;
    }
    case "done": botBubble = null; break;
    case "route":
      $("#routeChip").textContent = p.label;
      $("#routeChip").title = `${p.task ? p.task.replace(/_/g, " ") + ": " : ""}${p.reason}`; break;
    case "calibration": brainEvent(p); break;
    case "voicekit": voiceKitEvent(p); if (p.finished) void offlineVoiceRefresh?.(); break;
    case "google": googleEvent(p); break;
    case "health": healthEvent(p); break;
    case "open_settings": if (p.section === "memory") void openMemory(); else void openSettings(p.section); break;
    case "bench": benchEvent(p); break;
    case "offlinevoice": offlineVoiceEvent(p); break;
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
    case "emote":
      if (p.name === "sleep") (avatar as any).sleepNow?.();
      else avatar.emote(p.name);
      break;
    case "health": healthCard(p); break;
    case "cleanup": cleanupCard(p); break;
    case "update": {
      const el = document.getElementById("updStatus");
      if (el) el.textContent = updateText(p);
      if (p.status === "ready") updateToast(p);
      break;
    }
    case "sources":
      card("🔎 Sources", h("div", { class: "sources" }, ...p.sources.map((s: any) =>
        h("a", { href: s.url, onclick: (e: Event) => { e.preventDefault(); api.open_url(s.url); } }, s.title || s.url))));
      break;
    case "opened": addMsg("sys", `Opened ${p.url}`); break;
    case "memory": if (appState.settings.show_tech_details) addMsg("sys", `🧠 Memory ${p.command}: ${p.path ?? ""}`); break;
    case "memory_used": memoryUsed(p.items ?? []); break;
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
  toast(importance === "high" ? "Important is on for your next questions: Monkey thinks harder (a few cents at most). Switch back to Auto anytime."
    : importance === "low" ? "Quick is on for your next questions: fastest and cheapest." : "Auto: Monkey picks for each question.", 4500);
});
$("#composer").addEventListener("submit", (e) => {
  e.preventDefault();
  const input = $<HTMLInputElement>("#input");
  const text = input.value.trim();
  if (!text) return;
  if (!appState.keys.anthropic) {               // keep what they typed; take them to the one thing missing
    toast("⚠ Paste your Claude key first (Settings → Start here). Your question is still in the box.", 6500);
    void openSettings("start");
    return;
  }
  input.value = "";
  foldCards();
  api.send_text(text, importance === "normal" ? null : importance);
});
$("#mic").addEventListener("click", () => api.push_to_talk());
$("#convEnd").addEventListener("click", () => { $("#convChip").hidden = true; void api.end_conversation(); });
$("#newChat").addEventListener("click", () => {
  api.new_conversation(); log.replaceChildren();
  cards.querySelectorAll<HTMLElement>(".card").forEach((c) => { if (!(c.classList.contains("draft") && !c.classList.contains("sent"))) c.remove(); });
  addMsg("sys", "New conversation started. Monkey still remembers the earlier ones (Settings → Memory).");
});
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

/** Plain-English update status for Settings → Updates (also refreshed live by "update" events). */
function updateText(u: { status: string; available?: string; current?: string; detail?: string; progress?: number }) {
  switch (u.status) {
    case "checking": return "Checking GitHub for a new version…";
    case "downloading": return `Downloading ${u.available ?? "update"}… ${u.progress ? `${u.progress}%` : ""}`.trim();
    case "ready": return `Update ${u.available} downloaded. Click Restart & update.`;
    case "up_to_date": return `You're on the latest version (${u.current || appState.version})`;
    case "unavailable": return "Auto-update works after installing with Monkey-win-Setup.exe";
    case "error": return `Couldn't check: ${u.detail || "unknown error"}. Try again in a minute.`;
    default: return `Version ${u.current || appState.version}`;
  }
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
  ["anthropic", "Your Claude key", "Required: this is Monkey's brain."],
  ["fish", "Fish Audio key (optional)", "Monkey's real voice. fish.audio → API keys."],
  ["deepgram", "Deepgram (optional)", "Faster speech recognition. Leave empty to use free local Whisper."],
  ["youtube", "YouTube Data API (optional)", "For showing videos. Google Cloud → APIs → YouTube Data API v3 → API key."],
  ["brave", "Brave Search (optional)", "Better image search. Without it, images come from Wikimedia Commons."],
  ["openai", "OpenAI (optional)", "For generating images and new Monkey designs with GPT Image 2.6 (Avatar Lab)."],
  ["canvas_token", "Canvas API token (optional)", "Unlocks points, grades & missing status for ranking. UW–Madison: request one via the Learn@UW 'Student Request for Canvas Access Token' form (kb.wisc.edu/156712), then activate it in Canvas."],
];

const keyWarnings: Record<string, string> = {};   // keys saved but rejected by the service (shown in red until fixed)
let settingsOpenDetails = new Set<string>();

async function openSettings(section?: string) {
  appState = await api.get_state();
  applyChrome(appState);
  const s = appState.settings;
  const dlg = $<HTMLDialogElement>("#settings");
  // Re-rendering must not throw you back to the top (testers lost the Sign in button that way).
  const prevScroll = dlg.open ? dlg.querySelector<HTMLElement>(".body")?.scrollTop ?? 0 : 0;
  if (dlg.open) settingsOpenDetails = new Set([...dlg.querySelectorAll<HTMLDetailsElement>("details[id][open]")].map((d) => d.id));
  const status = (on: boolean) => h("span", { class: `dot ${on ? "on" : ""}` });
  const keyRow = ([name, label, help]: [string, string, string]) => {
    const hint = appState.key_hints?.[name];
    const inp = h("input", { type: "password", placeholder: appState.keys[name] ? `saved ••••${hint ?? ""}` : "paste key" });
    const warn = keyWarnings[name];
    const note = h("p", { class: warn ? "keynote bad" : "keynote" },
      warn ? `⚠ This key didn't work: ${warn}` :
      appState.keys[name] ? `✓ Saved and working${hint ? ` (ends in ${hint})` : ""}. Stays saved after restarts and updates.` : "");
    const save = async () => {
      if (!inp.value.trim()) return;
      if (name === "anthropic" && inp.value.trim().length < 60) {
        note.className = "keynote bad";
        note.textContent = "⚠ That looks shorter than a Claude key (they're about 100 characters and start with sk-ant-). Did you copy all of it?";
        inp.select();
        return;
      }
      const r = await api.save_key(name, inp.value.trim());
      if (!r.ok) { keyWarnings[name] = r.error ?? "it wasn't accepted"; note.className = "keynote bad"; note.textContent = `⚠ Not saved: ${r.error}`; inp.select(); return; }
      inp.value = "";
      if (r.warning) { keyWarnings[name] = r.warning; toast(`⚠ ${label}: ${r.warning}`, 9000); }
      else {
        delete keyWarnings[name];
        toast(r.note ? `✓ ${label} saved. ${r.note}` : `✓ ${label} saved and working.`, r.note ? 7000 : 4000);
      }
      await openSettings();
      if (name === "anthropic" && !r.warning) updateWelcome();
    };
    inp.addEventListener("keydown", (e) => { if ((e as KeyboardEvent).key === "Enter") { e.preventDefault(); save(); } });
    return h("div", { "data-key": name },
      h("div", { class: "field" }, h("span", { class: `dot ${warn ? "bad" : appState.keys[name] ? "on" : ""}` }), h("span", {}, label), inp,
        h("button", { class: "ghost", type: "button", onclick: save }, "Save"),
        appState.keys[name] && h("button", { class: "ghost", type: "button", title: "Remove this key", onclick: async () => {
          if (!confirm(`Remove the saved ${label} key?`)) return;
          await api.delete_key(name); toast(`${label} removed`); openSettings();
        } }, "✕")),
      note,
      h("p", { class: "help" }, help),
      name === "anthropic" && h("div", { class: "field", id: "workspaceRow" }, h("span", {}, "Claude workspace ID"),
        (() => {
          const ws = h("input", { value: appState.settings.anthropic_workspace_id ?? "", placeholder: "found automatically if your key needs one (wrkspc_…)" });
          ws.addEventListener("change", async () => { appState = await api.save_settings({ anthropic_workspace_id: ws.value.trim() }); toast("Saved"); });
          return ws;
        })(),
        h("button", { class: "ghost", type: "button", onclick: async () => {
          toast("Testing your Claude key…");
          const r = await api.test_anthropic();
          toast(r.ok ? `✓ Claude key works.${r.note ? " " + r.note : ""}` : `⚠ ${r.error}`, r.ok ? 5000 : 10000);
          if (r.ok) openSettings();
        } }, "Test")),
      name === "anthropic" && h("details", { class: "help maxhelp", id: "maxHelp" }, h("summary", {}, "Where do I get a Claude key? (and using Claude Max credits)"),
        "Make one at platform.claude.com (also called console.anthropic.com) → API keys; it starts with sk-ant-. Have Claude Max? It includes $100/month of API credits, so Monkey costs you nothing extra. claude.ai → Settings → Billing → ",
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
      applyLook(appState.settings);
      tick.textContent = "✓ saved";
      toast(`Saved: ${label}`);
    });
    const tick = h("span", { class: "meta" }, "");
    return h("div", { class: "field" }, h("span", {}, label), inp, tick);
  };
  const resultToast = (r: { ok: boolean; error?: string }, ok: string) => toast(r.ok ? ok : `⚠ ${r.error}`);
  const voiceOut = h("div", {});
  const instr = h("textarea", { rows: 3 },
    "An original adult male character voice, around 40, from New York City. Deep, smooth, slightly raspy baritone, calm laid-back confident delivery, subtle New York accent, warm and a little playful.");

  dlg.replaceChildren(h("div", { class: "settings" },
    h("header", {}, h("strong", {}, "Settings"), h("div", { class: "spacer" }),
      h("button", { class: "icon", onclick: () => dlg.close() }, "✕")),
    h("div", { class: "body" },
      healthSection(),
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
          h("button", { class: "ghost", type: "button", onclick: async () => {
            const r = await api.test_voice();
            toast(r.ok ? `✓ Using Monkey's Fish voice (${r.voice_id}, ${r.model === "s2.1-pro-free" ? "free model" : r.model})` : `⚠ ${r.error} Playing the Windows voice instead.`, r.ok ? 5000 : 10000);
            if (r.ok) openSettings();
          } }, "Test voice")),
        voiceOut,
        field("Fish voice ID", "fish_voice_id", "text", { placeholder: "reference_id from fish.audio" }),
        h("div", { class: "field" }, h("span", {}, "Fish model"), (() => {
          const sel = h("select", {},
            h("option", { value: "s2.1-pro-free" }, "S2.1 Pro Free ($0, Fish's free tier, announced through Nov 30, 2026)"),
            h("option", { value: "s2.1-pro" }, "S2.1 Pro (needs paid Fish API credits)"));
          sel.value = s.fish_model ?? "s2.1-pro-free";
          sel.addEventListener("change", async () => { appState = await api.save_settings({ fish_model: sel.value, fish_paid_confirmed: sel.value === "s2.1-pro" }); toast("Saved"); });
          return sel;
        })()),
        h("label", { class: "field toggle", id: "fishFreeShare" }, (() => {
          const cb = h("input", { type: "checkbox" }) as HTMLInputElement;
          cb.checked = s.fish_allow_free !== false;
          cb.addEventListener("change", async () => { appState = await api.save_settings({ fish_allow_free: cb.checked }); toast("Saved"); });
          return cb;
        })(), h("span", {}, "Use Fish's free model. Fish may use the text Monkey speaks to improve its models; turn off to use the offline voice only.")),
        h("p", { class: "help" }, "“Design voices” is a paid Fish API feature (a fish.audio subscription doesn't include API credits). Your current voice works on the free model.")),
      h("section", {}, h("h4", {}, "Wake word & mic"),
        h("p", { class: "help" }, `Active wake word: ${appState.wakeword}. Push-to-talk hotkey works anytime.`),
        field("Sensitivity (0.3–0.9)", "wakeword_threshold", "number", { step: "0.05", min: "0.3", max: "0.9" }),
        field("Push-to-talk hotkey", "push_to_talk_hotkey"),
        h("label", { class: "field toggle" }, (() => {
          const cb = h("input", { type: "checkbox" }) as HTMLInputElement;
          cb.checked = s.conversation_mode !== false;
          cb.addEventListener("change", async () => { appState = await api.save_settings({ conversation_mode: cb.checked }); toast(`Keep listening until the conversation is over: ${cb.checked ? "on" : "off"}`); });
          return cb;
        })(), h("span", {}, "Keep listening until the conversation is over (say “Hey Monkey” once, then just talk; say “thanks” or “that's all” to end)")),
        field("End a conversation after this many seconds of quiet", "conversation_idle_s", "number", { min: "15", max: "600", step: "5", placeholder: "90" }),
        h("div", { class: "field" }, h("span", {}, "Wait for me to finish"), (() => {
          const sel = h("select", {},
            h("option", { value: "quick" }, "Quick (0.9 s pause ends my turn)"),
            h("option", { value: "normal" }, "Normal (1.4 s)"),
            h("option", { value: "patient" }, "Patient (2 s, for long thoughts)"));
          sel.value = s.end_silence ?? "normal";
          sel.addEventListener("change", async () => { appState = await api.save_settings({ end_silence: sel.value }); toast("Saved"); });
          return sel;
        })()),
        h("div", { class: "field" }, h("span", {}, "Something not working?"),
          h("button", { class: "ghost", type: "button", onclick: async () => {
            const r = await api.open_log();
            toast(r.ok ? "Opened Monkey's log file (it shows what went wrong, for whoever helps you)" : `Log file: ${r.path}`, 6000);
          } }, "Open log")),
        h("div", { class: "field" }, h("span", {}, "Speech recognition"), (() => {
          const sel = h("select", {}, h("option", { value: "whisper" }, "Local Whisper (free, private)"),
            h("option", { value: "deepgram" }, "Deepgram Nova-3 (faster, needs key)"));
          sel.value = s.stt_engine;
          sel.addEventListener("change", async () => { appState = await api.save_settings({ stt_engine: sel.value }); toast("Saved"); });
          return sel;
        })())),
      h("section", {}, h("h4", {}, "Accounts"),
        h("p", { class: "help" }, "Connect what you use. Everything here is optional, and Monkey only reads; it never sends anything without you clicking Send."),
        h("h5", {}, "📅 Your class schedule"),
        (() => {
          const ta = h("textarea", { rows: 2, placeholder: appState.connections.calendar_ics ? "Calendar link saved (paste to replace)" : "https://calendar.google.com/calendar/ical/…/private-…/basic.ics" }) as HTMLTextAreaElement;
          return h("div", {},
            h("div", { class: "field" }, status(!!appState.connections.calendar_ics), h("span", {}, "Calendar link (easiest, no sign-in)"), ta,
              h("button", { class: "ghost", type: "button", onclick: async () => {
                if (!ta.value.trim()) return;
                const r = await api.save_key("calendar_ics", ta.value.trim());
                toast(r.ok ? (r.warning ? `⚠ ${r.warning}` : `✓ ${r.note ?? "Saved"}`) : `⚠ ${r.error}`);
                if (r.ok) openSettings();
              } }, "Save")),
            h("p", { class: "help" }, "Google Calendar (on the web) → ⚙ Settings → click your calendar on the left → Integrate calendar → copy “Secret address in iCal format”. Keep it private."));
        })(),
        h("h5", {}, "🎒 Canvas (what's due)"),
        (() => {
          const inp = h("input", { type: "url", value: s.canvas_ics_url ?? "", placeholder: "https://canvas.wisc.edu/feeds/calendars/user_….ics" }) as HTMLInputElement;
          const note = h("p", { class: "keynote" }, s.canvas_ics_url ? "✓ Saved. Click ✓ Homework at the top to see what's due." : "");
          const save = async () => {
            const v = inp.value.trim();
            if (v && !/^(https|webcal):\/\//i.test(v)) { note.className = "keynote bad"; note.textContent = "⚠ That doesn't look like the Canvas link. It starts with https:// and ends in .ics."; return; }
            appState = await api.save_settings({ canvas_ics_url: v });
            note.className = "keynote";
            note.textContent = v ? "✓ Saved. Click ✓ Homework at the top to see what's due." : "Removed.";
            toast(v ? "✓ Canvas connected" : "Canvas link removed");
            openSettings();
          };
          inp.addEventListener("keydown", (e) => { if ((e as KeyboardEvent).key === "Enter") { e.preventDefault(); void save(); } });
          return h("div", {},
            h("div", { class: "field" }, status(!!s.canvas_ics_url), h("span", {}, "Canvas calendar link"), inp,
              h("button", { class: "ghost", type: "button", onclick: save }, "Save")),
            note,
            h("p", { class: "help" }, "In Canvas: Calendar (left menu) → “Calendar Feed” (bottom right) → copy the link."));
        })(),
        h("h5", {}, "✉️ Gmail + Google Calendar"),
        (() => {
          const hasClient = !!appState.keys.google_client, connected = !!appState.connections.gmail;
          const st = h("span", { class: "meta", id: "googleStatus" }, connected ? "✓ Connected" : "");
          const pick = h("button", { class: hasClient ? "ghost" : "primary", type: "button", onclick: async () => {
            const r = await api.google_client_file();
            if (!r.ok) { if (r.error && !/nothing picked/i.test(r.error)) toast(`⚠ ${r.error}`); return; }
            toast("✓ Google setup file loaded. Now click Sign in with Google.");
            await openSettings();
            document.getElementById("googleSignIn")?.focus();
          } }, hasClient ? "Change setup file…" : "Choose file…");
          const signIn = h("button", { class: hasClient && !connected ? "primary" : "ghost", type: "button", id: "googleSignIn", disabled: !hasClient, onclick: async () => {
            const r = await api.google_sign_in();
            if (!r.ok) { st.textContent = `⚠ ${r.error}`; toast(`⚠ ${r.error}`); return; }
            st.textContent = "Opening Google sign-in in your browser…";
          } }, connected ? "Sign in again" : "Sign in with Google");
          return h("div", {},
            h("p", { class: "help" }, connected ? `✓ Connected${appState.settings.google_account ? ` as ${appState.settings.google_account}` : ""}. Monkey can read your Gmail and Google Calendar.` :
              "Needs a one-time Google setup (about 5 minutes, steps below). Only want your schedule? The calendar link above is enough."),
            !connected && h("div", { class: "field" }, status(hasClient), h("span", {}, "Step 1: your Google setup file"), pick,
              h("span", { class: "meta" }, hasClient ? "✓ Loaded" : "the client_secret_….apps.googleusercontent.com.json in your Downloads")),
            h("div", { class: "field" }, status(connected), h("span", {}, connected ? "Google account" : "Step 2: sign in"), signIn,
              connected && h("button", { class: "ghost", type: "button", onclick: async () => { await api.google_sign_out(); openSettings(); } }, "Sign out")),
            h("div", { class: "field" }, h("span", {}, ""), st),
            !connected && googleSetupGuide());
        })(),
        h("h5", {}, "🏫 School email (wisc.edu)"),
        h("div", { class: "field" }, status(!!appState.connections.outlook), h("span", {}, "wisc.edu Outlook"),
          h("button", { class: "ghost", type: "button", onclick: async () => {
            const r = await api.test_outlook(); resultToast(r, "Outlook connected"); openSettings();
          } }, appState.connections.outlook ? "Test connection" : "Connect"),
          appState.connections.outlook && h("button", { class: "ghost", type: "button", onclick: async () => {
            await api.disconnect_outlook(); toast("Outlook disconnected: Monkey won't open it"); openSettings();
          } }, "Disconnect")),
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
        h("div", { class: "field" }, h("span", {}, "Routing benchmark"),
          h("button", { class: "ghost", type: "button", onclick: async () => {
            const r = await api.routing_benchmark();
            const out = document.getElementById("benchOut");
            if (!r.ok) { toast(`⚠ ${r.error}`); return; }
            if (out) out.textContent = "Running (~14 quick Haiku calls, under $0.01)…";
          } }, "Run routing benchmark"),
          h("span", { class: "meta", id: "benchOut" }, "")),
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
      h("section", {}, h("h4", {}, "Look & feel"),
        h("p", { class: "help" }, "How much Monkey animates and makes noise. Auto follows Windows' “Animation effects” setting. " +
          "Calm keeps the fun but quieter and with fewer effects; Minimal turns off idle antics and sound effects."),
        h("div", { class: "field" }, h("span", {}, "Juice level"), (() => {
          const sel = h("select", {},
            h("option", { value: "auto" }, "Auto (follow Windows)"),
            h("option", { value: "full" }, "Full: all animations, effects & sounds"),
            h("option", { value: "calm" }, "Calm: fewer effects, quieter"),
            h("option", { value: "minimal" }, "Minimal: no idle antics or sound effects"));
          sel.value = s.juice_level ?? "auto";
          sel.addEventListener("change", async () => { appState = await api.save_settings({ juice_level: sel.value }); applyLook(appState.settings); toast("Saved"); });
          return sel;
        })()),
        h("div", { class: "field", id: "voiceVolume" }, h("span", {}, "Monkey's voice volume"), (() => {
          const r = h("input", { type: "range", min: "25", max: "200", step: "5", value: String(s.voice_volume ?? 100),
            title: "100% = as loud as YouTube and music at the same Windows volume" }) as HTMLInputElement;
          const pct = h("span", { class: "meta" }, `${r.value}%`);
          r.addEventListener("input", () => { pct.textContent = `${r.value}%`; });
          r.addEventListener("change", async () => { appState = await api.save_settings({ voice_volume: Number(r.value) }); toast(`Saved: Monkey's voice at ${r.value}%`); });
          return h("span", { class: "rangewrap" }, r, pct);
        })()),
        h("div", { class: "field", id: "voiceLoudness" }, h("label", {}, (() => {
          const c = h("input", { type: "checkbox" }) as HTMLInputElement;
          c.checked = s.voice_match_loudness ?? true;
          c.addEventListener("change", async () => { appState = await api.save_settings({ voice_match_loudness: c.checked }); toast("Saved"); });
          return c;
        })(), " Match the loudness of videos and music")),
        h("div", { class: "field" }, h("span", {}, "Sound effects volume"), (() => {
          const r = h("input", { type: "range", min: "0", max: "100", step: "5", value: String(s.sfx_volume ?? 70) }) as HTMLInputElement;
          r.addEventListener("change", async () => { appState = await api.save_settings({ sfx_volume: Number(r.value) }); applyLook(appState.settings); });
          return r;
        })()),
        field("Doze off after (minutes idle)", "sleep_after_min", "number", { min: "1", max: "120", step: "1" })),
      soundSection(s),
      h("section", {}, h("h4", {}, "Images & updates"),
        h("div", { class: "field", id: "imageModelRow" }, h("span", {}, "Image model"), (() => {
          const sel = h("select", {},
            h("option", { value: "gpt-image-2.6-sunburst" }, "GPT Image 2.6 Sunburst (best detail)"),
            h("option", { value: "gpt-image-2.6-flare" }, "GPT Image 2.6 Flare (faster drafts)"));
          sel.value = s.image_model ?? "gpt-image-2.6-sunburst";
          sel.addEventListener("change", async () => { appState = await api.save_settings({ image_model: sel.value }); toast("Saved"); });
          return sel;
        })()),
        (() => {
          const out = h("span", { class: "meta", id: "updStatus" }, "");
          api.update_state().then((u) => { out.textContent = updateText(u); });
          const auto = h("input", { type: "checkbox", checked: s.auto_update !== false });
          auto.addEventListener("change", async () => { appState = await api.save_settings({ auto_update: auto.checked }); toast("Saved"); });
          return h("div", {},
            h("div", { class: "field" }, h("span", {}, "Updates"), out,
              h("button", { class: "ghost", type: "button", onclick: async () => {
                out.textContent = updateText({ status: "checking" });
                const u = await api.check_update();      // returns at once; live progress comes as events
                out.textContent = updateText(u);
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
      briefSettings(s),
      h("section", {}, h("h4", {}, "Memory"),
        h("p", { class: "help" }, "Everything Monkey remembers about you stays on this PC. You can see it, fix it or delete it here."),
        memoryInspector(),
        contextImport(),
        moveToNewPc(),
        historyControls(s),
        h("details", {}, h("summary", {}, "Memory files on disk"),
          h("p", { class: "help" }, `Files: ${appState.memory_files.join(", ")}. Plain text you can edit.`),
          field("Sync folder (optional, e.g. OneDrive)", "memory_dir_override", "text", { placeholder: "C:\\Users\\you\\OneDrive\\Monkey" }),
          h("div", { class: "field" }, h("span", {}, ""),
            h("button", { class: "ghost", type: "button", onclick: () => api.open_memory_folder() }, "Open memory folder")))),
      h("p", { class: "help" }, `Monkey ${appState.version}`),
    )));
  organizeSettings(dlg);
  const quietUntil = Date.now() + 600;   // details re-opened by this render must not drag the view away from the target
  dlg.querySelectorAll<HTMLDetailsElement>(".body details").forEach((d) => d.addEventListener("toggle", () => {
    if (d.open && d.id !== "set-advanced" && Date.now() > quietUntil) setTimeout(() => d.scrollIntoView({ behavior: "smooth", block: "nearest" }), 30);
  }));
  for (const id of settingsOpenDetails) dlg.querySelector<HTMLDetailsElement>(`details#${id}`)?.setAttribute("open", "");
  if (!dlg.open) dlg.showModal();
  const body = dlg.querySelector<HTMLElement>(".body")!;
  if (section) { jumpTo(dlg, section); setTimeout(() => jumpTo(dlg, section, false), 120); }   // again after layout settles
  else body.scrollTop = prevScroll;
}

/** Settings layout: the everyday things first, developer things folded away under Advanced, and a menu to jump around. */
const SETTINGS_SECTIONS: [string, string][] = [["start", "Start"], ["accounts", "Accounts"], ["sound", "Voice & sound"],
  ["brief", "Morning brief"], ["memory", "Memory"], ["feel", "Look & mic"], ["advanced", "Advanced"]];
function organizeSettings(dlg: HTMLDialogElement) {
  const body = dlg.querySelector<HTMLElement>(".body")!;
  const sec = (title: string) => [...body.querySelectorAll<HTMLElement>(":scope > section")]
    .find((x) => x.querySelector(":scope > h4")?.textContent?.trim() === title);
  const move = (el: Element | null | undefined, to: Element | null | undefined, first = false) => {
    if (el && to) { if (first) to.querySelector(":scope > h4")?.after(el); else to.append(el); }
  };
  const health = sec("Is everything working?"), you = sec("You"), keysSec = sec("API keys"), fishSec = sec("Monkey's voice (Fish Audio)");
  const mic = sec("Wake word & mic"), accounts = sec("Accounts"), garmin = sec("Garmin"), brain = sec("Brain & budget");
  const look = sec("Look & feel"), sound = sec("Sound"), images = sec("Images & updates"), brief = sec("Morning brief"), memory = sec("Memory");
  // Start: name + the two keys that matter (Claude required, Fish optional)
  if (health) health.id = "set-check";
  if (you) {
    you.id = "set-start"; you.querySelector("h4")!.textContent = "Start here";
    move(keysSec?.querySelector('[data-key="anthropic"]'), you);
    move(keysSec?.querySelector('[data-key="fish"]'), you);
    you.append(h("p", { class: "help" }, "Only the Claude key is required. The Fish Audio key gives Monkey his real voice; without it he uses a free backup voice."));
  }
  if (accounts) { accounts.id = "set-accounts"; move(keysSec?.querySelector('[data-key="canvas_token"]'), accounts); }
  if (sound) {
    sound.id = "set-sound"; sound.querySelector("h4")!.textContent = "Voice & sound";
    move(look?.querySelector("#voiceLoudness"), sound, true);
    move(look?.querySelector("#voiceVolume"), sound, true);
    move(fishSec?.querySelector("#fishFreeShare"), sound);
  }
  if (brief) brief.id = "set-brief";
  if (memory) memory.id = "set-memory";
  if (look) { look.id = "set-feel"; look.querySelector("h4")!.textContent = "Look & mic"; }
  if (mic && look) { for (const el of [...mic.children].slice(1)) look.append(el); mic.remove(); }
  // Updates stay visible (in Look & mic); the image model goes to Advanced
  const imgModel = images?.querySelector("#imageModelRow");
  if (images && look) { for (const el of [...images.children].slice(1)) if (el !== imgModel) look.append(el); }
  // Advanced: optional keys, Fish voice design, Garmin, brain/budget/benchmark, image model, tech details
  const adv = h("details", { id: "set-advanced", class: "advanced" }, h("summary", {}, "⚙️ Advanced (optional keys, voice design, Garmin, AI models & budget, developer tools)")) as HTMLDetailsElement;
  for (const x of [brain, garmin, fishSec]) if (x) adv.append(x);
  if (keysSec) { keysSec.querySelector("h4")!.textContent = "Optional keys"; adv.append(keysSec); }
  const ws = you?.querySelector("#workspaceRow");
  if (ws && keysSec) keysSec.append(ws);
  if (imgModel) adv.append(h("section", {}, h("h4", {}, "Images"), imgModel));
  if (images) images.remove();
  adv.append(h("section", {}, h("h4", {}, "Developer"), (() => {
    const cb = h("input", { type: "checkbox" }) as HTMLInputElement;
    cb.checked = !!appState.settings.show_tech_details;
    cb.addEventListener("change", async () => { appState = await api.save_settings({ show_tech_details: cb.checked }); applyChrome(appState); toast("Saved"); });
    return h("label", { class: "field toggle" }, cb, h("span", {}, "Show technical details (AI model per answer, memory file names, Avatar Lab)"));
  })()));
  // Order
  const order = [health, you, accounts, sound, brief, memory, look].filter(Boolean) as HTMLElement[];
  const tail = [...body.children].filter((x) => !order.includes(x as HTMLElement) && x !== adv);
  body.replaceChildren(...order, adv, ...tail.filter((x) => x.tagName !== "SECTION"));
  const nav = h("nav", { class: "settingsnav" }, ...SETTINGS_SECTIONS.map(([id, label]) =>
    h("button", { type: "button", class: "ghost mini", onclick: () => jumpTo(dlg, id) }, label)));
  dlg.querySelector(".settings > header")!.after(nav);
}

function jumpTo(dlg: HTMLDialogElement, id: string, flash = true) {
  const body = dlg.querySelector<HTMLElement>(".body")!;
  const target = id === "start" || id === "check" ? null : dlg.querySelector<HTMLElement>(`#set-${id}`);
  if (target instanceof HTMLDetailsElement) target.open = true;
  // Plain scrollTop math (no smooth scrolling) so nothing else can interrupt it.
  body.scrollTop = target ? target.getBoundingClientRect().top - body.getBoundingClientRect().top + body.scrollTop - 8 : 0;
  if (!flash) return;
  const box = target ?? dlg.querySelector<HTMLElement>(id === "check" ? "#set-check" : "#set-start");
  box?.classList.add("attention");
  setTimeout(() => box?.classList.remove("attention"), 1600);
}

// ------------------------------------------------------------------ Google sign-in + routing benchmark
/** Links open in your real browser (pywebview ignores target=_blank). */
function extLink(href: string, text: string) {
  return h("a", { href, onclick: (e: Event) => { e.preventDefault(); void api.open_url(href); } }, text);
}

function googleSetupGuide() {
  const a = (href: string, text: string) => extLink(href, text);
  return h("details", { id: "googleGuide" }, h("summary", {}, "How to get the Google setup file (one time, about 5 minutes)"),
    h("ol", { class: "help" },
      h("li", {}, "Open ", a("https://console.cloud.google.com/projectcreate", "Google Cloud → New project"), " (any name, e.g. Monkey)."),
      h("li", {}, "Enable the ", a("https://console.cloud.google.com/apis/library/gmail.googleapis.com", "Gmail API"), " and the ", a("https://console.cloud.google.com/apis/library/calendar-json.googleapis.com", "Google Calendar API"), "."),
      h("li", {}, a("https://console.cloud.google.com/apis/credentials/consent", "OAuth consent screen"), ": External → fill the app name and your email."),
      h("li", {}, a("https://console.cloud.google.com/auth/audience", "Audience"), " → Publish app → Confirm. Monkey is only for you, so Google doesn't need to review it, and this keeps you signed in (in Testing mode Google signs you out every 7 days). Prefer Testing? Add your Gmail under Test users instead, or Google shows “Access blocked”."),
      h("li", {}, a("https://console.cloud.google.com/apis/credentials", "Credentials"), " → Create credentials → OAuth client ID → Application type: Desktop app → Create → Download JSON."),
      h("li", {}, "Back here: Step 1 → Choose file… (the client_secret_….json you just downloaded), then Sign in with Google. On “Google hasn't verified this app”, click Advanced → Go to Monkey (it's your own app), then allow Gmail and Calendar.")),
    h("p", { class: "help" }, "Only need your class schedule? Skip all this and use the Calendar link above."));
}

function googleEvent(p: any) {
  const st = document.getElementById("googleStatus");
  if (p.stage === "opening") {
    if (st) st.replaceChildren(
      h("span", {}, "Finish signing in in your browser. ",
        h("button", { class: "ghost mini", type: "button", onclick: async () => { await api.google_sign_in_cancel(); } }, "Cancel")),
      h("details", { class: "help" }, h("summary", {}, "Browser didn't open, or Google showed an error?"),
        h("p", {}, "Nothing opened: ", extLink(p.url, "open the Google sign-in page"), " or ",
          h("button", { class: "ghost mini", type: "button", onclick: async () => {
            try { await navigator.clipboard.writeText(p.url); toast("Link copied: paste it into your browser"); }
            catch { toast("⚠ Couldn't copy; use the open link"); }
          } }, "copy the link"), "."),
        h("p", {}, "Google says “Access blocked … has not completed the Google verification process”? In ",
          extLink("https://console.cloud.google.com/auth/audience", "Google Cloud → Audience"),
          ", click Publish app (or add your Gmail under Test users), then Cancel here and sign in again.")));
  } else if (p.stage === "done") {
    toast(p.emails != null ? `✓ Google connected: found ${p.emails} recent emails and ${p.events} calendar events this week` : "✓ Google connected", 6000);
    void openSettings();
  } else if (p.stage === "cancelled") {
    if (st) st.textContent = "Sign-in cancelled. Click Sign in with Google to try again.";
  } else if (p.stage === "error") {
    if (st) st.textContent = `⚠ ${p.message}`;
    toast(`⚠ ${p.message}`);
  }
}

// ------------------------------------------------------------------ check everything
let lastHealthReport = "";
function healthSection() {
  const out = h("div", { id: "checkAllOut", class: "checkall" });
  const btn = h("button", { class: "primary", type: "button", id: "checkAllBtn", onclick: async () => {
    const r = await api.health_check();
    if (!r.ok) { toast(`⚠ ${r.error}`); return; }
    out.replaceChildren(h("p", { class: "help" }, "Checking every part of Monkey… (about 10–20 seconds)"));
  } }, "Check everything");
  return h("section", {}, h("h4", {}, "Is everything working?"),
    h("p", { class: "help" }, "Tests the microphone, wake word, voices, your keys, Google, calendars, Canvas, memory and the morning brief on this PC. Free; nothing is sent or changed. Copy the report to share it: it never includes keys, emails or links."),
    h("div", { class: "field" }, btn), out);
}

const FIX_SECTION: Record<string, string> = { Brain: "start", Voice: "sound", Listening: "feel", Google: "accounts",
  Calendar: "accounts", Canvas: "accounts", Outlook: "accounts", Garmin: "advanced", Memory: "memory",
  "Morning brief": "brief", Budget: "advanced", App: "feel" };
function healthEvent(p: any) {
  const out = document.getElementById("checkAllOut");
  if (!out) return;
  if (!p.ok) { out.replaceChildren(h("p", { class: "help" }, `⚠ ${p.error}`)); return; }
  lastHealthReport = p.report;
  const icon: Record<string, string> = { ok: "✓", warn: "⚠", fail: "✗", skip: "–" };
  const checks = p.checks as { area: string; name: string; status: string; detail: string; fix: string }[];
  const bad = checks.filter((c) => c.status === "fail").length, warn = checks.filter((c) => c.status === "warn").length;
  out.replaceChildren(
    h("p", {}, h("strong", {}, bad ? `${bad} problem${bad > 1 ? "s" : ""}` : "No problems"),
      warn ? `, ${warn} thing${warn > 1 ? "s" : ""} to look at` : "", ". ",
      h("button", { class: "ghost", type: "button", onclick: async () => {
        try { await navigator.clipboard.writeText(lastHealthReport); toast("Report copied: paste it anywhere (a text, Discord, or to Claude)"); }
        catch { toast("⚠ Couldn't copy"); }
      } }, "Copy report")),
    h("ul", { class: "healthlist" }, ...checks.map((c) => h("li", { class: `h-${c.status}` },
      h("span", { class: "hicon" }, icon[c.status] ?? "?"),
      h("span", {}, h("b", {}, `${c.area} · ${c.name}: `), c.detail,
        c.fix && (c.status === "fail" || c.status === "warn") ? h("span", { class: "hfix" }, ` → ${c.fix} `,
          FIX_SECTION[c.area] ? h("button", { class: "ghost mini", type: "button", onclick: () => {
            if (c.area === "Memory") void openMemory(); else void openSettings(FIX_SECTION[c.area]);
          } }, "Fix it") : "") : "")))),
    h("button", { class: "ghost mini", type: "button", onclick: async () => {
      try { await navigator.clipboard.writeText(lastHealthReport); toast("Report copied: paste it anywhere (a text, Discord, or to Claude)"); }
      catch { toast("⚠ Couldn't copy"); }
    } }, "Copy report"));
}

function benchEvent(p: any) {
  const out = document.getElementById("benchOut");
  if (!p.finished) { if (out) out.textContent = `Running… ${p.done}/${p.total}`; return; }
  if (!p.ok) { if (out) out.textContent = `⚠ ${p.error}`; toast(`⚠ ${p.error}`); return; }
  if (out) out.textContent = "✓ Done (results card on the right)";
  card("📊 Routing benchmark", h("p", {}, p.summary),
    p.misses?.length ? h("ul", { class: "items" }, ...p.misses.map((m: any) => h("li", {}, `“${m.text}” → ${m.task} (expected ${m.want.join(" / ")})`))) : "",
    h("p", { class: "help" }, `Saved to ${p.path ?? "bench_routing.json"}. Nothing about routing changes automatically.`));
}

// ------------------------------------------------------------------ morning brief
let briefDismissed = false;
async function showMorningBrief(refresh = false) {
  if (refresh && (briefDismissed || !cards.querySelector('.card[data-title^="☀️"]'))) return;   // closed stays closed
  const r = await api.brief_preview(!refresh, refresh).catch(() => null);
  if (!r?.ok || !r.brief) return;
  const folded = !!cards.querySelector('.card.folded[data-title^="☀️"]');
  cards.querySelectorAll<HTMLElement>(".card").forEach((c) => { if ((c.dataset.title ?? "").startsWith("☀️")) c.remove(); });
  briefCard(r.brief, folded);
}

function briefCard(b: Brief, wasFolded = false) {
  const title = b.kind === "draft" ? "☀️ Morning brief (preview)" : b.kind === "late" ? "☀️ Today (late start)" : "☀️ Morning brief";
  const others = [...cards.querySelectorAll<HTMLElement>(".card")].filter((c) => !c.classList.contains("folded"));
  const c = card(title,
    b.kind === "draft" ? h("p", { class: "help" }, "Tell Monkey when your first class is each day and he'll have this ready 90 minutes before. ",
      h("button", { class: "ghost mini", type: "button", onclick: () => void openSettings("brief") }, "Set my class times")) : "",
    h("p", {}, h("strong", {}, "Top priority: "), b.top),
    h("p", { class: "help" }, "Next: " + b.next_step),
    ...b.sections.map((s) => h("div", { class: `briefsec ${s.status}` },
      h("strong", {}, s.title),
      s.items.length ? h("ul", { class: "items" }, ...s.items.map((i) => h("li", {}, i))) : "",
      s.note ? h("span", { class: "meta" }, s.note) : "")));
  c.querySelector(".close")?.addEventListener("click", () => { briefDismissed = true; });
  if (wasFolded) {                                  // a refresh must not pop the brief open over the chat
    c.classList.add("folded");
    others.forEach((o) => o.classList.remove("folded"));
  }
}

const DAY_LABEL: Record<string, string> = { mon: "Mon", tue: "Tue", wed: "Wed", thu: "Thu", fri: "Fri" };
function briefSettings(s: Record<string, any>) {
  const status = h("p", { class: "help" }, "…");
  const grid = h("div", { class: "briefgrid" });
  const inputs: Record<string, HTMLInputElement> = {};
  for (const d of Object.keys(DAY_LABEL)) {
    const inp = h("input", { type: "time", value: s.brief_schedule?.by_day?.[d] ?? "" }) as HTMLInputElement;
    inputs[d] = inp;
    grid.append(h("label", {}, h("span", {}, DAY_LABEL[d]), inp));
  }
  const xmlOut = h("pre", { class: "briefxml" });
  const taskHint = h("p", { class: "help", id: "briefTaskHint" });
  const needSchedule = (msg: string) => {
    taskHint.textContent = `⚠ ${msg}`;
    grid.scrollIntoView({ behavior: "smooth", block: "center" });
    grid.classList.add("attention");
    setTimeout(() => grid.classList.remove("attention"), 2500);
    (grid.querySelector("input") as HTMLInputElement | null)?.focus();
  };
  const friendly = (iso: string | null) => {
    if (!iso) return "none this week";
    const d = new Date(iso), t = d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
    const days = Math.round((new Date(d.toDateString()).getTime() - new Date(new Date().toDateString()).getTime()) / 864e5);
    return days === 0 ? `today ${t}` : days === 1 ? `tomorrow ${t}` : `${d.toLocaleDateString([], { weekday: "short", month: "short", day: "numeric" })}, ${t}`;
  };
  const taskState = h("span", { class: "meta" }, "");
  const refresh = async () => {
    const st = await api.brief_status();
    status.textContent = (st.verified
      ? `✓ Set. Your next brief: ${friendly(st.next_run)} (${st.lead_min} min before your first class).`
      : "Not set yet: type the start time of your first class on each school day, then click Confirm schedule.")
      + (st.canvas.status === "none" ? "" : ` ${st.canvas.message}`);
    taskState.textContent = st.task ? `✓ On${st.verified ? `: ready at ${friendly(st.next_run)} even if Monkey is closed` : ""}` : "Off";
    taskToggle.textContent = st.task ? "Turn off" : "Turn on";
    taskToggle.className = st.task ? "ghost" : "primary";
    taskOn = !!st.task;
  };
  let taskOn = false;
  const taskToggle = h("button", { class: "primary", type: "button", onclick: async () => {
    if (taskOn) { await api.brief_task_disable(); taskHint.textContent = ""; toast("Turned off"); void refresh(); return; }
    const r = await api.brief_task_enable();
    if (!r.ok && r.needs_schedule) { needSchedule(r.error ?? ""); return; }
    taskHint.textContent = r.ok ? "" : `⚠ ${r.error}`;
    toast(r.ok ? "✓ On: the brief gets made even when Monkey is closed" : `⚠ ${r.error}`);
    void refresh();
  } }, "Turn on");
  void refresh();
  const detect = h("button", { class: "ghost", type: "button", onclick: async () => {
    const r = await api.brief_candidates();
    if (!r.ok) { taskHint.textContent = `⚠ ${r.error}`; return toast(`⚠ ${r.error}`); }
    const c = r.candidates ?? {};
    for (const [d, v] of Object.entries(c)) if (inputs[d]) inputs[d].value = v.time;
    taskHint.textContent = "";
    toast(Object.keys(c).length ? `Found ${Object.keys(c).length} day(s) from ${r.source || "your calendar"}. Check them, then click Confirm schedule.` : "Couldn't find your classes. Type the first class time for each day instead.");
  } }, "Fill in from my calendar or notes");
  const confirmBtn = h("button", { class: "primary", type: "button", onclick: async () => {
    const byDay: Record<string, string> = {};
    for (const [d, inp] of Object.entries(inputs)) if (inp.value) byDay[d] = inp.value;
    if (!Object.keys(byDay).length) { needSchedule("Type the start time of your first class on at least one day first (or click Detect from calendar)."); return; }
    const st = await api.brief_confirm(byDay, "confirmed in app");
    appState = await api.get_state();
    toast(st.verified ? "✓ Schedule saved" : "Schedule cleared");
    if (st.verified) taskHint.textContent = "";
    void refresh();
  } }, "Confirm schedule");
  const speak = h("input", { type: "checkbox", checked: !!s.brief_speak_on_open }) as HTMLInputElement;
  speak.addEventListener("change", async () => { appState = await api.save_settings({ brief_speak_on_open: speak.checked }); toast("Saved"); });
  const expires = h("input", { type: "date", value: s.canvas_token_expires ?? "" }) as HTMLInputElement;
  expires.addEventListener("change", async () => { appState = await api.save_settings({ canvas_token_expires: expires.value }); void refresh(); });
  return h("section", {}, h("h4", {}, "Morning brief"),
    h("p", { class: "help" }, "On school days Monkey prepares a brief 90 minutes before your earliest confirmed class (Chicago time, weekends off): today's classes, what's due in 72 hours ranked by grade impact, unread email, weather and the one thing to do first. It shows in the app; nothing is sent anywhere."),
    grid, h("div", { class: "field" }, detect, confirmBtn), status,
    h("label", { class: "field toggle" }, speak, h("span", {}, "Say a two-sentence version when I open Monkey")),
    appState.keys.canvas_token ? h("div", { class: "field" }, h("span", {}, "Canvas access token expires"), expires) : "",
    h("div", { class: "field" }, h("span", {}, "Also make it when Monkey is closed"), taskToggle, taskState),
    h("p", { class: "help" }, "Windows wakes your PC a little early to build it (silently, no notifications)."),
    taskHint,
    appState.settings.show_tech_details ? h("details", {}, h("summary", {}, "Technical details (Windows Task Scheduler)"),
      h("button", { class: "ghost", type: "button", onclick: async () => {
        const r = await api.brief_task_preview();
        if (!r.ok && r.needs_schedule) { xmlOut.textContent = ""; needSchedule(r.error ?? ""); return; }
        xmlOut.textContent = r.ok ? r.xml ?? "" : `⚠ ${r.error}`;
      } }, "Preview task"), xmlOut) : "");
}

// ------------------------------------------------------------------ memory: inspector, import, history
/** Which memories/episodes informed the current answer: a small chip under the reply, details on click. */
const FRIENDLY_SOURCE: Record<string, string> = {
  "profile.md": "about you", "classes.md": "your classes", "preferences.md": "your preferences", "projects.md": "your projects",
  "people.md": "people you know", "writing_style.md": "your writing style",
};
function memoryUsed(items: { kind: string; ref: string; date: string; source: string; status: string; text?: string }[]) {
  const tech = !!appState.settings.show_tech_details;
  // Internal notes (model policy, site shortcuts) aren't "memories" a person cares about.
  items = items.filter((i) => tech || i.kind !== "fact" || i.source in FRIENDLY_SOURCE);
  if (!items.length) return;
  // One chip per answer: merge with a chip that's already right above (recall + search both report memories).
  const prev = log.lastElementChild as HTMLElement | null;
  if (prev?.classList.contains("memchip")) {
    const seen = new Set<string>(JSON.parse(prev.dataset.refs ?? "[]"));
    items = [...JSON.parse(prev.dataset.items ?? "[]"), ...items.filter((i) => !seen.has(i.ref))];
    prev.remove();
  }
  const label = items.map((i) => i.text ? `“${i.text}”` :
    `${i.kind === "fact" ? (tech ? i.source : FRIENDLY_SOURCE[i.source]) : i.kind === "episode" ? "an earlier chat" : "this conversation"} · ${i.date}`);
  const chip = h("details", { class: "memchip" }, h("summary", {}, `🧠 used ${items.length} memor${items.length === 1 ? "y" : "ies"}`),
    h("ul", {}, ...label.map((t) => h("li", {}, t))),
    h("button", { class: "ghost mini", type: "button", onclick: () => void openMemory() }, "See or fix what Monkey knows")) as HTMLElement;
  chip.dataset.items = JSON.stringify(items);
  chip.dataset.refs = JSON.stringify(items.map((i) => i.ref));
  log.append(chip);
  log.scrollTop = log.scrollHeight;
}

function memoryInspector() {
  const FILE_LABEL: Record<string, string> = { "profile.md": "About you", "classes.md": "Classes", "preferences.md": "Preferences",
    "projects.md": "Projects", "people.md": "People", "writing_style.md": "Writing style" };
  const q = h("input", { type: "search", placeholder: "Filter" }) as HTMLInputElement;
  const out = h("div", { class: "memlist" });
  const row = (f: { id: string; file: string; text: string; date: string }) => {
    const r: HTMLElement = h("div", { class: "memhit" },
      h("span", {}, f.text),
      h("span", { class: "memrow-actions" },
        h("button", { class: "ghost mini", type: "button", title: "Correct this", onclick: () => {
          const inp = h("input", { value: f.text }) as HTMLInputElement;
          const save = async () => {
            const res = await api.memory_edit(f.id, inp.value);
            if (!res.ok) { toast(`⚠ ${res.error}`); return; }
            toast("Updated. (Monkey keeps the old version marked as outdated so he doesn't bring it back; it's never used as current.)", 6000);
            void load();
          };
          inp.addEventListener("keydown", (e) => { if ((e as KeyboardEvent).key === "Enter") void save(); });
          r.replaceChildren(inp, h("span", { class: "memrow-actions" },
            h("button", { class: "primary mini", type: "button", onclick: save }, "Save"),
            h("button", { class: "ghost mini", type: "button", onclick: () => void load() }, "Cancel")));
          inp.focus();
        } }, "Edit"),
        h("button", { class: "ghost mini", type: "button", title: "Delete this from Monkey's memory", onclick: async () => {
          const res = await api.memory_forget(f.id);
          toast(res.ok ? "Forgotten" : `⚠ ${res.error}`);
          if (res.ok) r.remove();
        } }, "Forget")));
    return r;
  };
  const load = async () => {
    const r = await api.memory_list();
    if (!r.ok) { out.replaceChildren(h("p", { class: "help" }, `⚠ ${r.error}`)); return; }
    const needle = q.value.trim().toLowerCase();
    const facts = (r.facts ?? []).filter((f) => !needle || f.text.toLowerCase().includes(needle));
    if (!facts.length) {
      out.replaceChildren(h("p", { class: "help" }, needle ? "Nothing matches." :
        "Monkey doesn't know anything about you yet. Tell him things in chat (\"remember my roommate is Sam\") or add your notes below."));
      return;
    }
    const groups = new Map<string, typeof facts>();
    for (const f of facts) groups.set(f.file, [...(groups.get(f.file) ?? []), f]);
    out.replaceChildren(h("p", { class: "help" }, `${facts.length} thing${facts.length === 1 ? "" : "s"} Monkey knows about you:`),
      ...[...groups.entries()].map(([file, fs]) => h("div", { class: "memgroup" },
        h("strong", {}, FILE_LABEL[file] ?? file.replace(/\.md$/, "")), ...fs.map(row))));
  };
  q.addEventListener("input", () => void load());
  const box = h("details", { id: "memoryInspector" }, h("summary", {}, "🧠 What Monkey knows about you (see, edit, forget)"),
    h("div", { class: "field" }, q), out) as HTMLDetailsElement;
  box.addEventListener("toggle", () => { if (box.open) void load(); });
  return box;
}

function contextImport() {
  const out = h("div", {});
  const preview = async () => {
    const r = await api.import_preview();
    if (!r.ok) { if (r.error && !/nothing picked|no file/i.test(r.error)) toast(`⚠ ${r.error}`); return; }
    const files = r.files ?? [];
    const lines = files.reduce((n, f) => n + f.add.length, 0);
    const apply = h("button", { class: "primary", type: "button", onclick: async () => {
      const a = await api.import_apply();
      if (!a.ok) return toast(`⚠ ${a.error}`);
      out.replaceChildren(h("p", { class: "keynote" }, `✓ Done: Monkey now knows ${lines} new thing${lines === 1 ? "" : "s"} about you. Your old notes were backed up.`),
        h("button", { class: "ghost", type: "button", onclick: async () => {
          const u = await api.import_undo();
          toast(u.ok ? "Import undone" : `⚠ ${u.error}`);
          if (u.ok) out.replaceChildren(h("p", { class: "help" }, "Import undone. Nothing from those files is in Monkey's memory now."));
        } }, "Undo import"));
      toast(`✓ Monkey learned ${lines} thing${lines === 1 ? "" : "s"} about you`);
      out.scrollIntoView({ behavior: "smooth", block: "nearest" });
    } }, `Add ${lines} thing${lines === 1 ? "" : "s"} to Monkey's memory`);
    const cancel = h("button", { class: "ghost", type: "button", onclick: () => out.replaceChildren() }, "Cancel");
    // The buttons sit ABOVE the list (testers never found an Apply button at the bottom of a scroll box).
    out.replaceChildren(
      h("p", { class: "help" }, `Here's what will be added from ${files.length} file${files.length === 1 ? "" : "s"}. Nothing is saved until you click the yellow button.`),
      h("div", { class: "field" }, apply, cancel),
      h("div", { class: "memresults" }, ...files.map((f) => h("div", { class: "memhit" },
        h("strong", {}, `${f.name}: ${f.action === "new" ? "new" : f.action === "merge" ? `${f.add.length} new line(s)` : "nothing new"}`),
        ...f.conflicts.map((c) => h("span", { class: "meta" }, `⚠ might clash with what Monkey already knows: “${c.existing}” vs “${c.incoming}” (both kept; fix it in “What Monkey knows”)`)),
        h("details", {}, h("summary", {}, "show lines"), h("pre", {}, f.add.join("\n").replace(/\s*<!--.*?-->/g, "")))))));
    out.scrollIntoView({ behavior: "smooth", block: "center" });
  };
  return h("details", { id: "addNotes" }, h("summary", {}, "📥 Add notes about you (from files)"),
    h("p", { class: "help" }, "Pick text or .md files about you (like profile.md, classes.md). You'll see what gets added first; your current notes are backed up and you can undo."),
    h("button", { class: "ghost", type: "button", onclick: preview }, "Choose files…"), out);
}

function historyControls(s: Record<string, any>) {
  const stats = h("span", { class: "meta" }, "…");
  api.history_stats().then((st) => {
    stats.textContent = st.enabled ? `${st.sessions ?? 0} conversation${st.sessions === 1 ? "" : "s"} saved${appState.settings.show_tech_details ? ` · ${st.episodes ?? 0} summaries · ${st.facts ?? 0} lines searchable${st.fts ? "" : " (basic search)"}` : ""}` : "History is off";
  });
  const enabled = h("input", { type: "checkbox", checked: s.history_enabled !== false }) as HTMLInputElement;
  enabled.addEventListener("change", async () => { appState = await api.save_settings({ history_enabled: enabled.checked }); toast("Saved (takes effect after restart)"); });
  return h("details", {}, h("summary", {}, "🗂 Conversation history & retention"),
    h("label", { class: "field toggle" }, enabled, h("span", {}, "Keep a searchable history of our conversations on this PC")),
    h("div", { class: "field" }, h("span", {}, "Keep for (days, 0 = forever)"), (() => {
      const inp = h("input", { type: "number", min: "0", max: "3650", value: String(s.history_retention_days ?? 365) }) as HTMLInputElement;
      inp.addEventListener("change", async () => { appState = await api.save_settings({ history_retention_days: Number(inp.value) }); toast("Saved"); });
      return inp;
    })()),
    h("div", { class: "field" }, stats,
      h("button", { class: "ghost", type: "button", onclick: async () => { const r = await api.history_export(); toast(r.ok ? `Exported to ${r.path}` : `⚠ ${r.error}`); } }, "Export"),
      h("button", { class: "ghost", type: "button", onclick: async () => {
        if (!confirm("Delete ALL saved conversations and summaries? Your memory files stay.")) return;
        const r = await api.history_delete("all", 0);
        toast(r.ok ? `Deleted ${r.deleted} conversations` : `⚠ ${r.error}`);
      } }, "Delete all history")));
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

// ------------------------------------------------------------------ move to a new PC
function moveToNewPc(): HTMLElement {
  const pw = h("input", { type: "password", placeholder: "Password for the file (8+ characters)", autocomplete: "new-password" }) as HTMLInputElement;
  const pw2 = h("input", { type: "password", placeholder: "Type it again (for Export)", autocomplete: "new-password" }) as HTMLInputElement;
  const withKeys = h("input", { type: "checkbox" }) as HTMLInputElement;
  withKeys.checked = true;
  const out = h("div", { class: "meta", id: "transferStatus" });
  const exportBtn = h("button", { class: "primary", type: "button", onclick: async () => {
    if (pw.value.length < 8) { toast("⚠ Use a password of at least 8 characters"); return; }
    if (pw.value !== pw2.value) { toast("⚠ The two passwords don't match. Type them again so you can open the file later."); return; }
    out.textContent = "Packing everything up…";
    const r = await api.export_memory(pw.value, withKeys.checked);
    if (!r.ok) { out.textContent = `⚠ ${r.error}`; toast(`⚠ ${r.error}`); return; }
    const size = (r.mb ?? 0) >= 1 ? `${r.mb} MB` : "under 1 MB";
    const KEYNAME: Record<string, string> = { anthropic: "Claude key", fish: "Fish voice key", google_token: "Google sign-in",
      google_client: "Google setup file", calendar_ics: "calendar link", canvas_token: "Canvas access token", openai: "OpenAI key",
      youtube: "YouTube key", brave: "Brave key", deepgram: "Deepgram key" };
    const which = (r.keys ?? []).map((k) => KEYNAME[k] ?? k).join(", ");
    out.replaceChildren(`Saved ${r.path} (${size}: your memory, chats, settings, voice${which ? `, plus ${which}` : ""}). Copy it to a USB drive or your personal Google Drive. `,
      h("button", { class: "ghost", type: "button", onclick: () => { void api.open_documents_folder(); toast("Opened your Documents folder"); } }, "Open folder"));
    toast("Transfer file ready");
  } }, "Export for new PC");
  const importBtn = h("button", { class: "ghost", type: "button", onclick: async () => {
    out.textContent = "Checking the file…";
    const r = await api.import_memory(pw.value);
    if (!r.ok) { out.textContent = `⚠ ${r.error}`; toast(`⚠ ${r.error}`); return; }
    out.replaceChildren(`Got ${r.files} files${r.keys?.length ? ` and ${r.keys.length} keys` : ""}${r.keys_failed?.length ? ` (couldn't save: ${r.keys_failed.join(", ")})` : ""}. Restart to finish moving in. `,
      h("button", { class: "primary", type: "button", onclick: async () => {
        const x = await api.restart_app(); if (!x.ok) toast(`⚠ ${x.error}`);
      } }, "Restart Monkey"));
  } }, "Import from old PC");
  return h("div", { id: "moveToNewPc" },
    h("p", {}, h("strong", {}, "Move to a new PC")),
    h("p", { class: "help" }, "One encrypted file with your memory, chats, settings, voice and (optionally) your API keys and sign-ins. "
      + "On the old PC: Export. On the new PC: install Monkey, Import the file with the same password, restart."),
    h("div", { class: "field" }, pw, pw2),
    h("div", { class: "field" }, h("label", { title: "Your Claude key, voice key, Google sign-in and calendar/Canvas links, so you don't have to set them up again. Locked with this password." },
      withKeys, " Include my keys and sign-ins (Claude key, Google sign-in, links), locked with this password")),
    h("div", { class: "field" }, exportBtn, importBtn),
    out);
}

function welcomeAfterMove(t: NonNullable<AppState["transfer"]>): void {
  addMsg("sys", `Moved in from your old PC${t.from_version ? ` (Monkey ${t.from_version})` : ""}: ${t.moved.join(", ")}`
    + `${t.keys.length ? ` + ${t.keys.length} keys` : ""}. Your previous files are saved in ${t.backup}. `
    + "One-time steps for this PC: turn the morning brief back on (Settings → Morning brief), download the offline voice "
    + "(Settings → Sound), and Connect Outlook if you want school mail.");
  void api.transfer_seen();
}

// ------------------------------------------------------------------ boot
(async () => {
  api = await waitForApi();
  (window as any).__monkeyBooted = true;
  appState = await api.get_state();
  applyLook(appState.settings);
  applyChrome(appState);
  attachSounds(appState.settings);
  setState("idle");
  $("#hint").textContent = `Say “${appState.wakeword.split(" (")[0]}” or press ${appState.settings.push_to_talk_hotkey}`;
  $("#spend").textContent = `$${appState.month_usd.toFixed(2)} this month`;
  await restoreTranscript();
  if (appState.transfer) welcomeAfterMove(appState.transfer);
  void showMorningBrief();
  if (!appState.keys.anthropic || !appState.settings.first_run_complete) {
    welcomeEl = addMsg("sys", "Welcome! Paste your Claude key in Settings → Start here to get going (that's the only thing you need).");
    openSettings("start");
  } else {
    addMsg("sys", "Monkey's ready.");
  }
  // Whatever you changed in Settings (accounts, schedule, Canvas) shows up on the brief card right away.
  $<HTMLDialogElement>("#settings").addEventListener("close", () => {
    void showMorningBrief(true);
    void api.get_state().then((st) => { appState = st; applyChrome(st); updateWelcome(); });
  });
})();

let welcomeEl: HTMLElement | null = null;
function updateWelcome() {
  if (!welcomeEl) return;
  if (!appState.keys.anthropic) {
    welcomeEl.textContent = "Welcome! Paste your Claude key in Settings → Start here to get going (that's the only thing you need).";
    return;
  }
  const c = appState.connections;
  const next = c.canvas ? "Try: \"what's due this week?\"" : c.calendar_ics || c.google_calendar ? "Try: \"what's on tomorrow?\""
    : "Next: add your Canvas or calendar link in Settings → Accounts, then ask \"what's due this week?\"";
  welcomeEl.textContent = `You're all set! ${next}` + (appState.keys.fish ? "" : " (Optional: a Fish Audio key in Settings → Start here gives Monkey his real voice.)");
}
