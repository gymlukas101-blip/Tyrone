// Talks to the Python side (pywebview js_api). Falls back to a demo mock in a normal browser.

export type Importance = "low" | "normal" | "high";

export interface AppState {
  settings: Record<string, any>;
  keys: Record<string, boolean>;
  key_hints?: Record<string, string>;
  secrets_backend?: string;
  wakeword: string;
  connections: Record<string, boolean>;
  month_usd: number;
  budget_usd: number;
  breakdown: { model: string; calls: number; usd: number }[];
  memory_files: string[];
  version: string;
}

export interface Api {
  get_state(): Promise<AppState>;
  save_key(name: string, value: string): Promise<{ ok: boolean; error?: string; hint?: string; warning?: string; note?: string }>;
  test_anthropic(): Promise<{ ok: boolean; error?: string; note?: string }>;
  delete_key(name: string): Promise<{ ok: boolean }>;
  get_transcript(limit: number): Promise<{ ts: string; role: "user" | "bot"; text: string }[]>;
  save_settings(changes: Record<string, any>): Promise<AppState>;
  send_text(text: string, importance: Importance | null): Promise<void>;
  push_to_talk(): Promise<void>;
  stop_speaking(): Promise<void>;
  approve(draftId: string, token: string): Promise<{ ok: boolean; error?: string }>;
  cancel_draft(draftId: string): Promise<void>;
  edit_draft(draftId: string, token: string, subject: string, body: string): Promise<{ ok: boolean; error?: string }>;
  open_draft(draftId: string): Promise<void>;
  open_url(url: string): Promise<void>;
  google_sign_in(): Promise<{ ok: boolean; error?: string }>;
  google_sign_out(): Promise<void>;
  test_outlook(): Promise<{ ok: boolean; error?: string }>;
  learn_style(): Promise<{ ok: boolean; error?: string; preview?: string }>;
  voice_design(instruction: string): Promise<{ ok: boolean; error?: string; candidates?: string[] }>;
  choose_voice(index: number): Promise<{ ok: boolean; error?: string; voice_id?: string }>;
  test_voice(): Promise<{ ok: boolean; error?: string; voice_id?: string; engine?: string; model?: string }>;
  export_memory(password: string): Promise<{ ok: boolean; error?: string; path?: string }>;
  import_memory(password: string): Promise<{ ok: boolean; error?: string; restored?: string[] }>;
  open_memory_folder(): Promise<void>;
  new_conversation(): Promise<void>;
  get_assignments(refresh: boolean): Promise<any>;
  toggle_assignment(id: string, done: boolean): Promise<{ ok: boolean; synced?: boolean; error?: string }>;
  get_health(day: string): Promise<{ ok: boolean; error?: string; health?: any }>;
  garmin_login(email: string, password: string): Promise<{ ok: boolean; status?: string; error?: string }>;
  garmin_mfa(code: string): Promise<{ ok: boolean; status?: string; error?: string }>;
  garmin_logout(): Promise<void>;
  list_prototypes(): Promise<{ favorite: string; notes: Record<string, string>; model: string; has_key: boolean }>;
  pick_prototype(id: string, notes: string): Promise<{ favorite: string; notes: Record<string, string>; model: string; has_key: boolean }>;
  save_prototype_note(id: string, notes: string): Promise<boolean>;
  generate_prototypes(direction: string, count: number, refHero: string): Promise<{ ok: boolean; error?: string; images?: { src: string; title: string }[] }>;
  check_update(): Promise<UpdateState>;
  apply_update(): Promise<UpdateState & { error?: string }>;
  update_state(): Promise<UpdateState>;
  cleanup_plan(): Promise<CleanupResult>;
  cleanup_run(): Promise<CleanupResult>;
  cleanup_dismiss(): Promise<void>;
  report_ui_error(info: string): Promise<void>;
  make_voice_kit(takes: number): Promise<{ ok: boolean; error?: string }>;
  end_conversation(): Promise<void>;
  open_log(): Promise<{ ok: boolean; path: string; error?: string }>;
  offline_voice_state(): Promise<{ installed: boolean; own_voice: boolean; mode: string; downloading: boolean }>;
  download_offline_voice(): Promise<{ ok: boolean; error?: string }>;
  test_offline_voice(): Promise<{ ok: boolean; error?: string; own_voice?: boolean }>;
  get_user_sounds(): Promise<Record<string, string[]>>;
  get_sound(rel: string): Promise<string>;
  get_policy(): Promise<Policy>;
  set_policy_entry(task: string, tier: string, model: string, effort: string): Promise<{ ok: boolean; error?: string }>;
  reset_policy(task: string): Promise<Policy>;
  calibrate_start(samples: number, tasks: string[]): Promise<{ ok: boolean; error?: string }>;
  calibration_estimate(tasks: string[], samples: number): Promise<{ usd: number }>;
  calibrate_cancel(): Promise<{ ok: boolean }>;
  calibration_results(): Promise<CalResults>;
  calibration_apply(picks: Record<string, string>): Promise<{ ok: boolean; error?: string; changed?: string[] }>;
}

export interface PolicyChoice { model: string; effort: string; label: string; usd: number; first_words_s: number; per_month_usd: number }
export interface PolicyRow {
  id: string; label: string; why: string; internal: boolean;
  measured?: { model: string; effort: string; usd: number; first_words_s: number; total_s: number; date: string } | null;
  min: PolicyChoice; default: PolicyChoice; max: PolicyChoice;
}
export interface Policy {
  rows: PolicyRow[]; totals: { min: number; default: number; max: number };
  models: { id: string; name: string }[]; efforts: string[];
  calibration_estimate: number; calibrating: boolean; has_results: boolean;
}
export interface CalOutput { kind: string; to?: string; subject?: string; text: string }
export interface CalRun { model: string; effort: string; label: string; usd: number; first_words_s: number; total_s: number; answer: string; error: string; outputs?: CalOutput[]; samples?: number }
export interface CalResults {
  ok: boolean; error?: string; date: string; complete: boolean; spent_usd: number; setup_error?: string; samples?: number; rerun?: string[];
  tasks: Record<string, { label: string; sample: string; runs: CalRun[] }>;
}

export interface CleanupItem { kind: string; label: string; path: string; status: string; detail: string }
export interface CleanupResult { ok: boolean; error?: string; items?: CleanupItem[]; count?: number }

export interface UpdateState { status: string; detail: string; current: string; available: string; enabled: boolean; progress?: number }

declare global {
  interface Window {
    pywebview?: { api: Api };
    __monkeyEvents?: (events: [string, any][]) => void;
  }
}

/** Demo mode only in a normal browser dev preview (vite on localhost:4173/5173 or ?demo). Inside the
 *  desktop app we always wait for the real Python bridge, however slow the first start is. */
const isDevPreview = () =>
  /^(localhost|127\.0\.0\.1)$/.test(location.hostname) && ["4173", "5173"].includes(location.port) ||
  new URLSearchParams(location.search).has("demo");

export function waitForApi(timeoutMs = 2500): Promise<Api> {
  return new Promise((resolve) => {
    const ready = () => !!window.pywebview?.api && typeof (window.pywebview.api as any).get_state === "function";
    if (ready()) return resolve(window.pywebview!.api);
    window.addEventListener("pywebviewready", () => resolve(window.pywebview!.api), { once: true });
    // Also poll: the ready event can fire before this listener is attached.
    const iv = setInterval(() => { if (ready()) { clearInterval(iv); resolve(window.pywebview!.api); } }, 200);
    if (isDevPreview()) {
      setTimeout(() => { if (!ready()) { clearInterval(iv); resolve(mockApi()); } }, timeoutMs);
    }
  });
}

// ------------------------------------------------------------------ demo mock
function mockApi(): Api {
  const emit = (events: [string, any][]) => window.__monkeyEvents?.(events);
  const later = (ms: number, fn: () => void) => setTimeout(fn, ms);
  const state: AppState = {
    settings: { user_name: "", monthly_budget_usd: 25, wakeword_threshold: 0.5, stt_engine: "whisper",
                canvas_ics_url: "", fish_voice_id: "", push_to_talk_hotkey: "ctrl+alt+space", first_run_complete: true },
    key_hints: { anthropic: "x9Qa", fish: "4s0I" }, secrets_backend: "Windows DPAPI",
    keys: { anthropic: true, fish: true, deepgram: false, youtube: false, brave: false, google_client: false, google_token: false },
    wakeword: "Demo mode (browser)",
    connections: { gmail: false, google_calendar: false, outlook: false, canvas: false },
    month_usd: 3.42, budget_usd: 25,
    breakdown: [{ model: "claude-opus-5-5", calls: 41, usd: 2.9 }, { model: "claude-haiku-5-5", calls: 212, usd: 0.11 }],
    memory_files: ["profile.md", "classes.md", "people.md", "preferences.md", "writing_style.md", "sites.md"],
    version: "demo",
  };
  const talk = (text: string) => {
    emit([["state", { state: "speaking" }]]);
    let i = 0;
    const words = text.split(" ");
    const iv = setInterval(() => {
      const vs = ["viseme_aa", "viseme_O", "viseme_E", "viseme_I", "viseme_U", "viseme_SS", "viseme_PP", "viseme_FF"];
      const pick = vs[Math.floor(Math.random() * vs.length)];
      emit([["delta", { text: (i ? " " : "") + words[i] }], ["level", { v: 0.3 + Math.random() * 0.6 }],
            ["visemes", { [pick]: 0.6 + Math.random() * 0.4 }]]);
      if (++i >= words.length) {
        clearInterval(iv);
        emit([["level", { v: 0 }], ["done", { text }], ["state", { state: "idle" }]]);
      }
    }, 140);
  };
  return {
    async get_state() { return state; },
    async save_key(name, value) {
      state.keys[name] = true; (state.key_hints ??= {})[name] = value.slice(-4); return { ok: true, hint: value.slice(-4) };
    },
    async test_anthropic() { return { ok: true, note: "Your key is organization-wide, so Monkey found your workspace and saved its ID." }; },
    async delete_key(name) { state.keys[name] = false; delete state.key_hints?.[name]; return { ok: true }; },
    async get_transcript() {
      return [
        { ts: new Date(Date.now() - 3600e3).toISOString(), role: "user", text: "what's due this week?" },
        { ts: new Date(Date.now() - 3590e3).toISOString(), role: "bot", text: "Math 222 problem set Thursday and the CS 400 project on Friday. Start with the project, it's worth more." },
      ];
    },
    async save_settings(c) { Object.assign(state.settings, c); return state; },
    async send_text(text) {
      emit([["user", { text }], ["route", { label: "Opus 5.5 · medium", reason: "email drafting", importance: "normal" }],
            ["state", { state: "thinking" }]]);
      if (/assign|due|work on|homework/i.test(text)) {
        later(800, () => {
          emit([["route", { label: "Sonnet 5.5 · low", reason: "assignments / health lookup", importance: "normal" }],
                ["assignments", demoBoard()]]);
          talk("Your Math 222 midterm tomorrow is twenty percent of your grade, and that CS 400 homework is missing. Hit those first.");
        });
        return;
      }
      if (/sleep|heart|garmin|hrv/i.test(text)) {
        later(800, () => {
          emit([["route", { label: "Sonnet 5.5 · low", reason: "assignments / health lookup", importance: "normal" }],
                ["health", demoHealth()]]);
          talk("Sleep score eighty one, seven hours fifteen. Resting heart rate fifty one. You're good, my guy.");
        });
        return;
      }
      if (/draft|email/i.test(text)) {
        later(900, () => {
          emit([["draft", { draft_id: "demo1", account: "outlook", to: ["prof.smith@wisc.edu"], cc: [],
            subject: "Missing lab Thursday", token: "t", status: "pending",
            body: "Hi Professor Smith,\n\nI wanted to give you a heads up that I'll miss lab this Thursday because of a medical appointment. I'll go over the lab materials beforehand and reach out to my lab partner for notes.\n\nThanks for understanding!" }]]);
          talk("Draft's on your screen. Say send it when you're ready, or tweak it first.");
        });
      } else if (/day|important|priorit/i.test(text)) {
        later(900, () => {
          emit([["ranking", { summary: "Your CS 400 midterm tomorrow is the big one.", items: [
            { tier: "critical", reason: "Exam in 20 hours", kind: "event", title: "COMP SCI 400 Midterm", start: new Date(Date.now() + 72e6).toISOString(), source: "canvas" },
            { tier: "high", reason: "Professor asked for a reply", kind: "email", subject: "Re: project groups", sender: "Prof. Smith", received: new Date().toISOString() },
            { tier: "normal", reason: "Club meeting", kind: "event", title: "Hoofers meeting", start: new Date(Date.now() + 2e8).toISOString(), source: "google" },
            { tier: "low", reason: "Promo", kind: "email", subject: "50% off hoodies", sender: "Bookstore", received: new Date().toISOString() },
          ] }]]);
          talk("Real talk, your CS 400 midterm tomorrow at nine is priority one. Put the rest on your screen.");
        });
      } else {
        later(700, () => talk("Yo, I'm in demo mode right now. Run me as the desktop app and I'm fully plugged in."));
      }
    },
    async push_to_talk() { emit([["state", { state: "listening", conversation: true }]]); later(4000, () => emit([["state", { state: "idle", conversation: false }]])); },
    async stop_speaking() {},
    async approve() { return { ok: true }; },
    async cancel_draft() {},
    async edit_draft() { return { ok: true }; },
    async open_draft() {},
    async open_url(url) { window.open(url, "_blank"); },
    async google_sign_in() { return { ok: false, error: "Demo mode" }; },
    async google_sign_out() {},
    async test_outlook() { return { ok: false, error: "Demo mode" }; },
    async learn_style() { return { ok: false, error: "Demo mode" }; },
    async voice_design() { return { ok: false, error: "Demo mode" }; },
    async choose_voice() { return { ok: false, error: "Demo mode" }; },
    async test_voice() { return { ok: true, voice_id: "4a396e7e91a640a2b1e0f06249cbcd14", engine: "fish" }; },
    async export_memory() { return { ok: false, error: "Demo mode" }; },
    async import_memory() { return { ok: false, error: "Demo mode" }; },
    async open_memory_folder() {},
    async new_conversation() {},
    async get_assignments() { return { ok: true, ...demoBoard() }; },
    async toggle_assignment() { return { ok: true, synced: true }; },
    async get_health() { return { ok: true, health: demoHealth() }; },
    async garmin_login() { return { ok: false, error: "Demo mode" }; },
    async garmin_mfa() { return { ok: false, error: "Demo mode" }; },
    async garmin_logout() {},
    async list_prototypes() { return { favorite: labFav, notes: {}, model: "gpt-image-2.6-sunburst", has_key: false }; },
    async pick_prototype(id) { labFav = id; return { favorite: id, notes: {}, model: "gpt-image-2.6-sunburst", has_key: false }; },
    async save_prototype_note() { return true; },
    async generate_prototypes() { return { ok: false, error: "Demo mode: add an OpenAI key in the desktop app" }; },
    async check_update() { return { status: "ready", detail: "", current: "0.3.40", available: "0.3.41", enabled: true }; },
    async apply_update() { return { status: "ready", detail: "", current: "0.3.40", available: "0.3.41", enabled: true, error: "Demo mode" }; },
    async cleanup_plan() { return { ok: true, count: demoCleanup().length, items: demoCleanup() }; },
    async cleanup_run() { return { ok: true, count: 4, items: demoCleanup().map((i) => ({ ...i, status: "ok", detail: i.kind === "download" ? "moved to Recycle Bin" : "uninstalled" })) }; },
    async cleanup_dismiss() {},
    async report_ui_error() {},
    async make_voice_kit() {
      let i = 0;
      const iv = setInterval(() => { i += 6; emit([["voicekit", i >= 64 ? { finished: true, ok: true, made: { laugh: 4 } } : { done: i, total: 64, what: "laugh" }]]); if (i >= 64) clearInterval(iv); }, 250);
      return { ok: true };
    },
    async get_user_sounds() { return {}; },
    async end_conversation() { emit([["state", { state: "idle", conversation: false }]]); },
    async open_log() { return { ok: false, path: "%APPDATA%\\Monkey\\monkey.log" }; },
    async offline_voice_state() { return { installed: false, own_voice: false, mode: "fallback", downloading: false }; },
    async download_offline_voice() {
      let mb = 0;
      const iv = setInterval(() => { mb += 25; emit([["offlinevoice", mb >= 200 ? { finished: true, ok: true, mb: 200 } : { done: mb * 1e6, total: 200e6, what: "downloading" }]]); if (mb >= 200) clearInterval(iv); }, 200);
      return { ok: true };
    },
    async test_offline_voice() { return { ok: false, error: "Download the offline voice first." }; },
    async get_sound() { return ""; },
    async get_policy() { return demoPolicy(); },
    async set_policy_entry(task, tier, model, effort) {
      const row = POLICY_ROWS.find((r) => r[0] === task);
      if (row) row[tier === "min" ? 2 : tier === "max" ? 4 : 3] = `${model}|${effort}`;
      return { ok: true };
    },
    async reset_policy() { return demoPolicy(); },
    async calibrate_start() {
      let i = 0;
      const iv = setInterval(() => {
        i += 7;
        emit([["calibration", i >= 49 ? { finished: true } : { done: i, total: 49, task: "Draft an email in your voice", config: "Opus 5.5 · medium" }]]);
        if (i >= 49) clearInterval(iv);
      }, 300);
      return { ok: true };
    },
    async calibrate_cancel() { return { ok: true }; },
    async calibration_estimate(tasks, samples) { return { usd: (tasks.length ? 0.1 * tasks.length : 3.0) * samples }; },
    async calibration_results() { return demoCalibration(); },
    async calibration_apply() { return { ok: true, changed: ["general"] }; },
    async update_state() { return { status: "up_to_date", detail: "", current: "0.3.40", available: "", enabled: true }; },
  };
}

// ------------------------------------------------------------------ demo data
let labFav = "";
const demoCleanup = () => [
  { kind: "app", label: "Old app: Monkey 0.1.0-dev (previous installer)", path: "C:\\Users\\you\\AppData\\Local\\Programs\\Monkey", status: "found", detail: "" },
  { kind: "download", label: "Download: MonkeySetup.zip", path: "C:\\Users\\you\\Downloads\\MonkeySetup.zip", status: "found", detail: "" },
  { kind: "download", label: "Unzipped folder: MonkeySetup\\", path: "C:\\Users\\you\\Downloads\\MonkeySetup", status: "found", detail: "" },
  { kind: "download", label: "Download: TyroneSetup.zip", path: "C:\\Users\\you\\Downloads\\TyroneSetup.zip", status: "found", detail: "" },
];
const inH = (hours: number) => new Date(Date.now() + hours * 3.6e6).toISOString();
function demoBoard() {
  const it = (o: any) => ({ points: null, impact_pct: null, course_grade: null, missing: false, url: "", done: false,
                            source: "canvas", ...o });
  return {
    source: "canvas",
    stats: { week_total: 8, week_done: 3, missing: 1, critical: 2 },
    todo: [
      it({ id: "a1", title: "HW 6: Red-black trees", course: "COMP SCI 400", due: inH(-50), points: 30, impact_pct: 4.2, course_grade: 84, missing: true, priority: 74, tier: "critical", reason: "~4.2% of your grade · MISSING · you're at 84% in COMP SCI 400" }),
      it({ id: "a2", title: "Midterm 2", course: "MATH 222", due: inH(20), points: 100, impact_pct: 20, course_grade: 79, priority: 92, tier: "critical", reason: "~20.0% of your grade · due in 20h · you're at 79% in MATH 222" }),
      it({ id: "a3", title: "Lab report 4", course: "CHEM 104", due: inH(70), points: 50, impact_pct: 3.1, course_grade: 88, priority: 50, tier: "high", reason: "~3.1% of your grade · due in 3d · you're at 88% in CHEM 104" }),
      it({ id: "a4", title: "Discussion post week 11", course: "PSYCH 202", due: inH(110), points: 5, impact_pct: 0.4, course_grade: 96, priority: 16, tier: "low", reason: "~0.4% of your grade · due in 5d · you're at 96% in PSYCH 202" }),
    ].sort((a, b) => b.priority - a.priority),
    done: [
      it({ id: "d1", title: "Reading quiz 10", course: "PSYCH 202", due: inH(-20), priority: 0, tier: "done", reason: "submitted", done: true }),
    ],
  };
}
function demoHealth() {
  const start = new Date(); start.setHours(0, 0, 0, 0);
  const series: [number, number][] = [];
  for (let m = 0; m < 17 * 60; m += 5) {
    const hr = m < 7 * 60 ? 52 + Math.sin(m / 40) * 3 : m > 15 * 60 && m < 16 * 60 ? 120 + Math.sin(m / 7) * 20 : 72 + Math.sin(m / 23) * 9;
    series.push([start.getTime() + m * 60e3, Math.round(hr)]);
  }
  return {
    date: new Date().toISOString().slice(0, 10),
    sleep: { score: 81, quality: "Good", total_min: 435, stages_min: { deep: 90, light: 240, rem: 95, awake: 10 } },
    heart: { resting: 51, min: 47, max: 148, seven_day_resting: 53, series },
    hrv: { last_night: 61, weekly_avg: 58, status: "Balanced" },
    day: { steps: 8421, body_battery: 64, stress_avg: 28 },
  };
}

// ------------------------------------------------------------------ demo data for Settings → Brain
const H = "claude-haiku-5-5", S5 = "claude-sonnet-5-5", O = "claude-opus-5-5";
const POLICY_ROWS: [string, string, string, string, string, number, number, number, string][] = [
  ["chat", "Chit-chat / small talk", `${H}|low`, `${H}|low`, `${S5}|low`, 0.0001, 0.7, 0.08, "Short spoken replies; Haiku is fastest."],
  ["web_lookup", "Quick web lookup (scores, hours, news)", `${H}|medium`, `${H}|medium`, `${S5}|medium`, 0.0162, 5.4, 2.43, "Haiku 5.5 supports web search."],
  ["assignments", "Canvas assignments / what to work on", `${H}|low`, `${H}|medium`, `${S5}|medium`, 0.0008, 3.4, 0.1, "Ranking is computed in code."],
  ["health", "Garmin sleep / heart rate", `${H}|low`, `${H}|medium`, `${S5}|medium`, 0.0006, 3.0, 0.04, "Numbers come from Garmin."],
  ["general", "Everyday question (no rule matched)", `${H}|medium`, `${S5}|low`, `${O}|medium`, 0.0083, 3.2, 1.65, "Sonnet low answers well and starts fast."],
  ["triage", "Email & calendar triage (ranking)", `${H}|high`, `${S5}|medium`, `${O}|medium`, 0.0748, 19.4, 3.37, "Structured ranking; think first."],
  ["study_help", "Study help / explain a concept", `${S5}|medium`, `${S5}|medium`, `${O}|high`, 0.0217, 16, 1.95, "Opus high when it's exam prep."],
  ["draft_email", "Draft an email in your voice", `${O}|low`, `${O}|medium`, `${O}|high`, 0.0914, 32.7, 4.11, "Tone and content matter most."],
  ["research", "Deep research", `${S5}|medium`, `${O}|medium`, `${O}|high`, 0.3422, 82.5, 10.27, "Medium matches high for less."],
];
const NAMES: Record<string, string> = { [H]: "Haiku 5.5", [S5]: "Sonnet 5.5", [O]: "Opus 5.5", "claude-fable-5-2": "Fable 5.2" };
function demoPolicy() {
  const pc = (v: string, usd: number, fw: number, mo: number) => {
    const [model, effort] = v.split("|");
    return { model, effort, label: `${NAMES[model]} · ${effort}`, usd, first_words_s: fw, per_month_usd: mo };
  };
  return {
    rows: POLICY_ROWS.map(([id, label, lo, def, hi, usd, fw, mo, why]) => ({
      id, label, why, internal: false,
      measured: id === "chat" ? { model: H, effort: "low", usd: 0.00009, first_words_s: 0.6, total_s: 0.9, date: "2026-11-18" } : null,
      min: pc(lo, usd * 0.5, fw * 0.8, mo * 0.5), default: pc(def, usd, fw, mo), max: pc(hi, usd * 3, fw * 1.8, mo * 3) })),
    totals: { min: 17.04, default: 29.02, max: 64.31 },
    models: Object.entries(NAMES).map(([id, name]) => ({ id, name })),
    efforts: ["low", "medium", "high", "xhigh", "max"],
    calibration_estimate: 3.0, calibrating: false, has_results: true,
  };
}
function demoCalibration() {
  return {
    ok: true, date: "2026-11-18", complete: true, spent_usd: 2.71,
    tasks: {
      general: { label: "Everyday question (no rule matched)", sample: "why do cats purr?", runs: [
        { model: H, effort: "medium", label: "Haiku 5.5 · medium", usd: 0.0021, first_words_s: 1.1, total_s: 2.4, error: "",
          answer: "Cats purr by twitching the muscles in their voice box about 25 to 150 times a second. It usually means they're content, but they also purr to calm themselves when hurt or stressed." },
        { model: S5, effort: "low", label: "Sonnet 5.5 · low", usd: 0.0074, first_words_s: 1.4, total_s: 3.0, error: "",
          answer: "It's their laryngeal muscles vibrating, 25–150 times a second, as they breathe in and out. Mostly contentment, but also self-soothing; some studies even link those frequencies to bone healing." },
        { model: O, effort: "medium", label: "Opus 5.5 · medium", usd: 0.0219, first_words_s: 2.6, total_s: 5.2, error: "",
          answer: "A neural oscillator in the brainstem makes the laryngeal muscles twitch 25–150 times per second, on both the in-breath and out-breath. It signals contentment, but cats also purr when stressed, giving birth or injured, likely to self-soothe." }] },
      draft_email: { label: "Draft an email in your voice", sample: "draft a reply to Professor Lee asking for a two-day extension on the lab report", runs: [
        { model: O, effort: "low", label: "Opus 5.5 · low", usd: 0.051, first_words_s: 5.8, total_s: 9.9, error: "",
          answer: "Draft's on your screen: short and polite, asks for two days and mentions you'll submit by Thursday.",
          outputs: [{ kind: "Email draft", to: "lee@wisc.edu", subject: "Re: BIO 151 lab report",
            text: "Hi Professor Lee,\n\nSorry for the late lab report. Would it be possible to have a two-day extension? I can submit it by Thursday.\n\nThanks,\nSam" }] },
        { model: O, effort: "medium", label: "Opus 5.5 · medium", usd: 0.083, first_words_s: 9.2, total_s: 15.1, error: "",
          answer: "Done, the draft's up. I apologized for the late lab report, asked for a two-day extension and offered Thursday 5 PM. Read it over and say send it when you're good.",
          outputs: [{ kind: "Email draft", to: "lee@wisc.edu", subject: "Re: BIO 151 lab report",
            text: "Hi Professor Lee,\n\nThanks for the heads up, and sorry for missing the deadline. Could I have a two-day extension on lab report 5? I can have it in by Thursday at 5 PM.\n\nThanks,\nSam" }] }] },
    },
  };
}
