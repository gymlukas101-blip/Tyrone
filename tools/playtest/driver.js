// Playtest driver: one persistent Chromium page that a tester controls step by step over HTTP, the way a person
// would: look at what's on screen (only what's inside the window), click things by their number, type, scroll.
//
//   node tools/playtest/driver.js <driverPort> <backendPort> <outDir>
//
//   GET /see                      what's on screen now (+ toasts that appeared since last look, file picker state)
//   GET /shot                     screenshot -> {path} (look at it with an image viewer)
//   GET /click?n=12               click control #12 (from /see)
//   GET /type?n=5&text=hello      replace the text in field #5
//   GET /press?key=Enter          press a key (Enter, Escape, Tab, Control+a ...)
//   GET /hover?n=3                hover over control #3 (shows its tooltip, if any)
//   GET /select?n=7&option=Always use the offline voice
//   GET /check?n=9                toggle checkbox #9
//   GET /scroll?dy=600            scroll the thing under the middle of the screen (negative = up)
//   GET /wait?ms=3000             wait (things load, Monkey answers)
//   GET /pick?files=a.json|b.md   choose file(s) in an open file picker (paths from /see); /pick with no files = Cancel
//   GET /log                      every action so far, with timestamps (for the report)
const http = require("http");
const fs = require("fs");
const path = require("path");
const { chromium } = require("playwright");

const [driverPort, backendPort, outDir] = [Number(process.argv[2] || 9301), Number(process.argv[3] || 8801), process.argv[4] || "/tmp/pt"];
fs.mkdirSync(outDir, { recursive: true });
const base = `http://127.0.0.1:${backendPort}`;
const actions = [];
let page, shots = 0;

const SEE = () => {
  // Everything below runs in the page.
  const vw = innerWidth, vh = innerHeight;
  const modal = [...document.querySelectorAll("dialog[open]")].pop() || null;
  const root = modal || document.body;
  const visible = (el) => {
    const r = el.getBoundingClientRect();
    if (r.width < 2 || r.height < 2 || r.bottom < 0 || r.right < 0 || r.top > vh || r.left > vw) return false;
    const cs = getComputedStyle(el);
    if (cs.visibility === "hidden" || cs.display === "none" || Number(cs.opacity) === 0) return false;
    // clipped by a scrolling ancestor?
    for (let p = el.parentElement; p && p !== document.body; p = p.parentElement) {
      const ps = getComputedStyle(p);
      if (/(auto|scroll|hidden)/.test(ps.overflowY)) {
        const pr = p.getBoundingClientRect();
        if (r.bottom < pr.top + 2 || r.top > pr.bottom - 2) return false;
      }
    }
    return true;
  };
  document.querySelectorAll("[data-pt]").forEach((e) => e.removeAttribute("data-pt"));
  const sel = "button, a[href], input, select, textarea, summary, [role=button], [contenteditable=true]";
  const controls = [];
  let n = 0;
  for (const el of root.querySelectorAll(sel)) {
    if (!visible(el) || (modal == null && el.closest("dialog:not([open])"))) continue;
    n += 1;
    el.setAttribute("data-pt", String(n));
    const tag = el.tagName.toLowerCase();
    const type = (el.getAttribute("type") || "").toLowerCase();
    const kind = tag === "a" ? "link" : tag === "summary" ? "expander" : tag === "select" ? "dropdown"
      : tag === "textarea" ? "text box" : tag === "input" ? (type === "checkbox" ? "checkbox" : type === "range" ? "slider" : type === "file" ? "file" : `field(${type || "text"})`) : "button";
    let label = (el.getAttribute("aria-label") || "").trim();
    if (!label && tag === "input" && el.labels && el.labels[0]) label = el.labels[0].innerText.trim();
    if (!label) label = (el.innerText || "").trim();
    if (!label) label = el.getAttribute("placeholder") || el.getAttribute("title") || el.getAttribute("name") || "";
    if (!label && (kind.startsWith("field") || kind === "text box")) {
      const prev = el.closest(".field")?.querySelector("span, label");
      if (prev) label = prev.innerText.trim();
    }
    const c = { n, kind, label: label.replace(/\s+/g, " ").slice(0, 90) };
    if (tag === "select") { c.value = el.options[el.selectedIndex]?.text; c.options = [...el.options].map((o) => o.text); }
    else if (type === "checkbox") c.checked = el.checked;
    else if ("value" in el && tag !== "button" && type !== "range") c.value = String(el.value || "").slice(0, 60);
    else if (type === "range") c.value = el.value + ` (${el.min}-${el.max})`;
    if (tag === "summary") c.open = !!el.parentElement?.open;
    if (el.disabled) c.disabled = true;
    controls.push(c);
  }
  // Visible text, in reading order, only what is inside the window.
  const lines = [];
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  let node, last = "";
  while ((node = walker.nextNode())) {
    const t = node.textContent.replace(/\s+/g, " ").trim();
    if (!t || !node.parentElement || !visible(node.parentElement)) continue;
    if (node.parentElement.closest("script,style,select,option")) continue;
    if (t === last) continue;
    lines.push(t); last = t;
  }
  let scroll = "";
  const sc = modal ? modal.querySelector(".body") || modal : document.scrollingElement;
  if (sc && sc.scrollHeight > sc.clientHeight + 4) {
    const above = sc.scrollTop > 4, below = sc.scrollTop + sc.clientHeight < sc.scrollHeight - 4;
    scroll = `${above ? "more above" : ""}${above && below ? ", " : ""}${below ? "more below (scroll down)" : ""}`;
  }
  const toasts = (window.__ptToasts || []).splice(0);
  return { where: modal ? `a window is open on top: "${(modal.querySelector("header")?.innerText || modal.id || "").trim().split("\n")[0]}"` : "main screen",
           scroll, text: lines.join(" | ").slice(0, 5000), controls, toasts };
};

async function see() {
  const s = await page.evaluate(SEE);
  const st = await (await fetch(`${base}/control/state`)).json();
  if (st.dialog) s.file_picker = { open: true, looking_for: st.dialog.types, multiple: st.dialog.multiple, files_on_pc: st.dialog.files };
  if (st.opened?.length) s.browser_tabs_opened = st.opened;
  s.errors = (page.__errs || []).splice(0);
  return s;
}

async function el(n) {
  const loc = page.locator(`[data-pt="${n}"]`);
  if (!(await loc.count()) && !(await page.locator("[data-pt]").count())) await page.evaluate(SEE);  // never looked yet
  if (!(await loc.count())) throw new Error(`no control #${n} on screen (look again with /see)`);
  return loc.first();
}

async function act(pathname, q) {
  const t0 = Date.now();
  const SIG = () => {
    const modal = [...document.querySelectorAll("dialog[open]")].pop();
    const root = modal || document.body;
    const vals = [...root.querySelectorAll("input,select,textarea,details")].map((e) => e.value ?? String(e.open)).join("|");
    return (modal ? "M:" : "B:") + root.innerText.length + ":" + root.innerText.slice(0, 4000) + vals;
  };
  const sig0 = await page.evaluate(SIG).catch(() => "");
  let label = "";
  if (q.get("n")) label = await page.locator(`[data-pt="${q.get("n")}"]`).first().innerText({ timeout: 500 }).catch(() => "");
  let note = "";
  if (pathname === "/click") await (await el(q.get("n"))).click({ timeout: 4000 });
  else if (pathname === "/type") await (await el(q.get("n"))).fill(q.get("text") || "", { timeout: 4000 });
  else if (pathname === "/press") await page.keyboard.press(q.get("key"));
  else if (pathname === "/hover") {
    const e = await el(q.get("n"));
    await e.hover({ timeout: 4000 });
    note = "tooltip: " + ((await e.getAttribute("title")) || "(none)");
  }
  else if (pathname === "/check") await (await el(q.get("n"))).click({ timeout: 4000 });
  else if (pathname === "/select") {
    const e = await el(q.get("n"));
    await e.selectOption({ label: q.get("option") }).catch(async () => e.selectOption(q.get("option")));
  } else if (pathname === "/scroll") {
    const dy = Number(q.get("dy") || 500);
    await page.evaluate((dy) => {
      const modal = [...document.querySelectorAll("dialog[open]")].pop();
      const sc = modal ? modal.querySelector(".body") || modal : document.scrollingElement;
      sc.scrollBy(0, dy);
    }, dy);
  } else if (pathname === "/wait") await page.waitForTimeout(Math.min(Number(q.get("ms") || 1000), 20000));
  else if (pathname === "/pick") {
    const files = (q.get("files") || "").split("|").filter(Boolean);
    await fetch(`${base}/control/pick`, { method: "POST", body: JSON.stringify({ files }) });
    note = files.length ? `picked ${files.length}` : "cancelled picker";
  } else return null;
  await page.waitForTimeout(450);
  const changed = (await page.evaluate(SIG).catch(() => "")) !== sig0
    || (await page.evaluate(() => (window.__ptToasts || []).length).catch(() => 0)) > 0;
  const rec = { t: new Date().toISOString(), action: pathname.slice(1), args: Object.fromEntries(q), target: label.slice(0, 60),
                ms: Date.now() - t0, screen_changed: changed, note };
  const recent = actions.filter((a) => a.action === "click" && a.target === rec.target && Date.now() - Date.parse(a.t) < 4000);
  if (pathname === "/click" && recent.length >= 2) rec.rage_click = true;
  if (pathname === "/click" && !changed) rec.dead_click = true;
  actions.push(rec);
  const s = await see();
  if (rec.dead_click) s.note = "Nothing on screen changed after that click.";
  if (pathname === "/hover") s.note = note;
  return s;
}

(async () => {
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 800 }, permissions: ["clipboard-read", "clipboard-write"] });
  page = await ctx.newPage();
  page.__errs = [];
  page.on("pageerror", (e) => page.__errs.push(String(e).slice(0, 200)));
  page.on("console", (m) => { if (m.type() === "error") page.__errs.push(m.text().slice(0, 200)); });
  await page.addInitScript(() => {
    window.__ptToasts = [];
    window.__ptMut = 0;
    new MutationObserver((muts) => {
      window.__ptMut += muts.length;
      for (const m of muts) for (const n of m.addedNodes) {
        if (n.nodeType === 1 && (n.classList?.contains("toast") || n.id === "toast")) window.__ptToasts.push(n.innerText.trim());
      }
    }).observe(document, { childList: true, subtree: true, attributes: true, characterData: true });
  });
  await page.goto(base + "/?svg");   // 2D avatar: the 3D one renders at ~1 fps on a CPU-only server and starves the page
  await page.waitForTimeout(4000);
  http.createServer(async (req, res) => {
    const q = new URL(req.url, "http://x");
    let out;
    try {
      if (q.pathname === "/see") out = await see();
      else if (q.pathname === "/shot") {
        shots += 1;
        const p = path.join(outDir, `shot-${String(shots).padStart(3, "0")}.png`);
        await page.screenshot({ path: p });
        out = { path: p };
      } else if (q.pathname === "/log") out = actions;
      else out = (await act(q.pathname, q.searchParams)) ?? { error: "unknown command" };
    } catch (e) {
      out = { error: String(e.message || e).split("\n")[0] };
      actions.push({ t: new Date().toISOString(), action: q.pathname.slice(1), args: Object.fromEntries(q.searchParams), error: out.error });
    }
    res.setHeader("content-type", "application/json");
    res.end(JSON.stringify(out, null, 1));
  }).listen(driverPort, "127.0.0.1", () => console.log(`driver on http://127.0.0.1:${driverPort}`));
})();
