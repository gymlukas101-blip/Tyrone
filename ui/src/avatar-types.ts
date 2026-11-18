// Shared interface for Monkey's avatars (3D model or the SVG fallback).

export type AvatarState = "idle" | "listening" | "thinking" | "speaking" | "transcribing";
export type Emote =
  | "celebrate" | "laugh" | "shrug" | "wave" | "happy" | "sad" | "angry" | "surprised" | "flex" | "dance";

export interface AvatarLike {
  setState(s: AvatarState): void;
  /** 0..1 loudness of Monkey's voice. */
  setLevel(v: number): void;
  /** Viseme weights, e.g. { viseme_aa: 0.7, viseme_O: 0.2 }. */
  setVisemes(w: Record<string, number>): void;
  emote(name: Emote): void;
}

/** Banana confetti over the avatar (shared by both avatars). */
export function bananaRain(host: HTMLElement) {
  let rain = host.querySelector<HTMLElement>(".banana-rain");
  if (!rain) {
    rain = document.createElement("div");
    rain.className = "banana-rain";
    rain.setAttribute("aria-hidden", "true");
    host.append(rain);
  }
  if (matchMedia("(prefers-reduced-motion: reduce)").matches) return;
  for (let i = 0; i < 18; i++) {
    const b = document.createElement("span");
    b.textContent = "🍌";
    b.style.left = `${5 + Math.random() * 90}%`;
    b.style.animationDelay = `${Math.random() * 0.6}s`;
    b.style.fontSize = `${18 + Math.random() * 18}px`;
    b.style.setProperty("--spin", `${(Math.random() * 2 - 1) * 540}deg`);
    rain.append(b);
    setTimeout(() => b.remove(), 2600);
  }
}
