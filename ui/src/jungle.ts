// Decorative jungle layer for the stage: swaying vines with leaves and banana bunches,
// big tropical leaves in the corners. Purely visual (aria-hidden).

const LEAF = (x: number, y: number, rot: number, scale = 1, fill = "#2fd35f") => `
  <g transform="translate(${x} ${y}) rotate(${rot}) scale(${scale})">
    <path d="M0,0 C14,-22 46,-24 64,0 C46,22 14,22 0,0 Z" fill="${fill}" stroke="#0b5a22" stroke-width="2"/>
    <path d="M2,0 L60,0 M20,0 L30,-9 M34,0 L44,-8 M20,0 L30,9 M34,0 L44,8" stroke="#0b5a22" stroke-width="1.6" fill="none"/>
  </g>`;

const BANANAS = (x: number, y: number, scale = 1) => `
  <g transform="translate(${x} ${y}) scale(${scale})">
    <path d="M0,0 L0,10" stroke="#5a3a10" stroke-width="5" stroke-linecap="round"/>
    ${[-26, -10, 8, 24].map((r, i) => `
      <path transform="rotate(${r} 0 10)" d="M0,10 C-8,30 -6,58 10,74 C4,56 6,32 8,12 Z"
            fill="${i % 2 ? "#ffd60a" : "#ffe55c"}" stroke="#8a5a00" stroke-width="2.2" stroke-linejoin="round"/>`).join("")}
  </g>`;

function vine(cls: string, left: string, length: number, bunchAt: number | null, flip = 1) {
  let d = "M20,0";
  const leaves: string[] = [];
  for (let y = 0; y < length; y += 40) {
    const x = 20 + Math.sin(y / 30) * 10 * flip;
    d += ` Q${x + 14 * flip},${y + 20} ${x},${y + 40}`;
    leaves.push(LEAF(x, y + 30, (y / 40) % 2 ? 30 : 150, 0.55, (y / 40) % 3 ? "#35e06a" : "#1fbf55"));
  }
  const bunch = bunchAt != null ? BANANAS(20, bunchAt, 0.9) : "";
  return `<svg class="vine ${cls}" style="left:${left}" width="90" height="${length + 90}" viewBox="-30 0 100 ${length + 90}">
    <path d="${d}" stroke="#1a7a32" stroke-width="5" fill="none" stroke-linecap="round"/>${leaves.join("")}${bunch}</svg>`;
}

const CORNER = (side: "l" | "r") => `
  <svg class="leaf-corner ${side}" style="${side === "l" ? "left:-30px" : "right:-30px"};bottom:-30px"
       width="260" height="240" viewBox="0 0 260 240">
    <g transform="${side === "r" ? "translate(260 0) scale(-1 1)" : ""}">
      ${LEAF(10, 230, -70, 2.6, "#13a844")}
      ${LEAF(20, 236, -40, 2.4, "#2ee865")}
      ${LEAF(30, 238, -12, 2.0, "#0f8c38")}
      ${LEAF(0, 210, -95, 1.6, "#42f57a")}
    </g>
  </svg>`;

export function decorateJungle(stage: HTMLElement) {
  const deco = document.createElement("div");
  deco.className = "jungle-deco";
  deco.setAttribute("aria-hidden", "true");
  deco.innerHTML =
    vine("v1", "4%", 220, 180) +
    vine("v2", "22%", 120, null, -1) +
    vine("v3", "70%", 170, 120, -1) +
    vine("v1", "86%", 260, null) +
    CORNER("l") + CORNER("r") +
    `<svg style="right:6%;top:40%" width="70" height="90" viewBox="-30 -5 70 95">${BANANAS(0, 0, 0.9)}</svg>`;
  stage.prepend(deco);
}
