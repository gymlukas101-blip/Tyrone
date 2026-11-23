// Quick-add parsing for the to-do panel: "call the dentist tomorrow 5pm !high #health" -> text, due, priority, list.
// A port of split_quick in monkey/memory/todos.py; tests/todo_due_cases.json holds the cases both must pass.
// Due strings are local wall-clock time: "YYYY-MM-DD" (a day) or "YYYY-MM-DDTHH:MM" (a time).

export interface Quick { text: string; due: string | null; priority: "low" | "normal" | "high"; list: string }

const WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"];
const WD_FULL = "(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)";
const WD_SHORT = "(?:mon|tues?|weds?|thu(?:rs?)?|fri|sat|sun)";
const MONTHS = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"];
const MON = "(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)";
const PART: Record<string, number> = { morning: 9, afternoon: 15, evening: 18, night: 20, tonight: 20 };
const LEAD = "(?:(?:\\bby|\\bat|\\bon|\\bdue|\\bbefore|\\buntil|@)\\s+)?";

const pad = (n: number) => String(n).padStart(2, "0");
const ymd = (d: Date) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
const addDays = (d: Date, n: number) => new Date(d.getFullYear(), d.getMonth(), d.getDate() + n);
/** Python's weekday(): Monday = 0. */
const wd = (d: Date) => (d.getDay() + 6) % 7;
const mod = (a: number, n: number) => ((a % n) + n) % n;
/** A real calendar date, or null (Feb 30 is not one). */
function mkDate(y: number, m: number, d: number): Date | null {
  const x = new Date(y, m - 1, d);
  return x.getFullYear() === y && x.getMonth() === m - 1 && x.getDate() === d ? x : null;
}

function hour(h: number, m: number, ap: string, bare: boolean): [number, number] | null {
  ap = (ap || "").toLowerCase().replace(/\./g, "");
  if (m > 59) return null;
  if (ap.startsWith("a")) return h >= 1 && h <= 12 ? [h === 12 ? 0 : h, m] : null;
  if (ap.startsWith("p")) return h >= 1 && h <= 12 ? [h === 12 ? 12 : h + 12, m] : null;
  if (bare && h >= 1 && h <= 7) return [h + 12, m];
  return h >= 0 && h <= 23 ? [h, m] : null;
}

export function splitQuick(phrase: string, now: Date = new Date()): Quick {
  let s = " " + (phrase || "").split(/\s+/).filter(Boolean).join(" ") + " ";
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  let day: Date | null = null;
  let hm: [number, number] | null = null;
  let exact: Date | null = null;
  let priority: Quick["priority"] = "normal";
  let list = "";
  const find = (p: string) => new RegExp(p, "i").exec(s);
  const cut = (m: RegExpExecArray) => { s = s.slice(0, m.index) + " " + s.slice(m.index + m[0].length); };

  let m = find("(?<!\\S)(?:!high|!h|!!!?|!urgent)(?!\\S)|\\b(?:high|top) priority\\b");
  if (m) { priority = "high"; cut(m); }
  m = find("(?<!\\S)(?:!low|!l)(?!\\S)|\\blow priority\\b");
  if (m) { priority = "low"; cut(m); }
  m = find("(?<!\\S)#([\\w-]{1,30})(?!\\S)");
  if (m) { list = m[1].toLowerCase(); cut(m); }

  m = find(LEAD + "\\b(\\d{4})-(\\d{2})-(\\d{2})(?:[T ](\\d{2}):(\\d{2})(?::\\d{2})?(?:\\.\\d+)?(?:Z|[+-]\\d{2}:?\\d{2})?)?\\b");
  if (m) {
    day = mkDate(+m[1], +m[2], +m[3]);
    if (day) { if (m[4]) hm = [+m[4], +m[5]]; cut(m); }
  }
  if (!day) {
    m = find("\\bin\\s+(half an|an|a|\\d{1,3})\\s*(minutes?|mins?|hours?|hrs?|h|days?|weeks?|wks?)\\b");
    if (m) {
      const nTxt = m[1].toLowerCase(), unit = m[2].toLowerCase();
      const n = nTxt === "half an" ? 0.5 : nTxt === "a" || nTxt === "an" ? 1 : parseInt(nTxt, 10);
      if (unit.startsWith("m")) exact = new Date(now.getTime() + n * 60e3);
      else if (unit.startsWith("h")) exact = new Date(now.getTime() + n * 3600e3);
      else if (unit.startsWith("d")) day = addDays(today, Math.trunc(n));
      else day = addDays(today, 7 * Math.trunc(n));
      cut(m);
    }
  }
  const none = () => !day && !exact;
  if (none()) {
    m = find(LEAD + "\\b(today|tonight|this (?:morning|afternoon|evening))\\b");
    if (m) {
      day = today;
      const w = m[1].toLowerCase().split(" ").pop()!;
      if (w in PART) hm = [PART[w], 0];
      cut(m);
    }
  }
  if (none()) {
    m = find(LEAD + "\\b(?:tomorrow|tmrw?|tomorow|tmw)(?:\\s+(morning|afternoon|evening|night))?\\b");
    if (m) { day = addDays(today, 1); if (m[1]) hm = [PART[m[1].toLowerCase()], 0]; cut(m); }
  }
  if (none()) {
    m = find("\\b(?:next week)\\b");
    if (m) { day = addDays(today, 7 - wd(today)); cut(m); }
  }
  if (none()) {
    m = find(LEAD + "\\b(?:this weekend|the weekend)\\b");
    if (m) { day = addDays(today, mod(5 - wd(today), 7)); cut(m); }
  }
  if (none()) {
    m = find(LEAD + "\\b(?:the )?end of (?:the |this )?week\\b");
    if (m) { day = addDays(today, mod(4 - wd(today), 7)); cut(m); }
  }
  if (none()) {
    m = find(LEAD + "\\b(next|this|on)?\\s*\\b(" + WD_FULL + ")\\b(?:\\s+(morning|afternoon|evening|night))?")
      ?? find("\\b(next|this|on|by|due|before|until)\\s+(" + WD_SHORT + ")\\b\\.?(?:\\s+(morning|afternoon|evening|night))?");
    if (m) {
      const idx = WEEKDAYS.findIndex((n) => n.startsWith(m![2].toLowerCase().slice(0, 3)));
      if ((m[1] ?? "").toLowerCase() === "next") day = addDays(today, 7 - wd(today) + idx);
      else day = addDays(today, mod(idx - wd(today), 7));
      if (m[3]) hm = [PART[m[3].toLowerCase()], 0];
      cut(m);
    }
  }
  if (none()) {
    const a = find(LEAD + "\\b(" + MON + ")\\.?\\s+(\\d{1,2})(?:st|nd|rd|th)?(?:,?\\s+(\\d{4}))?\\b");
    const b = a ? null : find(LEAD + "\\b(?:the\\s+)?(\\d{1,2})(?:st|nd|rd|th)?\\s+(?:of\\s+)?(" + MON + ")\\b(?:,?\\s+(\\d{4}))?");
    m = a ?? b;
    if (m) {
      const [monTok, dTok] = a ? [m[1], m[2]] : [m[2], m[1]];
      const mon = MONTHS.indexOf(monTok.toLowerCase().slice(0, 3)) + 1;
      const year = m[3] ? +m[3] : today.getFullYear();
      let d = mkDate(year, mon, +dTok);
      if (d && !m[3] && d < today) d = mkDate(year + 1, mon, +dTok);
      if (d) { day = d; cut(m); }
    }
  }
  if (none()) {
    m = find(LEAD + "\\bthe\\s+(\\d{1,2})(?:st|nd|rd|th)\\b");
    const want = m ? +m[1] : 0;
    if (m && want >= 1 && want <= 31) {
      let y = today.getFullYear(), mo = today.getMonth() + 1;
      if (want < today.getDate()) { if (mo === 12) { y += 1; mo = 1; } else mo += 1; }
      for (let i = 0; i < 3 && !day; i++) {
        day = mkDate(y, mo, want);
        if (!day) { if (mo === 12) { y += 1; mo = 1; } else mo += 1; }
      }
      if (day) cut(m);
    }
  }
  if (none()) {
    m = find(LEAD + "(?<![\\d/])(\\d{1,2})/(\\d{1,2})(?:/(\\d{2}|\\d{4}))?(?![\\d/])");
    if (m) {
      let year = m[3] ? +m[3] : today.getFullYear();
      if (year < 100) year += 2000;
      let d = mkDate(year, +m[1], +m[2]);
      if (d && !m[3] && d < today) d = mkDate(year + 1, +m[1], +m[2]);
      if (d) { day = d; cut(m); }
    }
  }

  if (!exact && !hm) {
    m = find(LEAD + "\\b(noon|midday|midnight)\\b");
    if (m) { hm = m[1].toLowerCase() === "midnight" ? [23, 59] : [12, 0]; cut(m); }
  }
  if (!exact && !hm) {
    m = find(LEAD + "\\b(\\d{1,2})(?::(\\d{2}))?(?:\\s*([ap]\\.?m\\b\\.?)|([ap]))(?![\\w])");
    if (m) { hm = hour(+m[1], +(m[2] ?? 0), m[3] ?? m[4] ?? "", false); if (hm) cut(m); }
  }
  if (!exact && !hm) {
    m = find("\\b(?:at|by|@|before)\\s+(\\d{1,2})(?::(\\d{2}))?\\b(?!\\s*(?:%|percent|pages?|min|hours?|days?))");
    if (m) { hm = hour(+m[1], +(m[2] ?? 0), "", true); if (hm) cut(m); }
  }
  if (!exact && !hm) {
    m = find(LEAD + "(?<![\\d:/.])\\b([01]?\\d|2[0-3]):([0-5]\\d)\\b");
    if (m) {
      const h24 = m[1].startsWith("0") || +m[1] >= 13;
      hm = hour(+m[1], +m[2], "", !h24);
      cut(m);
    }
  }
  if (!exact && !hm && day) {
    m = find(LEAD + "\\b(?:in the )?(morning|afternoon|evening|night)\\b");
    if (m) { hm = [PART[m[1].toLowerCase()], 0]; cut(m); }
  }

  let due: string | null = null;
  if (exact) due = `${ymd(exact)}T${pad(exact.getHours())}:${pad(exact.getMinutes())}`;
  else if (day || hm) {
    if (!day) day = hm![0] * 60 + hm![1] > now.getHours() * 60 + now.getMinutes() ? today : addDays(today, 1);
    due = ymd(day) + (hm ? `T${pad(hm[0])}:${pad(hm[1])}` : "");
  }
  let text = s.split(/\s+/).filter(Boolean).join(" ");
  text = text.replace(/(?:\s*\b(?:by|at|on|due|before|until)\b|\s*@)+\s*$/i, "");
  text = text.replace(/^\s*(?:remind me to|i need to|i have to|i gotta|need to|todo:?|to-do:?)\s+/i, "");
  text = text.replace(/^[\s,;:\-–—]+|[\s,;:\-–—]+$/g, "");
  return { text, due, priority, list };
}

/** The moment something is due: a day-only item is due at the end of that day. */
export function dueDate(due: string | null | undefined): Date | null {
  if (!due) return null;
  const m = /^(\d{4})-(\d{2})-(\d{2})(?:T(\d{2}):(\d{2}))?$/.exec(due);
  if (!m) return null;
  return m[4] ? new Date(+m[1], +m[2] - 1, +m[3], +m[4], +m[5]) : new Date(+m[1], +m[2] - 1, +m[3], 23, 59, 59);
}

export const hasTime = (due: string | null | undefined) => !!due && due.includes("T");

export function isOverdue(due: string | null | undefined, now: Date = new Date()): boolean {
  const d = dueDate(due);
  return !!d && d.getTime() < now.getTime();
}

/** "Today 5:00 PM", "Tomorrow", "Fri", "Thu Dec 3" (for rows and the parsed-date chip). */
export function dueLabel(due: string | null | undefined, now: Date = new Date()): string {
  const d = dueDate(due);
  if (!d) return "";
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const days = Math.round((new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime() - today.getTime()) / 864e5);
  let label = days === 0 ? "Today" : days === 1 ? "Tomorrow" : days === -1 ? "Yesterday"
    : days > 1 && days < 7 ? d.toLocaleDateString([], { weekday: "long" })
    : d.toLocaleDateString([], { weekday: "short", month: "short", day: "numeric" });
  if (hasTime(due)) label += " " + d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
  return label;
}

/** For <input type="datetime-local"> / type="date" values. */
export const toInputValue = (due: string | null | undefined) => due ?? "";
