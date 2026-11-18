// Tyrone's cartoon avatar: an original character drawn as layered SVG.
// The mouth follows the loudness of his voice; eyes blink; idle breathing;
// listening/thinking states change brows, eyes and the glow ring.

export type AvatarState = "idle" | "listening" | "thinking" | "speaking" | "transcribing";

const SKIN = "#8a5a35";
const SKIN_SHADE = "#734a2b";
const SKIN_LIGHT = "#a06c43";
const HAIR = "#1c1712";

const SVG = `
<svg viewBox="0 0 400 440" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="Tyrone">
  <defs>
    <radialGradient id="glow" cx="50%" cy="45%" r="55%">
      <stop offset="60%" stop-color="var(--glow)" stop-opacity="0"/>
      <stop offset="100%" stop-color="var(--glow)" stop-opacity="0.55"/>
    </radialGradient>
    <linearGradient id="hoodie" x1="0" x2="0" y1="0" y2="1">
      <stop offset="0" stop-color="#3a3f58"/>
      <stop offset="1" stop-color="#23263a"/>
    </linearGradient>
    <linearGradient id="gold" x1="0" x2="1">
      <stop offset="0" stop-color="#f7d774"/>
      <stop offset="0.5" stop-color="#e2ac2f"/>
      <stop offset="1" stop-color="#f7d774"/>
    </linearGradient>
    <clipPath id="mouthClip"><ellipse id="mouthClipShape" cx="0" cy="0" rx="26" ry="3"/></clipPath>
  </defs>

  <circle id="ring" cx="200" cy="215" r="198" fill="url(#glow)"/>

  <g id="body">
    <!-- hoodie -->
    <path d="M40,440 C48,372 110,338 200,336 C290,338 352,372 360,440 Z" fill="url(#hoodie)"/>
    <path d="M128,350 C150,392 250,392 272,350 C250,372 150,372 128,350 Z" fill="#2c3047"/>
    <path d="M168,372 L162,430 M232,372 L238,430" stroke="#c9ccd8" stroke-width="4" stroke-linecap="round"/>
    <!-- neck -->
    <path d="M160,300 L160,352 C180,368 220,368 240,352 L240,300 Z" fill="${SKIN_SHADE}"/>
    <!-- chain -->
    <path d="M150,346 C165,392 235,392 250,346" fill="none" stroke="url(#gold)" stroke-width="7"
          stroke-dasharray="7 3" stroke-linecap="round"/>
    <g transform="translate(200,392)">
      <path d="M0,-14 L12,0 L0,16 L-12,0 Z" fill="url(#gold)" stroke="#b8861b" stroke-width="2"/>
      <path d="M0,-8 L5,0 L0,8 L-5,0 Z" fill="#fff5c7" opacity="0.8"/>
    </g>
  </g>

  <g id="head">
    <!-- ears -->
    <ellipse cx="106" cy="205" rx="17" ry="27" fill="${SKIN}"/>
    <ellipse cx="294" cy="205" rx="17" ry="27" fill="${SKIN}"/>
    <ellipse cx="108" cy="206" rx="8" ry="15" fill="${SKIN_SHADE}"/>
    <ellipse cx="292" cy="206" rx="8" ry="15" fill="${SKIN_SHADE}"/>
    <circle cx="101" cy="226" r="4.5" fill="#e8f4ff" stroke="#9fc4e8" stroke-width="1.5"/>
    <circle cx="299" cy="226" r="4.5" fill="#e8f4ff" stroke="#9fc4e8" stroke-width="1.5"/>
    <!-- face -->
    <path d="M200,72 C262,72 298,118 298,186 C298,246 276,302 200,312 C124,302 102,246 102,186 C102,118 138,72 200,72 Z"
          fill="${SKIN}"/>
    <path d="M200,72 C262,72 298,118 298,186 C298,200 297,212 295,224 C282,150 250,104 200,100 C150,104 118,150 105,224
             C103,212 102,200 102,186 C102,118 138,72 200,72 Z" fill="${SKIN_LIGHT}" opacity="0.35"/>
    <!-- buzz-cut fade -->
    <path d="M104,170 C104,108 146,70 200,70 C254,70 296,108 296,170 C284,128 252,96 200,96 C148,96 116,128 104,170 Z"
          fill="${HAIR}" opacity="0.78"/>
    <!-- beard -->
    <path id="beard" d="M108,206 C112,262 140,312 200,318 C260,312 288,262 292,206 C286,236 272,252 256,258
             C246,240 226,232 200,234 C174,232 154,240 144,258 C128,252 114,236 108,206 Z" fill="${HAIR}"/>
    <!-- brows -->
    <g id="brows">
      <path id="browL" d="M138,148 C152,136 174,136 186,144 L184,154 C172,148 154,148 140,158 Z" fill="${HAIR}"/>
      <path id="browR" d="M262,148 C248,136 226,136 214,144 L216,154 C228,148 246,148 260,158 Z" fill="${HAIR}"/>
    </g>
    <!-- eyes -->
    <g id="eyes">
      <ellipse cx="162" cy="180" rx="19" ry="13" fill="#fdfaf3"/>
      <ellipse cx="238" cy="180" rx="19" ry="13" fill="#fdfaf3"/>
      <g id="pupils">
        <circle cx="164" cy="181" r="9" fill="#3b2412"/>
        <circle cx="240" cy="181" r="9" fill="#3b2412"/>
        <circle cx="164" cy="181" r="4.5" fill="#0d0805"/>
        <circle cx="240" cy="181" r="4.5" fill="#0d0805"/>
        <circle cx="167" cy="177" r="2.6" fill="#fff"/>
        <circle cx="243" cy="177" r="2.6" fill="#fff"/>
      </g>
      <!-- relaxed upper lids (gives the cool, half-lidded look) -->
      <path id="lidL" d="M141,166 C150,160 176,160 183,168 L183,176 C170,170 152,170 141,176 Z" fill="${SKIN_SHADE}"/>
      <path id="lidR" d="M259,166 C250,160 224,160 217,168 L217,176 C230,170 248,170 259,176 Z" fill="${SKIN_SHADE}"/>
      <rect id="blinkL" x="140" y="164" width="44" height="0" fill="${SKIN_SHADE}"/>
      <rect id="blinkR" x="216" y="164" width="44" height="0" fill="${SKIN_SHADE}"/>
    </g>
    <!-- nose -->
    <path d="M200,186 C198,206 190,218 184,224 C190,232 210,232 216,224 C210,218 202,206 200,186 Z" fill="${SKIN_SHADE}"/>
    <ellipse cx="189" cy="226" rx="6" ry="4" fill="#4d2f19"/>
    <ellipse cx="211" cy="226" rx="6" ry="4" fill="#4d2f19"/>
    <!-- mustache -->
    <path d="M160,250 C172,238 190,238 200,244 C210,238 228,238 240,250 C228,248 212,250 200,252 C188,250 172,248 160,250 Z"
          fill="${HAIR}"/>
    <!-- mouth -->
    <g id="mouth" transform="translate(200,266)">
      <ellipse id="mouthCavity" cx="0" cy="0" rx="26" ry="3" fill="#3a1010"/>
      <g clip-path="url(#mouthClip)">
        <rect id="teeth" x="-22" y="-30" width="44" height="27" rx="4" fill="#fbf7ef"/>
        <ellipse id="tongue" cx="0" cy="18" rx="15" ry="10" fill="#c45a5a"/>
      </g>
      <path id="lips" d="M-28,0 C-14,-5 14,-5 28,0 C14,6 -14,6 -28,0 Z" fill="#5e2f22" opacity="0.9"/>
    </g>
    <!-- thinking dots -->
    <g id="thinkDots" opacity="0">
      <circle cx="300" cy="96" r="7" fill="var(--glow)"/>
      <circle cx="322" cy="74" r="9" fill="var(--glow)"/>
      <circle cx="350" cy="50" r="12" fill="var(--glow)"/>
    </g>
  </g>
</svg>`;

const COLORS: Record<AvatarState, string> = {
  idle: "#6c7bff",
  listening: "#2fe39a",
  transcribing: "#2fe39a",
  thinking: "#ffb547",
  speaking: "#ff5ea8",
};

export class Avatar {
  private root: HTMLElement;
  private q = <T extends Element>(id: string) => this.root.querySelector<T>(`#${id}`)!;
  private state: AvatarState = "idle";
  private level = 0;
  private mouth = 0;
  private nextBlink = performance.now() + 2500;
  private blinkUntil = 0;
  private roundness = 0;

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

  /** 0..1 loudness of Tyrone's voice (drives the mouth). */
  setLevel(v: number) {
    this.level = Math.max(0, Math.min(1, v));
  }

  private frame = (t: number) => {
    const s = this.state;
    // Mouth: fast attack, slower release, with a little "shape" variation so it reads as talking.
    const target = s === "speaking" ? Math.min(1, this.level * 1.6) : 0;
    this.mouth += (target - this.mouth) * (target > this.mouth ? 0.55 : 0.25);
    if (s === "speaking" && Math.random() < 0.06) this.roundness = Math.random();
    const open = this.mouth;
    const rx = 26 - open * 6 - this.roundness * open * 8;
    const ry = 3 + open * 20;
    for (const id of ["mouthCavity", "mouthClipShape"]) {
      const e = this.q<SVGEllipseElement>(id);
      e.setAttribute("rx", rx.toFixed(1));
      e.setAttribute("ry", ry.toFixed(1));
    }
    this.q<SVGPathElement>("lips").style.opacity = open > 0.12 ? "0" : "0.9";
    this.q<SVGGElement>("teeth").setAttribute("y", (-ry - 2).toFixed(1));
    this.q<SVGGElement>("teeth").setAttribute("height", (ry * 0.45 + 2).toFixed(1));

    // Blink.
    if (t > this.nextBlink) {
      this.blinkUntil = t + 130;
      this.nextBlink = t + 2500 + Math.random() * 3500;
    }
    const blinkH = t < this.blinkUntil ? 30 : 0;
    this.q("blinkL").setAttribute("height", String(blinkH));
    this.q("blinkR").setAttribute("height", String(blinkH));

    // Head motion: breathing, nod while talking, tilt while listening.
    const breathe = Math.sin(t / 900) * 2;
    const bob = s === "speaking" ? Math.sin(t / 110) * open * 3 : 0;
    const tilt = s === "listening" || s === "transcribing" ? -4 : s === "thinking" ? 3 : 0;
    this.q<SVGGElement>("head").setAttribute(
      "transform",
      `translate(0 ${(breathe + bob).toFixed(2)}) rotate(${tilt} 200 300)`,
    );
    this.q<SVGGElement>("body").setAttribute("transform", `translate(0 ${(breathe * 0.5).toFixed(2)})`);

    // Brows + eyes per state.
    const browUp = s === "listening" || s === "transcribing" ? -7 : s === "thinking" ? -3 : 0;
    this.q("browL").setAttribute("transform", `translate(0 ${browUp})`);
    this.q("browR").setAttribute("transform", `translate(0 ${s === "thinking" ? 2 : browUp})`);
    const look = s === "thinking" ? "translate(5 -5)" : s === "listening" ? "translate(0 -1)" : "translate(0 0)";
    this.q("pupils").setAttribute("transform", look);
    const lidDrop = s === "idle" ? 2 : s === "listening" ? -5 : 0;
    this.q("lidL").setAttribute("transform", `translate(0 ${lidDrop})`);
    this.q("lidR").setAttribute("transform", `translate(0 ${lidDrop})`);

    // Glow ring pulse + thinking dots.
    const pulse = s === "listening" ? 1 + Math.sin(t / 200) * 0.03 : s === "speaking" ? 1 + open * 0.04 : 1;
    this.q("ring").setAttribute("transform", `translate(200 215) scale(${pulse.toFixed(3)}) translate(-200 -215)`);
    const dots = this.q<SVGGElement>("thinkDots");
    dots.style.opacity = s === "thinking" ? String(0.55 + Math.sin(t / 250) * 0.35) : "0";

    requestAnimationFrame(this.frame);
  };
}
