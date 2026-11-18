// Tiny DOM helpers shared by the UI modules.

export type Child = Node | string | null | undefined | false;

export function h<K extends keyof HTMLElementTagNameMap>(
  tag: K, attrs: Record<string, any> = {}, ...children: Child[]
): HTMLElementTagNameMap[K] {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === undefined || v === null || v === false) continue;
    if (k.startsWith("on") && typeof v === "function") el.addEventListener(k.slice(2), v);
    else if (k === "class") el.className = v;
    else if (k in el && typeof v !== "string") (el as any)[k] = v;
    else el.setAttribute(k, String(v));
  }
  for (const c of children) if (c !== null && c !== undefined && c !== false) el.append(c);
  return el;
}

const SVGNS = "http://www.w3.org/2000/svg";
export function s<K extends keyof SVGElementTagNameMap>(
  tag: K, attrs: Record<string, string | number> = {}, ...children: (SVGElement | string)[]
): SVGElementTagNameMap[K] {
  const el = document.createElementNS(SVGNS, tag);
  for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, String(v));
  for (const c of children) el.append(c);
  return el;
}

export const fmtTime = (iso?: string) => {
  if (!iso) return "";
  const d = new Date(iso);
  return d.toLocaleString(undefined, { weekday: "short", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
};

export function toast(text: string, ms = 3500) {
  const t = h("div", { class: "toast" }, text);
  document.body.append(t);
  setTimeout(() => t.remove(), ms);
}

export const safeHttp = (u: string) => (/^https:\/\//i.test(u) ? u : "");

export function countdown(iso: string | null): string {
  if (!iso) return "no due date";
  const hours = (new Date(iso).getTime() - Date.now()) / 3.6e6;
  if (hours < 0) {
    const late = -hours;
    return late < 48 ? `${Math.round(late)}h overdue` : `${Math.round(late / 24)}d overdue`;
  }
  if (hours < 1) return `${Math.max(1, Math.round(hours * 60))}m left`;
  if (hours < 48) return `${Math.round(hours)}h left`;
  return `${Math.round(hours / 24)}d left`;
}

export const minutes = (m: number | null | undefined) =>
  m == null ? "—" : m >= 60 ? `${Math.floor(m / 60)}h ${String(m % 60).padStart(2, "0")}m` : `${m}m`;
