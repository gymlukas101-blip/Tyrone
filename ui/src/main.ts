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
  const make = h("button", { class: "primary", type: "button", onclick: async () => {
    const r = await api.make_voice_kit(4);
    status.textContent = r.ok ? "Starting…" : `⚠ ${r.error}`;
  } }, "🎙 Make Monkey's voice set");
  voiceKitHooks = { status, done: async () => { await a3?.sfx.reloadUser(); renderLab(); } };
  return h("section", {}, h("h4", {}, "Sound"),
    h("p", { class: "help" }, "Monkey's grunts, laughs, yawns and snorts are made in his own Fish voice with Fish's free model " +
      "(free until Nov 30, 2026) and saved on this PC, so they keep working after that. Takes about 3–5 minutes, once. " +
      "It also saves a clean sample of his voice for the offline voice."),
    h("div", { class: "field" }, h("span", {}, "Voice set"), make, status),
    offlineVoiceRow(s),
    h("details", {}, h("summary", {}, "Sound Lab: hear every sound (click a number; right-click to turn a take off)"), lab));
}
/** Settings → Sound → Offline voice: Pocket TTS clone of Monkey's voice, free forever, runs on this PC. */
function offlineVoiceRow(s: Record<string, any>) {
  const st = h("span", { class: "meta", id: "offlineVoiceStatus" }, "…");
  const refresh = async () => {
    const v = await api.offline_voice_state();
    st.textContent = v.downloading ? "Downloading…" : !v.installed ? "Not downloaded (~200 MB, once)"
      : v.own_voice ? "✓ Ready: Monkey's own voice" : "✓ Ready (generic voice until you make Monkey's voice set)";
    dl.textContent = v.installed ? "Re-download" : "⬇ Download";
  };
  const dl = h("button", { class: "ghost", type: "button", onclick: async () => {
    const r = await api.download_offline_voice();
    st.textContent = r.ok ? "Starting download…" : `⚠ ${r.error}`;
  } }, "⬇ Download");
  const test = h("button", { class: "ghost", type: "button", onclick: async () => {
    const r = await api.test_offline_voice();
    toast(r.ok ? (r.own_voice ? "🔊 Offline voice (Monkey's own)" : "🔊 Offline voice (generic: make the voice set to clone Monkey)") : `⚠ ${r.error}`);
  } }, "▶ Test");
  const mode = h("select", {},
    h("option", { value: "fallback" }, "Use it when Fish isn't available"),
    h("option", { value: "only" }, "Always use the offline voice (never Fish)"),
    h("option", { value: "off" }, "Off (Windows voice as backup)"));
  mode.value = s.offline_voice ?? "fallback";
  mode.addEventListener("change", async () => { appState = await api.save_settings({ offline_voice: mode.value }); toast("Saved"); });
  offlineVoiceRefresh = refresh;
  void refresh();
  return h("div", {},
    h("div", { class: "field" }, h("span", {}, "Offline voice"), dl, test, st),
    h("div", { class: "field" }, h("span", {}, ""), mode));
}
let offlineVoiceRefresh: (() => Promise<void>) | null = null;
function offlineVoiceEvent(p: any) {
  const st = document.getElementById("offlineVoiceStatus");
  if (p.finished) {
    toast(p.ok ? `✓ Offline voice downloaded (${p.mb} MB)` : `⚠ ${p.error}`);
    void offlineVoiceRefresh?.();
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
    case "memory": addMsg("sys", `🧠 Memory ${p.command}: ${p.path ?? ""}`); break;
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
$("#convEnd").addEventListener("click", () => { $("#convChip").hidden = true; void api.end_conversation(); });
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
      inp.value = "";
      if (r.warning) { toast(`Saved, but: ${r.warning}`, 9000); }
      else toast(r.note ? `✓ ${label} saved. ${r.note}` : `✓ ${label} saved. It'll be there next time you open Monkey.`, r.note ? 7000 : 4000);
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
      name === "anthropic" && h("div", { class: "field" }, h("span", {}, "Claude workspace ID"),
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
      applyLook(appState.settings);
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
        h("label", { class: "field toggle" }, (() => {
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
          cb.addEventListener("change", async () => { appState = await api.save_settings({ conversation_mode: cb.checked }); toast("Saved"); });
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
            if (!r.ok) toast(`Log file: ${r.path}`);
          } }, "Open log")),
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
        h("div", { class: "field" }, h("span", {}, ""),
          h("button", { class: "ghost", type: "button", onclick: async () => {
            const r = await api.google_client_file(); resultToast(r, "✓ Google client loaded. Now click Sign in."); if (r.ok) openSettings();
          } }, "Load JSON file…")),
        googleSetupGuide(),
        h("div", { class: "field" }, status(!!appState.connections.gmail), h("span", {}, "Gmail + Google Calendar"),
          h("button", { class: "primary", type: "button", onclick: async () => {
            const r = await api.google_sign_in();
            const st = document.getElementById("googleStatus");
            if (!r.ok) { if (st) st.textContent = `⚠ ${r.error}`; toast(`⚠ ${r.error}`); if (r.needs_client) (document.getElementById("googleGuide") as HTMLDetailsElement | null)?.setAttribute("open", ""); return; }
            if (st) st.textContent = "Opening Google sign-in in your browser…";
          } }, appState.connections.gmail ? "Reconnect" : "Sign in"),
          appState.connections.gmail && h("button", { class: "ghost", type: "button", onclick: async () => { await api.google_sign_out(); openSettings(); } }, "Sign out")),
        h("div", { class: "field" }, h("span", {}, ""), h("span", { class: "meta", id: "googleStatus" }, "")),
        h("div", { class: "field" }, status(!!appState.connections.outlook), h("span", {}, "wisc.edu Outlook"),
          h("button", { class: "ghost", type: "button", onclick: async () => {
            const r = await api.test_outlook(); resultToast(r, "Outlook connected"); openSettings();
          } }, "Test connection")),
        (() => {
          const ta = h("textarea", { rows: 2, placeholder: appState.connections.calendar_ics ? "Calendar link saved (paste to replace)" : "https://calendar.google.com/calendar/ical/…/private-…/basic.ics" }) as HTMLTextAreaElement;
          return h("div", {},
            h("div", { class: "field" }, status(!!appState.connections.calendar_ics), h("span", {}, "Calendar link (no sign-in)"), ta,
              h("button", { class: "ghost", type: "button", onclick: async () => {
                if (!ta.value.trim()) return;
                const r = await api.save_key("calendar_ics", ta.value.trim());
                toast(r.ok ? (r.warning ? `⚠ ${r.warning}` : `✓ ${r.note ?? "Saved"}`) : `⚠ ${r.error}`);
                if (r.ok) openSettings();
              } }, "Save")),
            h("p", { class: "help" }, "Easiest way to give Monkey your class schedule: Google Calendar (web) → ⚙ Settings → click your calendar on the left → Integrate calendar → copy “Secret address in iCal format” and paste it here. Read-only; one link per line for several calendars. Keep it private: anyone with the link can see that calendar."));
        })(),
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
        h("div", { class: "field" }, h("span", {}, "Sound effects volume"), (() => {
          const r = h("input", { type: "range", min: "0", max: "100", step: "5", value: String(s.sfx_volume ?? 70) }) as HTMLInputElement;
          r.addEventListener("change", async () => { appState = await api.save_settings({ sfx_volume: Number(r.value) }); applyLook(appState.settings); });
          return r;
        })()),
        field("Doze off after (minutes idle)", "sleep_after_min", "number", { min: "1", max: "120", step: "1" })),
      soundSection(s),
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
        h("p", { class: "help" }, `Files: ${appState.memory_files.join(", ")}. Plain markdown you can edit. Export to move Monkey to another PC (encrypted with your password).`),
        field("Sync folder (optional, e.g. OneDrive)", "memory_dir_override", "text", { placeholder: "C:\\Users\\you\\OneDrive\\Monkey" }),
        (() => {
          const pw = h("input", { type: "password", placeholder: "export/import password (8+ chars)" });
          return h("div", { class: "field" }, pw,
            h("button", { class: "ghost", type: "button", onclick: async () => resultToast(await api.export_memory(pw.value), "Exported") }, "Export"),
            h("button", { class: "ghost", type: "button", onclick: async () => resultToast(await api.import_memory(pw.value), "Imported — restart Monkey") }, "Import"),
            h("button", { class: "ghost", type: "button", onclick: () => api.open_memory_folder() }, "Open folder"));
        })(),
        memoryInspector(),
        contextImport(),
        historyControls(s)),
      h("p", { class: "help" }, `Monkey ${appState.version}`),
    )));
  if (!dlg.open) dlg.showModal();
}

// ------------------------------------------------------------------ Google sign-in + routing benchmark
/** Links open in your real browser (pywebview ignores target=_blank). */
function extLink(href: string, text: string) {
  return h("a", { href, onclick: (e: Event) => { e.preventDefault(); void api.open_url(href); } }, text);
}

function googleSetupGuide() {
  const a = (href: string, text: string) => extLink(href, text);
  return h("details", { id: "googleGuide" }, h("summary", {}, "Set up Google (one time, ~5 min): what the Sign in button needs"),
    h("ol", { class: "help" },
      h("li", {}, "Open ", a("https://console.cloud.google.com/projectcreate", "Google Cloud → New project"), " (any name, e.g. Monkey)."),
      h("li", {}, "Enable the ", a("https://console.cloud.google.com/apis/library/gmail.googleapis.com", "Gmail API"), " and the ", a("https://console.cloud.google.com/apis/library/calendar-json.googleapis.com", "Google Calendar API"), "."),
      h("li", {}, a("https://console.cloud.google.com/apis/credentials/consent", "OAuth consent screen"), ": External → fill the app name and your email → under Test users, add your own Google account."),
      h("li", {}, a("https://console.cloud.google.com/apis/credentials", "Credentials"), " → Create credentials → OAuth client ID → Application type: Desktop app → Create → Download JSON."),
      h("li", {}, "Back here: Load JSON file… (above), then Sign in. Your browser opens; pick your account; you may see “Google hasn't verified this app”: click Continue (it's your own app).")),
    h("p", { class: "help" }, "Only need your calendar for the morning brief? Skip all this and use the Calendar link below instead."));
}

function googleEvent(p: any) {
  const st = document.getElementById("googleStatus");
  if (p.stage === "opening") {
    if (st) st.replaceChildren("Finish signing in in your browser. Nothing opened? ",
      extLink(p.url, "Open Google sign-in"));
  } else if (p.stage === "done") {
    if (st) st.textContent = "✓ Google connected";
    toast("✓ Google connected");
    void api.get_state().then((s) => { appState = s; });
  } else if (p.stage === "error") {
    if (st) st.textContent = `⚠ ${p.message}`;
    toast(`⚠ ${p.message}`);
  }
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
async function showMorningBrief() {
  const r = await api.brief_preview(true).catch(() => null);
  if (!r?.ok || !r.brief) return;
  briefCard(r.brief);
}

function briefCard(b: Brief) {
  const title = b.kind === "draft" ? "☀️ Morning brief (preview)" : b.kind === "late" ? "☀️ Today (late start)" : "☀️ Morning brief";
  card(title,
    b.kind === "draft" ? h("p", { class: "help" }, "Confirm your class schedule in Settings → Morning brief to get it timed 90 minutes before your first class.") : "",
    h("p", {}, h("strong", {}, "Top priority: "), b.top),
    h("p", { class: "help" }, "Next: " + b.next_step),
    ...b.sections.map((s) => h("div", { class: `briefsec ${s.status}` },
      h("strong", {}, s.title),
      s.items.length ? h("ul", { class: "items" }, ...s.items.map((i) => h("li", {}, i))) : "",
      s.note ? h("span", { class: "meta" }, s.note) : "")));
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
  const refresh = async () => {
    const st = await api.brief_status();
    status.textContent = (st.verified
      ? `✓ Timed from your confirmed schedule: ${st.lead_min} min before your earliest class. Next: ${st.next_run ? new Date(st.next_run).toLocaleString() : "none this week"}.`
      : "Not timed yet: confirm your earliest class each weekday (Monkey won't guess from old notes or Canvas due dates).")
      + ` ${st.canvas.message}`;
  };
  void refresh();
  const detect = h("button", { class: "ghost", type: "button", onclick: async () => {
    const r = await api.brief_candidates();
    if (!r.ok) return toast(`⚠ ${r.error}`);
    const c = r.candidates ?? {};
    for (const [d, v] of Object.entries(c)) if (inputs[d]) inputs[d].value = v.time;
    toast(Object.keys(c).length ? `Found ${Object.keys(c).length} day(s) from your calendar. Check them, then Confirm.` : "No recurring classes found in the next 2 weeks.");
  } }, "Detect from calendar");
  const confirmBtn = h("button", { class: "primary", type: "button", onclick: async () => {
    const byDay: Record<string, string> = {};
    for (const [d, inp] of Object.entries(inputs)) if (inp.value) byDay[d] = inp.value;
    const st = await api.brief_confirm(byDay, "confirmed in app");
    appState = await api.get_state();
    toast(st.verified ? "Schedule confirmed" : "Schedule cleared");
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
    h("div", { class: "field" }, h("span", {}, "Canvas token expires"), expires),
    h("label", { class: "field toggle" }, h("input", { type: "checkbox", disabled: true }), h("span", { class: "meta" }, "Phone notifications: off (needs your approval before it can be turned on)")),
    h("details", {}, h("summary", {}, "Prepare it even when Monkey is closed (Windows Task Scheduler)"),
      h("p", { class: "help" }, "Creates a scheduled task that wakes the PC to build the brief (no sound, no notifications). Review it first; nothing is registered until you click Enable."),
      h("div", { class: "field" },
        h("button", { class: "ghost", type: "button", onclick: async () => {
          const r = await api.brief_task_preview();
          xmlOut.textContent = r.ok ? r.xml ?? "" : `⚠ ${r.error}`;
        } }, "Preview task"),
        h("button", { class: "ghost", type: "button", onclick: async () => {
          const r = await api.brief_task_enable();
          toast(r.ok ? "Scheduled task enabled" : `⚠ ${r.error}`);
        } }, "Enable"),
        h("button", { class: "ghost", type: "button", onclick: async () => { await api.brief_task_disable(); toast("Scheduled task removed"); } }, "Disable")),
      xmlOut));
}

// ------------------------------------------------------------------ memory: inspector, import, history
/** Which memories/episodes informed the current answer: a small chip under the reply, details on click. */
function memoryUsed(items: { kind: string; ref: string; date: string; source: string; status: string }[]) {
  if (!items.length) return;
  const label = items.map((i) => `${i.kind === "fact" ? i.source : i.kind === "episode" ? "earlier chat" : "conversation"} · ${i.date}`);
  const chip = h("details", { class: "memchip" }, h("summary", {}, `🧠 used ${items.length} memor${items.length === 1 ? "y" : "ies"}`),
    h("ul", {}, ...label.map((t) => h("li", {}, t))));
  log.append(chip);
  log.scrollTop = log.scrollHeight;
}

function memoryInspector() {
  const q = h("input", { type: "search", placeholder: "Search what Monkey remembers (facts + past conversations)" }) as HTMLInputElement;
  const hist = h("input", { type: "checkbox" }) as HTMLInputElement;
  const out = h("div", { class: "memresults" });
  const run = async () => {
    const r = await api.memory_search(q.value, "all", hist.checked);
    if (!r.ok) { out.replaceChildren(h("p", { class: "help" }, `⚠ ${r.error}`)); return; }
    const hits = r.hits ?? [];
    out.replaceChildren(...(hits.length ? hits.map((x) => h("div", { class: `memhit ${x.status}` },
      h("span", { class: "meta" }, `${x.kind === "fact" ? x.source : x.kind} · ${x.date}${x.status !== "current" ? " · " + x.status : ""}${x.sensitive ? " · sensitive" : ""}`),
      h("span", {}, x.text),
      x.kind === "fact" && x.status === "current" ? h("button", { class: "ghost", type: "button", title: "Delete this fact from memory", onclick: async (e: Event) => {
        const res = await api.memory_forget(x.ref);
        toast(res.ok ? "Forgotten" : `⚠ ${res.error}`);
        if (res.ok) (e.target as HTMLElement).closest(".memhit")?.remove();
      } }, "Forget") : "")) : [h("p", { class: "help" }, "Nothing found.")]));
  };
  q.addEventListener("keydown", (e) => { if ((e as KeyboardEvent).key === "Enter") void run(); });
  return h("details", {}, h("summary", {}, "🔎 Memory inspector: see, search and correct what Monkey knows"),
    h("div", { class: "field" }, q, h("button", { class: "ghost", type: "button", onclick: run }, "Search")),
    h("label", { class: "field toggle" }, hist, h("span", {}, "Include older (superseded) versions")), out);
}

function contextImport() {
  const out = h("div", { class: "memresults" });
  const preview = async () => {
    const r = await api.import_preview();
    if (!r.ok) { toast(`⚠ ${r.error}`); return; }
    const files = r.files ?? [];
    const apply = h("button", { class: "primary", type: "button", onclick: async () => {
      const a = await api.import_apply();
      if (!a.ok) return toast(`⚠ ${a.error}`);
      out.replaceChildren(h("p", { class: "help" }, `✓ Imported. Backup of your previous files: ${a.backup}`),
        h("button", { class: "ghost", type: "button", onclick: async () => {
          const u = await api.import_undo();
          toast(u.ok ? `Undone (${(u.restored ?? []).join(", ")})` : `⚠ ${u.error}`);
        } }, "Undo import"));
    } }, "Apply import (backs up first)");
    out.replaceChildren(h("p", { class: "help" }, `Preview: ${r.label}. Nothing is written until you click Apply.`),
      ...files.map((f) => h("div", { class: "memhit" },
        h("strong", {}, `${f.name}: ${f.action === "new" ? "new file" : f.action === "merge" ? `add ${f.add.length} line(s)` : "no changes"}`),
        ...f.conflicts.map((c) => h("span", { class: "meta" }, `⚠ possible conflict: “${c.existing}” vs “${c.incoming}” (both kept; fix in the file)`)),
        h("details", {}, h("summary", {}, "lines"), h("pre", {}, f.add.join("\n").replace(/\s*<!--.*?-->/g, ""))))),
      apply);
  };
  return h("details", {}, h("summary", {}, "📥 Import context files (e.g. your ChatGPT profile pack)"),
    h("p", { class: "help" }, "Pick profile.md, preferences.md, projects.md, classes.md. You'll see exactly what changes; your current files are backed up first and you can undo."),
    h("button", { class: "ghost", type: "button", onclick: preview }, "Choose files and preview…"), out);
}

function historyControls(s: Record<string, any>) {
  const stats = h("span", { class: "meta" }, "…");
  api.history_stats().then((st) => {
    stats.textContent = st.enabled ? `${st.sessions ?? 0} conversations, ${st.episodes ?? 0} summaries, ${st.facts ?? 0} facts indexed${st.fts ? "" : " (basic search)"}` : "History is off";
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

// ------------------------------------------------------------------ boot
(async () => {
  api = await waitForApi();
  (window as any).__monkeyBooted = true;
  appState = await api.get_state();
  applyLook(appState.settings);
  attachSounds(appState.settings);
  setState("idle");
  $("#hint").textContent = `Say “${appState.wakeword.split(" (")[0]}” or press ${appState.settings.push_to_talk_hotkey}`;
  $("#spend").textContent = `$${appState.month_usd.toFixed(2)} this month`;
  await restoreTranscript();
  void showMorningBrief();
  if (!appState.keys.anthropic || !appState.settings.first_run_complete) {
    addMsg("sys", "Welcome! Add your Anthropic and Fish Audio keys in Settings to get started.");
    openSettings();
  } else {
    addMsg("sys", "Monkey's ready.");
  }
})();
