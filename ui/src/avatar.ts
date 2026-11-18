// Monkey: a big, buff, original cartoon monkey drawn as layered SVG.
// Mouth follows the loudness of his voice; eyes blink; idle breathing; arms pose per state;
// emotes: "celebrate" (double-bicep flex + banana rain), "laugh", "shrug".

import type { AvatarLike, AvatarState, Emote } from "./avatar-types";

export type { AvatarState, Emote };
type SvgEmote = "celebrate" | "laugh" | "shrug";
const SVG_EMOTE: Record<Emote, SvgEmote> = {
  celebrate: "celebrate", flex: "celebrate", dance: "celebrate", happy: "celebrate", wave: "celebrate",
  laugh: "laugh", shrug: "shrug", surprised: "shrug", sad: "shrug", angry: "shrug",
};

const FUR = "#7a4518";
const FUR_DARK = "#5a300f";
const FUR_LIGHT = "#9a5b25";
const FACE = "#f6c48b";
const FACE_SHADE = "#e0a565";
const OUTLINE = "#2b1405";

// One arm: upper arm + bicep + forearm + fist, pivoting at the shoulder (0,0).
const arm = (id: string, flip: 1 | -1) => `
  <g id="${id}">
    <rect x="-30" y="-6" width="60" height="112" rx="30" fill="${FUR}" stroke="${OUTLINE}" stroke-width="3"/>
    <ellipse id="${id}Bicep" cx="${-8 * flip}" cy="52" rx="24" ry="30" fill="${FUR_LIGHT}" opacity="0.9"/>
    <g id="${id}Fore" transform="translate(0 98)">
      <rect x="-25" y="-6" width="50" height="96" rx="25" fill="${FUR}" stroke="${OUTLINE}" stroke-width="3"/>
      <circle cx="0" cy="96" r="29" fill="${FACE}" stroke="${OUTLINE}" stroke-width="3"/>
      <path d="M-14,86 Q0,80 14,86 M-16,98 Q0,92 16,98" stroke="${FACE_SHADE}" stroke-width="3" fill="none" stroke-linecap="round"/>
    </g>
  </g>`;

const SVG = `
<svg viewBox="0 0 400 440" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="Monkey">
  <defs>
    <radialGradient id="glow" cx="50%" cy="45%" r="55%">
      <stop offset="55%" stop-color="var(--glow)" stop-opacity="0"/>
      <stop offset="100%" stop-color="var(--glow)" stop-opacity="0.7"/>
    </radialGradient>
    <linearGradient id="tank" x1="0" x2="0" y1="0" y2="1">
      <stop offset="0" stop-color="#22e06b"/>
      <stop offset="1" stop-color="#0fa84a"/>
    </linearGradient>
    <linearGradient id="band" x1="0" x2="1">
      <stop offset="0" stop-color="#ff2d78"/>
      <stop offset="1" stop-color="#ff7a1a"/>
    </linearGradient>
    <clipPath id="bodyClip"><rect x="-300" y="-300" width="1000" height="740"/></clipPath>
    <clipPath id="mouthClip"><ellipse id="mouthClipShape" cx="0" cy="0" rx="30" ry="3"/></clipPath>
  </defs>

  <circle id="ring" cx="200" cy="215" r="198" fill="url(#glow)"/>

  <g clip-path="url(#bodyClip)"><g id="body">
    <!-- torso -->
    <path d="M78,440 C70,372 96,304 150,290 L250,290 C304,304 330,372 322,440 Z" fill="${FUR}" stroke="${OUTLINE}" stroke-width="3"/>
    <!-- traps -->
    <path d="M118,300 Q200,246 282,300 Q200,284 118,300 Z" fill="${FUR_DARK}"/>
    <!-- chest + pecs -->
    <path d="M140,312 Q200,300 260,312 Q262,350 200,356 Q138,350 140,312 Z" fill="${FACE}" stroke="${OUTLINE}" stroke-width="2.5"/>
    <path d="M200,316 L200,352 M150,338 Q176,352 198,346 M250,338 Q224,352 202,346" stroke="${FACE_SHADE}" stroke-width="3" fill="none" stroke-linecap="round"/>
    <!-- tank top -->
    <path d="M126,300 L156,300 Q170,356 200,362 Q230,356 244,300 L274,300 Q300,360 304,440 L96,440 Q100,360 126,300 Z"
          fill="url(#tank)" stroke="${OUTLINE}" stroke-width="3"/>
    <!-- banana logo -->
    <g transform="translate(200 402) rotate(-18)">
      <path d="M-26,-6 Q-4,18 26,-10 Q22,8 2,14 Q-18,16 -26,-6 Z" fill="#ffe14d" stroke="${OUTLINE}" stroke-width="2.5"/>
      <path d="M24,-10 L30,-16" stroke="${OUTLINE}" stroke-width="4" stroke-linecap="round"/>
    </g>
    <!-- arms (in front of the torso so poses like hand-to-chin read) -->
    <g transform="translate(92 318)"><g id="armLPivot">${arm("armL", 1)}</g></g>
    <g transform="translate(308 318)"><g id="armRPivot">${arm("armR", -1)}</g></g>
    <!-- shoulders (deltoids) on top -->
    <circle cx="92" cy="318" r="40" fill="${FUR}" stroke="${OUTLINE}" stroke-width="3"/>
    <circle cx="308" cy="318" r="40" fill="${FUR}" stroke="${OUTLINE}" stroke-width="3"/>
    <path d="M70,306 Q92,290 114,304 M286,304 Q308,290 330,306" stroke="${FUR_LIGHT}" stroke-width="5" fill="none" stroke-linecap="round"/>
  </g></g>

  <g id="head">
    <!-- ears -->
    <g id="earL"><circle cx="104" cy="182" r="36" fill="${FUR}" stroke="${OUTLINE}" stroke-width="3"/><circle cx="106" cy="184" r="22" fill="${FACE}"/></g>
    <g id="earR"><circle cx="296" cy="182" r="36" fill="${FUR}" stroke="${OUTLINE}" stroke-width="3"/><circle cx="294" cy="184" r="22" fill="${FACE}"/></g>
    <!-- head fur -->
    <circle cx="200" cy="178" r="96" fill="${FUR}" stroke="${OUTLINE}" stroke-width="3"/>
    <path d="M186,86 Q192,62 200,80 Q206,58 214,84 Q224,70 222,92" fill="${FUR}" stroke="${OUTLINE}" stroke-width="3" stroke-linejoin="round"/>
    <!-- face mask: two eye lobes + big muzzle -->
    <g fill="${FACE}">
      <circle cx="166" cy="168" r="42"/><circle cx="234" cy="168" r="42"/>
      <ellipse cx="200" cy="232" rx="70" ry="52"/>
    </g>
    <path d="M124,168 A42,42 0 0 1 200,146 A42,42 0 0 1 276,168" fill="none" stroke="${OUTLINE}" stroke-width="2.5" opacity="0.5"/>
    <!-- headband -->
    <path d="M110,134 Q200,84 290,134 L286,154 Q200,106 114,154 Z" fill="url(#band)" stroke="${OUTLINE}" stroke-width="3"/>
    <path d="M286,140 L310,128 L306,152 Z M288,146 L312,160 L294,166 Z" fill="#ff2d78" stroke="${OUTLINE}" stroke-width="2.5" stroke-linejoin="round"/>
    <!-- brows (heavy fur ridges) -->
    <path id="browL" d="M132,152 Q160,134 192,146 L190,156 Q160,148 136,162 Z" fill="${FUR_DARK}"/>
    <path id="browR" d="M268,152 Q240,134 208,146 L210,156 Q240,148 264,162 Z" fill="${FUR_DARK}"/>
    <!-- eyes -->
    <ellipse cx="166" cy="176" rx="19" ry="17" fill="#fff" stroke="${OUTLINE}" stroke-width="2.5"/>
    <ellipse cx="234" cy="176" rx="19" ry="17" fill="#fff" stroke="${OUTLINE}" stroke-width="2.5"/>
    <g id="pupils">
      <circle cx="168" cy="178" r="10" fill="#6b3a12"/><circle cx="236" cy="178" r="10" fill="#6b3a12"/>
      <circle cx="168" cy="178" r="5.5" fill="#120802"/><circle cx="236" cy="178" r="5.5" fill="#120802"/>
      <circle cx="171" cy="174" r="3" fill="#fff"/><circle cx="239" cy="174" r="3" fill="#fff"/>
    </g>
    <path id="lidL" d="M146,166 Q166,154 186,166 L186,170 Q166,162 146,170 Z" fill="${FACE_SHADE}"/>
    <path id="lidR" d="M214,166 Q234,154 254,166 L254,170 Q234,162 214,170 Z" fill="${FACE_SHADE}"/>
    <rect id="blinkL" x="144" y="158" width="44" height="0" fill="${FACE_SHADE}"/>
    <rect id="blinkR" x="212" y="158" width="44" height="0" fill="${FACE_SHADE}"/>
    <!-- nose -->
    <path d="M186,206 Q200,198 214,206 Q214,218 200,220 Q186,218 186,206 Z" fill="${FACE_SHADE}"/>
    <ellipse cx="193" cy="212" rx="4.5" ry="3.5" fill="${OUTLINE}"/>
    <ellipse cx="207" cy="212" rx="4.5" ry="3.5" fill="${OUTLINE}"/>
    <!-- mouth -->
    <g id="mouth" transform="translate(200 248)">
      <ellipse id="mouthCavity" cx="0" cy="0" rx="30" ry="3" fill="#5a1414"/>
      <g clip-path="url(#mouthClip)">
        <rect id="teeth" x="-26" y="-30" width="52" height="27" rx="4" fill="#fffdf5"/>
        <ellipse id="tongue" cx="0" cy="20" rx="17" ry="11" fill="#ff6b8b"/>
      </g>
      <path id="lips" d="M-34,-4 Q0,20 34,-4" fill="none" stroke="${OUTLINE}" stroke-width="4" stroke-linecap="round"/>
    </g>
    <!-- cheeks -->
    <ellipse cx="148" cy="226" rx="12" ry="7" fill="#ff7a8a" opacity="0.45"/>
    <ellipse cx="252" cy="226" rx="12" ry="7" fill="#ff7a8a" opacity="0.45"/>
    <!-- thinking dots -->
    <g id="thinkDots" opacity="0">
      <circle cx="300" cy="96" r="7" fill="var(--glow)"/><circle cx="324" cy="72" r="9" fill="var(--glow)"/>
      <circle cx="354" cy="46" r="12" fill="var(--glow)"/>
    </g>
  </g>
</svg>
<div class="banana-rain" aria-hidden="true"></div>`;

const COLORS: Record<AvatarState, string> = {
  idle: "#ffd60a",
  listening: "#39ff6a",
  transcribing: "#39ff6a",
  thinking: "#ff9f1a",
  speaking: "#ff3d9a",
};

// Arm pose targets in degrees: [left upper, left fore, right upper, right fore].
type Pose = [number, number, number, number];
const POSES: Record<string, Pose> = {
  idle: [14, -8, -14, 8],
  listening: [14, -8, -150, -40],     // right hand cupped near ear
  thinking: [14, -8, 35, 121],        // right fist to chin
  speaking: [20, -30, -20, 30],
  celebrate: [100, 95, -100, -95],    // double-bicep flex
  shrug: [60, -110, -60, 110],
  laugh: [30, 60, -30, -60],
};

export class Avatar implements AvatarLike {
  private root: HTMLElement;
  private q = <T extends Element>(id: string) => this.root.querySelector<T>(`#${id}`)!;
  private state: AvatarState = "idle";
  private level = 0;
  private mouth = 0;
  private nextBlink = performance.now() + 2500;
  private blinkUntil = 0;
  private roundness = 0;
  private pose: Pose = [...POSES.idle] as Pose;
  private emoteName: SvgEmote | null = null;
  private emoteUntil = 0;
  private nextFidget = performance.now() + 9000;

  constructor(host: HTMLElement) {
    this.root = host;
    host.innerHTML = SVG;
    this.setState("idle");
    requestAnimationFrame(this.frame);
  }

  setState(s: AvatarState) {
    this.state = s;
    this.root.style.setProperty("--glow", COLORS[s]);
    this.root.dataset.state = s;
  }

  /** 0..1 loudness of Monkey's voice (drives the mouth). */
  setLevel(v: number) {
    this.level = Math.max(0, Math.min(1, v));
  }

  setVisemes(_w: Record<string, number>) {
    // The SVG fallback lip-syncs from loudness only.
  }

  emote(name: Emote, ms = 2200, rain = true) {
    const mapped = SVG_EMOTE[name] ?? "celebrate";
    this.emoteName = mapped;
    this.emoteUntil = performance.now() + ms;
    if (mapped === "celebrate" && rain && name !== "wave" && name !== "happy") this.bananaRain();
  }

  private bananaRain() {
    const rain = this.root.querySelector<HTMLElement>(".banana-rain");
    if (!rain || matchMedia("(prefers-reduced-motion: reduce)").matches) return;
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

  private frame = (t: number) => {
    const s = this.state;
    const emoting = this.emoteName && t < this.emoteUntil ? this.emoteName : null;
    if (!emoting) this.emoteName = null;

    // Idle fidget: a quick flex every so often, so he never looks frozen.
    if (s === "idle" && !emoting && t > this.nextFidget) {
      this.emote(Math.random() < 0.6 ? "celebrate" : "shrug", 1400, false);
      this.nextFidget = t + 14000 + Math.random() * 12000;
    }

    // Mouth: fast attack, slower release, a little shape variation.
    const talking = s === "speaking";
    const target = talking ? Math.min(1, this.level * 1.6) : emoting === "laugh" ? 0.6 + Math.sin(t / 70) * 0.3 : 0;
    this.mouth += (target - this.mouth) * (target > this.mouth ? 0.55 : 0.25);
    if (talking && Math.random() < 0.06) this.roundness = Math.random();
    const open = this.mouth;
    const rx = 30 - open * 6 - this.roundness * open * 9;
    const ry = 3 + open * 22;
    for (const id of ["mouthCavity", "mouthClipShape"]) {
      const e = this.q<SVGEllipseElement>(id);
      e.setAttribute("rx", rx.toFixed(1));
      e.setAttribute("ry", ry.toFixed(1));
    }
    this.q<SVGPathElement>("lips").style.opacity = open > 0.12 ? "0" : "1";
    this.q("teeth").setAttribute("y", (-ry - 2).toFixed(1));
    this.q("teeth").setAttribute("height", (ry * 0.45 + 2).toFixed(1));

    // Blink.
    if (t > this.nextBlink) {
      this.blinkUntil = t + 130;
      this.nextBlink = t + 2500 + Math.random() * 3500;
    }
    const blinkH = t < this.blinkUntil || emoting === "laugh" ? 26 : 0;
    this.q("blinkL").setAttribute("height", String(blinkH));
    this.q("blinkR").setAttribute("height", String(blinkH));

    // Arms ease toward the pose for the current emote/state.
    const want = POSES[emoting ?? s] ?? POSES.idle;
    const flexPulse = emoting === "celebrate" ? Math.sin(t / 120) * 6 : 0;
    const talkSway = talking ? Math.sin(t / 160) * 10 * (0.3 + open) : 0;
    for (let i = 0; i < 4; i++) this.pose[i] += (want[i] - this.pose[i]) * 0.14;
    const [lu, lf, ru, rf] = this.pose;
    this.q("armLPivot").setAttribute("transform", `rotate(${(lu + talkSway).toFixed(1)})`);
    this.q("armLFore").setAttribute("transform", `translate(0 98) rotate(${(lf + flexPulse).toFixed(1)})`);
    this.q("armRPivot").setAttribute("transform", `rotate(${(ru - talkSway).toFixed(1)})`);
    this.q("armRFore").setAttribute("transform", `translate(0 98) rotate(${(rf - flexPulse).toFixed(1)})`);
    const bicep = 1 + Math.max(0, (Math.abs(lu) - 30) / 70) * 0.35 + (emoting === "celebrate" ? Math.abs(flexPulse) / 40 : 0);
    for (const id of ["armLBicep", "armRBicep"]) {
      this.q(id).setAttribute("transform", `translate(0 52) scale(${bicep.toFixed(3)}) translate(0 -52)`);
    }

    // Head motion: breathing, nod while talking, tilt while listening, bounce when celebrating.
    const breathe = Math.sin(t / 900) * 2;
    const bob = talking ? Math.sin(t / 110) * open * 3 : 0;
    const hop = emoting === "celebrate" || emoting === "laugh" ? -Math.abs(Math.sin(t / 140)) * 8 : 0;
    const tilt = s === "listening" || s === "transcribing" ? -6 : s === "thinking" ? 5 : emoting === "shrug" ? 7 : 0;
    this.q("head").setAttribute("transform",
      `translate(0 ${(breathe + bob + hop).toFixed(2)}) rotate(${tilt} 200 300)`);
    this.q("body").setAttribute("transform", `translate(0 ${(breathe * 0.6 + hop * 0.5).toFixed(2)})`);
    const earScale = s === "listening" || s === "transcribing" ? 1.12 : 1;
    this.q("earL").setAttribute("transform", `translate(104 182) scale(${earScale}) translate(-104 -182)`);
    this.q("earR").setAttribute("transform", `translate(296 182) scale(${earScale}) translate(-296 -182)`);

    // Brows + eyes per state.
    const browUp = s === "listening" || s === "transcribing" ? -8 : s === "thinking" ? -4 : emoting ? -6 : 0;
    this.q("browL").setAttribute("transform", `translate(0 ${browUp})`);
    this.q("browR").setAttribute("transform", `translate(0 ${s === "thinking" ? 3 : browUp})`);
    const look = s === "thinking" ? "translate(5 -5)" : s === "listening" ? "translate(-2 -1)" : "translate(0 0)";
    this.q("pupils").setAttribute("transform", look);
    const lidDrop = s === "idle" && !emoting ? 3 : s === "listening" ? -6 : 0;
    this.q("lidL").setAttribute("transform", `translate(0 ${lidDrop})`);
    this.q("lidR").setAttribute("transform", `translate(0 ${lidDrop})`);

    // Glow ring + thinking dots.
    const pulse = s === "listening" ? 1 + Math.sin(t / 200) * 0.03 : talking ? 1 + open * 0.05 : 1;
    this.q("ring").setAttribute("transform", `translate(200 215) scale(${pulse.toFixed(3)}) translate(-200 -215)`);
    this.q<SVGGElement>("thinkDots").style.opacity = s === "thinking" ? String(0.55 + Math.sin(t / 250) * 0.35) : "0";

    requestAnimationFrame(this.frame);
  };
}
