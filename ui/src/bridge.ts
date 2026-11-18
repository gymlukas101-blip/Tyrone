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
  save_key(name: string, value: string): Promise<{ ok: boolean; error?: string; hint?: string }>;
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
  test_voice(): Promise<void>;
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
}

export interface CleanupItem { kind: string; label: string; path: string; status: string; detail: string }
export interface CleanupResult { ok: boolean; error?: string; items?: CleanupItem[]; count?: number }

export interface UpdateState { status: string; detail: string; current: string; available: string; enabled: boolean }

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
    async push_to_talk() { emit([["state", { state: "listening" }]]); later(1500, () => emit([["state", { state: "idle" }]])); },
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
    async test_voice() {},
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
