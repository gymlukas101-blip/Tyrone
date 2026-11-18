// Talks to the Python side (pywebview js_api). Falls back to a demo mock in a normal browser.

export type Importance = "low" | "normal" | "high";

export interface AppState {
  settings: Record<string, any>;
  keys: Record<string, boolean>;
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
  save_key(name: string, value: string): Promise<boolean>;
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
}

declare global {
  interface Window {
    pywebview?: { api: Api };
    __tyroneEvents?: (events: [string, any][]) => void;
  }
}

export function waitForApi(timeoutMs = 2500): Promise<Api> {
  return new Promise((resolve) => {
    if (window.pywebview?.api) return resolve(window.pywebview.api);
    const done = () => resolve(window.pywebview!.api);
    window.addEventListener("pywebviewready", done, { once: true });
    setTimeout(() => {
      if (!window.pywebview?.api) resolve(mockApi());
    }, timeoutMs);
  });
}

// ------------------------------------------------------------------ demo mock
function mockApi(): Api {
  const emit = (events: [string, any][]) => window.__tyroneEvents?.(events);
  const later = (ms: number, fn: () => void) => setTimeout(fn, ms);
  const state: AppState = {
    settings: { user_name: "", monthly_budget_usd: 25, wakeword_threshold: 0.5, stt_engine: "whisper",
                canvas_ics_url: "", fish_voice_id: "", push_to_talk_hotkey: "ctrl+alt+space", first_run_complete: true },
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
      emit([["delta", { text: (i ? " " : "") + words[i] }], ["level", { v: 0.3 + Math.random() * 0.6 }]]);
      if (++i >= words.length) {
        clearInterval(iv);
        emit([["level", { v: 0 }], ["done", { text }], ["state", { state: "idle" }]]);
      }
    }, 140);
  };
  return {
    async get_state() { return state; },
    async save_key() { return true; },
    async save_settings(c) { Object.assign(state.settings, c); return state; },
    async send_text(text) {
      emit([["user", { text }], ["route", { label: "Opus 5.5 · medium", reason: "email drafting", importance: "normal" }],
            ["state", { state: "thinking" }]]);
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
  };
}
