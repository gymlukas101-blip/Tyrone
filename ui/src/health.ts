// Garmin health card: sleep score hero, sleep-stage bar, stat tiles, heart rate over the day.
import { h, minutes, s } from "./dom";

export interface Health {
  date: string;
  sleep: { score: number | null; quality: string | null; total_min: number | null;
           stages_min: { deep: number | null; light: number | null; rem: number | null; awake: number | null } };
  heart: { resting: number | null; min: number | null; max: number | null; seven_day_resting: number | null;
           series: [number, number][] };
  hrv: { last_night: number | null; weekly_avg: number | null; status: string | null };
  day: { steps: number | null; body_battery: number | null; stress_avg: number | null };
}

// Categorical slots 1-4 in fixed order (validated: CVD ΔE ≥ 8.4 adjacent, both modes).
const STAGES: [keyof Health["sleep"]["stages_min"], string, string][] = [
  ["deep", "Deep", "var(--series-1)"],
  ["light", "Light", "var(--series-2)"],
  ["rem", "REM", "var(--series-3)"],
  ["awake", "Awake", "var(--series-4)"],
];

function stageBar(st: Health["sleep"]["stages_min"]) {
  const total = STAGES.reduce((t, [k]) => t + (st[k] ?? 0), 0);
  if (!total) return null;
  const W = 400, H = 14, GAP = 2;
  const svg = s("svg", { viewBox: `0 0 ${W} ${H}`, class: "stagebar", preserveAspectRatio: "none", role: "img",
                         "aria-label": "Sleep stages" });
  const segs = STAGES.filter(([k]) => (st[k] ?? 0) > 0);
  let x = 0;
  const usable = W - GAP * (segs.length - 1);
  segs.forEach(([k, label, color], i) => {
    const w = ((st[k] ?? 0) / total) * usable;
    const first = i === 0, last = i === segs.length - 1;
    // Rounded outer ends only (4px), square inner joins with a 2px surface gap.
    const r = 4;
    const d = `M${x + (first ? r : 0)},0 H${x + w - (last ? r : 0)} ${last ? `Q${x + w},0 ${x + w},${r} V${H - r} Q${x + w},${H} ${x + w - r},${H}` : `V${H}`}
               H${x + (first ? r : 0)} ${first ? `Q${x},${H} ${x},${H - r} V${r} Q${x},0 ${x + r},0` : `V0`} Z`;
    const seg = s("path", { d, fill: color, class: "seg" }, s("title", {}, `${label}: ${minutes(st[k])}`));
    svg.append(seg);
    x += w + GAP;
  });
  const legend = h("div", { class: "legend" }, ...STAGES.map(([k, label, color]) =>
    h("span", {}, h("i", { style: `background:${color}` }), `${label} `, h("b", {}, minutes(st[k])))));
  return h("div", {}, svg, legend);
}

function tile(label: string, value: string, sub = "") {
  return h("div", { class: "tile" }, h("div", { class: "tile-v" }, value), h("div", { class: "tile-l" }, label),
    sub ? h("div", { class: "tile-s" }, sub) : null);
}

const hhmm = (ms: number) => new Date(ms).toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });

function hrChart(hd: Health["heart"]) {
  const pts = hd.series;
  if (pts.length < 2) return h("p", { class: "meta" }, "No heart-rate samples for this day yet.");
  const W = 600, H = 190, L = 34, R = 10, T = 12, B = 24;
  const t0 = pts[0][0], t1 = pts[pts.length - 1][0];
  const lo = Math.min(...pts.map((p) => p[1]), hd.resting ?? 999) - 5;
  const hi = Math.max(...pts.map((p) => p[1])) + 5;
  const X = (t: number) => L + ((t - t0) / Math.max(1, t1 - t0)) * (W - L - R);
  const Y = (v: number) => T + (1 - (v - lo) / Math.max(1, hi - lo)) * (H - T - B);
  const svg = s("svg", { viewBox: `0 0 ${W} ${H}`, class: "hrchart", role: "img",
                         "aria-label": `Heart rate from ${hhmm(t0)} to ${hhmm(t1)}, ${hd.min ?? ""} to ${hd.max ?? ""} bpm` });
  // Recessive grid + y ticks.
  const step = hi - lo > 80 ? 40 : 20;
  for (let v = Math.ceil(lo / step) * step; v <= hi; v += step) {
    svg.append(s("line", { x1: L, x2: W - R, y1: Y(v), y2: Y(v), class: "grid" }),
      s("text", { x: L - 6, y: Y(v) + 4, "text-anchor": "end", class: "axis" }, String(v)));
  }
  // X ticks every 3 hours.
  const start = new Date(t0); start.setMinutes(0, 0, 0);
  for (let t = start.getTime() + 3.6e6; t < t1; t += 3 * 3.6e6) {
    svg.append(s("text", { x: X(t), y: H - 6, "text-anchor": "middle", class: "axis" },
      new Date(t).toLocaleTimeString(undefined, { hour: "numeric" })));
  }
  if (hd.resting) {
    svg.append(s("line", { x1: L, x2: W - R, y1: Y(hd.resting), y2: Y(hd.resting), class: "ref" }),
      s("text", { x: W - R, y: Y(hd.resting) - 5, "text-anchor": "end", class: "axis" }, `resting ${hd.resting}`));
  }
  // Line, broken at gaps > 20 min (watch off).
  let d = "";
  pts.forEach(([t, v], i) => {
    const gap = i > 0 && t - pts[i - 1][0] > 20 * 60e3;
    d += `${i === 0 || gap ? "M" : "L"}${X(t).toFixed(1)},${Y(v).toFixed(1)} `;
  });
  svg.append(s("path", { d, class: "hrline" }));
  // Crosshair + tooltip.
  const cross = s("line", { y1: T, y2: H - B, class: "cross", visibility: "hidden" });
  const dot = s("circle", { r: 4, class: "crossdot", visibility: "hidden" });
  svg.append(cross, dot);
  const tip = h("div", { class: "tip", hidden: true });
  const wrap = h("div", { class: "chartwrap" }, svg, tip);
  svg.addEventListener("pointermove", (e) => {
    const box = svg.getBoundingClientRect();
    const t = t0 + (((e.clientX - box.left) / box.width) * W - L) / (W - L - R) * (t1 - t0);
    let best = pts[0];
    for (const p of pts) if (Math.abs(p[0] - t) < Math.abs(best[0] - t)) best = p;
    const x = X(best[0]), y = Y(best[1]);
    cross.setAttribute("x1", String(x)); cross.setAttribute("x2", String(x));
    dot.setAttribute("cx", String(x)); dot.setAttribute("cy", String(y));
    cross.setAttribute("visibility", "visible"); dot.setAttribute("visibility", "visible");
    tip.hidden = false;
    tip.replaceChildren(h("b", {}, `${best[1]} bpm`), ` ${hhmm(best[0])}`);
    const px = (x / W) * box.width;
    tip.style.left = `${Math.min(box.width - 110, Math.max(0, px - 50))}px`;
    tip.style.top = `${(y / H) * box.height - 40}px`;
  });
  svg.addEventListener("pointerleave", () => {
    cross.setAttribute("visibility", "hidden"); dot.setAttribute("visibility", "hidden"); tip.hidden = true;
  });
  // Table view (hourly averages) for accessibility.
  const hours = new Map<number, number[]>();
  for (const [t, v] of pts) {
    const k = new Date(t).setMinutes(0, 0, 0);
    hours.set(k, [...(hours.get(k) ?? []), v]);
  }
  const table = h("details", { class: "datatable" }, h("summary", {}, "Show data"),
    h("table", {}, h("tr", {}, h("th", {}, "Hour"), h("th", {}, "Avg bpm"), h("th", {}, "Max")),
      ...[...hours].map(([k, v]) => h("tr", {}, h("td", {}, hhmm(k)),
        h("td", {}, String(Math.round(v.reduce((a, b) => a + b, 0) / v.length))), h("td", {}, String(Math.max(...v)))))));
  return h("div", {}, wrap, table);
}

export function renderHealth(card: HTMLElement, hd: Health) {
  card.classList.add("health");
  const sl = hd.sleep;
  card.append(
    h("div", { class: "health-top" },
      h("div", { class: "hero" },
        h("div", { class: "hero-v" }, sl.score == null ? "—" : String(sl.score)),
        h("div", { class: "hero-l" }, "Sleep score"),
        h("div", { class: "hero-s" }, [sl.quality, sl.total_min ? `${minutes(sl.total_min)} asleep` : ""].filter(Boolean).join(" · "))),
      h("div", { class: "tiles" },
        tile("Resting HR", hd.heart.resting == null ? "—" : `${hd.heart.resting}`,
             hd.heart.seven_day_resting ? `7-day avg ${hd.heart.seven_day_resting}` : ""),
        tile("HRV", hd.hrv.last_night == null ? "—" : `${hd.hrv.last_night} ms`, hd.hrv.status ?? ""),
        tile("Body battery", hd.day.body_battery == null ? "—" : `${hd.day.body_battery}`),
        tile("Avg stress", hd.day.stress_avg == null ? "—" : `${hd.day.stress_avg}`),
        tile("Steps", hd.day.steps == null ? "—" : hd.day.steps.toLocaleString()))),
    h("h4", {}, "Sleep stages"),
    stageBar(sl.stages_min) ?? h("p", { class: "meta" }, "No sleep recorded."),
    h("h4", {}, "Heart rate"),
    hrChart(hd.heart),
  );
}
