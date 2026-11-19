/* Monkey's animated banana cursor: one self-contained controller (no dependencies).
 *
 * Used in three places with the same code:
 *   1. injected into Monkey's managed browser (a fixed, click-through layer in a closed shadow root), where it follows
 *      the exact viewport coordinates Playwright clicks;
 *   2. the Settings preview and 3. the cursor test page (inside a host element).
 * It is FEEDBACK ONLY: it never clicks, never changes where a click lands, and takes no pointer events.
 *
 * Coordinates are CSS pixels in the host's space (the browser viewport when injected). The hotspot is the pointer
 * tip in SVG units (manifest.json), scaled with the cursor size, so the tip — not the image centre — sits on (x, y).
 */
(function () {
  "use strict";
  if (window.MonkeyBananaCursor) return;

  var INTERACTIVE = { button: 1, link: 1, textbox: 1, checkbox: 1, radio: 1, combobox: 1, menuitem: 1, tab: 1,
    slider: 1, "switch": 1, option: 1, searchbox: 1, spinbutton: 1, treeitem: 1, menuitemcheckbox: 1,
    menuitemradio: 1, listbox: 1, edit: 1, hyperlink: 1 };
  var T = { pressMs: 70, releaseMs: 110, rippleMs: 320, glowInMs: 130, glowOutMs: 170 };

  /** Travel time for a move (shared formula with Python's cursor_events.travel_ms). */
  function travelMs(dist, motion) {
    if (motion === "reduced" || motion === "off") return 0;
    return Math.round(Math.min(260, Math.max(70, 70 + Math.sqrt(dist) * 7)));
  }

  var CSS = [
    ":host{all:initial}",
    ".bc{position:absolute;left:0;top:0;pointer-events:none;will-change:transform;transform:translate3d(-999px,-999px,0);",
    "  z-index:2147483647;opacity:1;transition:opacity .18s ease}",
    ".bc.hidden{opacity:0}",
    ".bc .body{position:absolute;left:0;top:0;transition:transform .12s cubic-bezier(.2,.9,.3,1.3),filter .15s ease}",
    ".bc .body svg{display:block;width:100%;height:100%;overflow:visible}",
    ".bc.hover .body{transform:scale(1.03);filter:brightness(1.05) drop-shadow(var(--cw) 0 0 #ffe24d) drop-shadow(calc(var(--cw) * -1) 0 0 #ffe24d)",
    "  drop-shadow(0 var(--cw) 0 #ffd83a) drop-shadow(0 calc(var(--cw) * -1) 0 #ffe96e) drop-shadow(0 0 calc(var(--gs) * var(--glow)) rgba(255,190,0,calc(.95 * var(--glow))))}",
    ".bc.hover.pulse .body{animation:bcPulse 1.6s ease-in-out infinite}",
    "@keyframes bcPulse{50%{filter:drop-shadow(0 0 1.6px #fff1a8) drop-shadow(0 0 calc(7px * var(--glow)) rgba(255,205,0,calc(.95 * var(--glow))))}}",
    ".bc.press .body{transform:scale(.9,.86);transition:transform " + T.pressMs + "ms ease-out;",
    "  filter:drop-shadow(0 0 1.4px #fff3b0) drop-shadow(0 0 4px rgba(255,214,10,.9))}",
    ".bc.drag .body{transform:rotate(-9deg) scale(.97)}",
    ".bc.paused .body{filter:grayscale(.55) brightness(.8);opacity:.75}",
    ".bc.thinking .body{animation:bcThink 1.4s ease-in-out infinite}",
    "@keyframes bcThink{50%{filter:drop-shadow(0 0 5px rgba(255,170,30,.75))}}",
    ".bc .fx{position:absolute;left:0;top:0;width:0;height:0}",
    ".bc .rip{position:absolute;left:0;top:0;width:var(--r);height:var(--r);margin:calc(var(--r) / -2) 0 0 calc(var(--r) / -2);",
    "  border-radius:50%;border:var(--rw) solid #ffd60a;box-shadow:0 0 8px rgba(255,200,0,.9),inset 0 0 6px rgba(255,214,10,.6);",
    "  animation:bcRip var(--d) cubic-bezier(.2,.7,.3,1) forwards}",
    ".bc .rip.mid{border-width:calc(var(--rw) * .55);animation-delay:35ms;opacity:0}",
    ".bc .arcs{position:absolute;left:0;top:0;width:var(--r);height:var(--r);margin:calc(var(--r) / -2) 0 0 calc(var(--r) / -2);",
    "  animation:bcRip var(--d) cubic-bezier(.2,.7,.3,1) 60ms forwards;opacity:0}",
    ".bc .arcs svg{display:block;width:100%;height:100%;overflow:visible}",
    "@keyframes bcRip{0%{transform:scale(.2);opacity:1}55%{opacity:.95}100%{transform:scale(1);opacity:0}}",
    ".bc .rays{position:absolute;left:var(--rx);top:var(--ry);width:0;height:0}",
    ".bc .rays i{--rw:var(--rayw)}",
    ".bc .rays i{position:absolute;left:0;top:0;width:var(--rw);height:calc(var(--rw) * 2.1);margin-left:calc(var(--rw) / -2);",
    "  background:#ffd60a;box-shadow:0 0 5px rgba(255,200,0,.9);clip-path:polygon(0 0,100% 0,70% 100%,30% 100%);",
    "  transform-origin:50% 100%;opacity:0;animation:bcRay .7s ease-out forwards}",
    "@keyframes bcRay{0%{opacity:0;scale:1 .4}20%{opacity:1;scale:1 1}70%{opacity:1}100%{opacity:0;scale:1 .8}}",
    ".bc .ring{position:absolute;left:var(--bx);top:var(--by);width:var(--bs);height:var(--bs);opacity:0;transition:opacity .2s ease}",
    ".bc.busy .ring{opacity:1}.bc.busy .ring svg{animation:bcSpin 1.1s linear infinite;filter:drop-shadow(0 0 calc(var(--bs) * .06) rgba(255,200,0,.7))}",
    "@keyframes bcSpin{to{transform:rotate(360deg)}}",
    ".bc .badge{position:absolute;left:var(--bx);top:var(--by);min-width:18px;height:18px;padding:0 5px;border-radius:9px;",
    "  font:800 11px/18px 'Segoe UI',system-ui,sans-serif;color:#2a1c00;background:#ffd60a;box-shadow:0 1px 3px rgba(0,0,0,.45);",
    "  border:1.5px solid #4d2b0f;text-align:center;opacity:0;transform:scale(.6);transition:opacity .15s,transform .15s}",
    ".bc .badge.on{opacity:1;transform:scale(1)}",
    ".bc .badge.amber{background:#ff9f1a}.bc .badge.err{background:#ff5a6e;color:#fff}.bc .badge.ok{background:#39d96a}",
    ".bc .spark{position:absolute;width:5px;height:5px;margin:-2.5px;border-radius:50%;background:#fff3a8;",
    "  box-shadow:0 0 5px #ffd60a;animation:bcSpark .5s ease-out forwards}",
    "@keyframes bcSpark{0%{transform:translate(0,0) scale(1);opacity:1}100%{transform:translate(var(--sx),var(--sy)) scale(.3);opacity:0}}",
    ".bc.err .body{animation:bcShake .32s ease}",
    "@keyframes bcShake{25%{translate:-2px 0}75%{translate:2px 0}}",
    ".bc.reduced .body,.bc.reduced .rip,.bc.reduced .rays i,.bc.reduced .ring svg,.bc.reduced .spark{animation:none!important;transition:none!important}",
    ".bc.reduced .rip,.bc.reduced .arcs{display:none}"
  ].join("\n");

  var RING = '<svg viewBox="0 0 40 40" width="100%" height="100%"><g fill="none" stroke-width="5.5" stroke-linecap="butt">' +
    [0, 1, 2, 3, 4, 5].map(function (i) {
      var a0 = (i * 60 + 6) * Math.PI / 180, a1 = (i * 60 + 50) * Math.PI / 180;
      var p = function (a) { return (20 + 15 * Math.cos(a)).toFixed(2) + " " + (20 + 15 * Math.sin(a)).toFixed(2); };
      var al = [1, 0.8, 0.35, 0.28, 0.85, 1][i];
      return '<path stroke="rgba(255,' + (214 + i * 6) + ',' + (40 + i * 18) + ',' + al + ')" d="M' + p(a0) + ' A15 15 0 0 1 ' + p(a1) + '"/>';
    }).join("") + "</g></svg>";

  var ARCS = '<svg viewBox="0 0 40 40"><g fill="none" stroke="rgba(255,206,40,.75)" stroke-width="2.6" stroke-linecap="butt">' +
    [[200, 285], [300, 345], [15, 95], [110, 170]].map(function (a) {
      var p = function (d) { var r = d * Math.PI / 180; return (20 + 18 * Math.cos(r)).toFixed(2) + " " + (20 + 18 * Math.sin(r)).toFixed(2); };
      return '<path d="M' + p(a[0]) + " A18 18 0 0 1 " + p(a[1]) + '"/>';
    }).join("") + "</g></svg>";

  function create(opts) {
    opts = opts || {};
    var vb = opts.viewBox || 128;
    var hot = opts.hotspot || [11.6, 4.2];
    // Base art: an extracted/approved sprite (manifest.sprite) when present, else the vector reconstruction.
    var sprite = opts.sprite && opts.sprite.src ? opts.sprite : null;
    var cfg = { scale: 1, glow: 0.7, motion: "full", clickFx: true, busyFx: true };
    var host = opts.host, layer, root;
    var doc = (host && host.ownerDocument) || document;
    if (!host) {                                 // injected: a fixed, click-through, accessibility-hidden layer
      var el = doc.createElement("monkey-cursor");
      el.setAttribute("aria-hidden", "true");
      el.style.cssText = "position:fixed;inset:0;pointer-events:none;z-index:2147483647;contain:strict;";
      (doc.documentElement || doc.body).appendChild(el);
      layer = el.attachShadow ? el.attachShadow({ mode: "closed" }) : el;
      host = el;
    } else {
      layer = host.attachShadow ? host.attachShadow({ mode: "open" }) : host;
      host.style.pointerEvents = "none";
    }
    var style = doc.createElement("style");
    style.textContent = CSS;
    layer.appendChild(style);
    root = doc.createElement("div");
    root.className = "bc hidden";
    root.innerHTML = '<div class="fx"></div><div class="ring">' + RING + '</div><div class="badge"></div><div class="body">' +
      (sprite ? '<img alt="" draggable="false" style="display:block;width:100%;height:100%" src="' + sprite.src + '">' : (opts.svg || "")) +
      "</div>";
    layer.appendChild(root);
    var body = root.querySelector(".body"), fx = root.querySelector(".fx"), badge = root.querySelector(".badge");

    var dbg = { ripples: 0, lastRipple: null, hovers: 0 };
    var pos = { x: -999, y: -999 }, from = null, to = null, t0 = 0, dur = 0, raf = 0, visible = false;
    var size = 48, hx = 0, hy = 0, now = function () { return (window.performance && performance.now()) || Date.now(); };

    function layout() {
      size = Math.round(48 * cfg.scale);
      var bh = size;
      if (sprite) {                 // the extracted art is taller than wide: 0.82 × size wide keeps it cursor-sized
        var bw = Math.round(size * 0.82);
        bh = Math.round(bw * sprite.height / sprite.width);
        hx = sprite.hotspot[0] * bw / sprite.width; hy = sprite.hotspot[1] * bw / sprite.width;
        body.style.width = bw + "px"; body.style.height = bh + "px";
        body.style.left = -hx + "px"; body.style.top = -hy + "px";
        body.style.transformOrigin = hx + "px " + hy + "px";
      } else { hx = hot[0] * size / vb; hy = hot[1] * size / vb; }
      if (!sprite) {
        body.style.width = size + "px"; body.style.height = bh + "px";
        body.style.left = -hx + "px"; body.style.top = -hy + "px";
        body.style.transformOrigin = hx + "px " + hy + "px";    // squash/tilt around the tip: it never drifts
      }
      root.style.setProperty("--glow", String(cfg.glow));
      var bwPx = sprite ? Math.round(size * 0.82) : size * 0.82;
      root.style.setProperty("--bw", bwPx + "px");
      root.style.setProperty("--cw", Math.max(1, bwPx * 0.034).toFixed(2) + "px");          // hover contour band
      root.style.setProperty("--gs", Math.min(18, Math.max(3, bwPx * 0.09)) + "px");
      root.style.setProperty("--rayw", Math.max(2.5, bwPx * 0.105) + "px");
      // rays fan out from just above the peel hood (reference: ~0.93, 0.40 banana-widths from the tip)
      root.style.setProperty("--rx", (bwPx * 0.80) + "px");
      root.style.setProperty("--ry", (bwPx * 0.33) + "px");
      // busy ring: centre ≈ (0.94, 0.16) bw from the tip, radius ≈ 0.27 bw (reference LOADING / BUSY)
      var bs = Math.round(bwPx * 0.62);
      root.style.setProperty("--bx", (bwPx * 0.94 - bs / 2) + "px");
      root.style.setProperty("--by", (bwPx * 0.16 - bs / 2) + "px");
      root.style.setProperty("--bs", bs + "px");
      root.style.setProperty("--rpx", bwPx + "px");
      var reduced = cfg.motion === "reduced" ||
        (cfg.motion === "auto" && window.matchMedia && matchMedia("(prefers-reduced-motion: reduce)").matches);
      root.classList.toggle("reduced", reduced);
      cfg._reduced = reduced;
    }
    function place(x, y) {
      pos.x = x; pos.y = y;
      root.style.transform = "translate3d(" + x + "px," + y + "px,0)";
    }
    function ease(t) { return t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2; }   // easeInOutCubic
    function tick() {
      raf = 0;
      if (!to) return;
      var t = dur ? Math.min(1, (now() - t0) / dur) : 1;       // time-based: correct at any frame rate
      var e = ease(t);
      place(from.x + (to.x - from.x) * e, from.y + (to.y - from.y) * e);
      if (t < 1) raf = requestAnimationFrame(tick); else to = null;   // no loop while idle
    }
    function show() { if (!visible) { visible = true; root.classList.remove("hidden"); } }
    function setClass(c, on) { root.classList.toggle(c, !!on); }
    function setBadge(text, kind) {
      badge.textContent = text || "";
      badge.className = "badge" + (text ? " on" : "") + (kind ? " " + kind : "");
    }
    function sparks(n) {
      if (cfg._reduced) return;
      for (var i = 0; i < n; i++) {
        var s = doc.createElement("i");
        s.className = "spark";
        var a = (i / n) * Math.PI * 2 + 0.3;
        s.style.setProperty("--sx", Math.round(Math.cos(a) * 16) + "px");
        s.style.setProperty("--sy", Math.round(Math.sin(a) * 16) + "px");
        fx.appendChild(s);
        setTimeout(function (n) { return function () { n.remove(); }; }(s), 560);
      }
    }

    var api = {
      version: 1,
      configure: function (c) { for (var k in c) if (c.hasOwnProperty(k)) cfg[k] = c[k]; layout(); return cfg; },
      /** Move the tip to (x, y). Returns the travel time in ms (0 when jumping). */
      moveTo: function (x, y, o) {
        o = o || {};
        show();
        if (o.from) place(o.from[0], o.from[1]);
        if (pos.x < -900) { place(x, y); return 0; }           // first appearance: no flight across the screen
        var d = Math.hypot(x - pos.x, y - pos.y);
        dur = o.duration != null ? o.duration : travelMs(d, cfg._reduced ? "reduced" : cfg.motion);
        if (!dur || d < 1) { to = null; place(x, y); return 0; }
        from = { x: pos.x, y: pos.y }; to = { x: x, y: y }; t0 = now();
        if (!raf) raf = requestAnimationFrame(tick);
        return dur;
      },
      /** Hover only for genuinely interactive targets (role from the accessibility tree, not looks). */
      hover: function (role) {
        var on = !!(role && INTERACTIVE[String(role).toLowerCase()]);
        if (on && !root.classList.contains("hover") && !cfg._reduced) {
          var rays = doc.createElement("div");
          rays.className = "rays";
          rays.innerHTML = [16, 50, 82].map(function (a, i) {
            return "<i style='transform:rotate(" + a + "deg) translateY(calc(var(--rayw) * -" + (2.3 + (i === 1 ? 0.4 : 0)) +
              "));animation-delay:" + (i * 25) + "ms'></i>"; }).join("");
          root.appendChild(rays);
          setTimeout(function () { rays.remove(); }, 760);
        }
        setClass("hover", on);
        return on;
      },
      /** Press. If the travel animation hasn't arrived (a slow frame, a cut-short wait), snap to the target first:
       *  the press and ripple are never drawn anywhere but where the click lands. */
      press: function () {
        if (to) { place(to.x, to.y); to = null; if (raf) { cancelAnimationFrame(raf); raf = 0; } }
        show(); setClass("press", true); return T.pressMs;
      },
      /** Release + ripple from the hotspot (where the click actually landed). */
      release: function () {
        setClass("press", false);
        var fr = fx.getBoundingClientRect(), hr = host.getBoundingClientRect ? host.getBoundingClientRect() : { left: 0, top: 0 };
        dbg.ripples++;
        dbg.lastRipple = { x: fr.left - hr.left, y: fr.top - hr.top };     // where the ripple is centred
        if (cfg.clickFx && !cfg._reduced) {
          // reference CLICK: thick bright inner ring, a thinner second ring, segmented outer arcs (in bw units)
          var bw = parseFloat(root.style.getPropertyValue("--rpx")) || 40;
          [["rip", 0.8, 0.09], ["rip mid", 1.15, 0.055], ["arcs", 1.6, 0.05]].forEach(function (r) {
            var c = doc.createElement("div");
            c.className = r[0];
            c.style.setProperty("--r", Math.round(r[1] * bw) + "px");
            c.style.setProperty("--rw", Math.max(2, r[2] * bw) + "px");
            c.style.setProperty("--d", (T.rippleMs + (r[0] === "arcs" ? 60 : 0)) + "ms");
            if (r[0] === "arcs") c.innerHTML = ARCS;
            fx.appendChild(c);
            setTimeout(function () { c.remove(); }, T.rippleMs + 160);
          });
        }
        return T.releaseMs;
      },
      dragTo: function (x, y) { setClass("drag", true); return api.moveTo(x, y); },
      endDrag: function () { setClass("drag", false); },
      /** idle | busy | thinking | typing | waiting | paused | blocked | error | success */
      setState: function (s, label) {
        ["busy", "thinking", "paused", "err"].forEach(function (c) { setClass(c, false); });
        setBadge("");
        if (s === "busy") setClass("busy", cfg.busyFx);
        else if (s === "thinking") setClass("thinking", true);
        else if (s === "typing") setBadge("⌨", "");
        else if (s === "waiting") setBadge(label || "✋ your turn", "");
        else if (s === "paused") { setClass("paused", true); setBadge("❚❚", ""); }
        else if (s === "blocked") setBadge("!", "amber");
        else if (s === "error") { setClass("err", true); setBadge("✖", "err"); }
        else if (s === "success") { setBadge("✓", "ok"); sparks(6); setTimeout(function () { setBadge(""); }, 900); }
        if (s !== "idle" && s !== "success") show();
        return s;
      },
      hide: function () { visible = false; root.classList.add("hidden"); setClass("hover", false); api.setState("idle"); },
      /** Where the tip is drawn right now, in host coordinates (for alignment tests). */
      tip: function () {
        var r = body.getBoundingClientRect(), h = (host.getBoundingClientRect ? host.getBoundingClientRect() : { left: 0, top: 0 });
        var sx = r.width / (sprite ? Math.round(size * 0.82) : size), sy = sx;     // includes the hover scale (around the tip, so 0 drift)
        return { x: r.left - h.left + hx * sx, y: r.top - h.top + hy * sy, size: size, visible: visible };
      },
      position: function () { return { x: pos.x, y: pos.y }; },
      debug: function () { return { ripples: dbg.ripples, lastRipple: dbg.lastRipple, fxNodes: fx.childNodes.length,
        classes: root.className, visible: visible, badge: badge.textContent }; },
      timings: T,
    };
    layout();
    return api;
  }

  window.MonkeyBananaCursor = { create: create, travelMs: travelMs, timings: T };
  if (window.__MONKEY_BANANA && window.top === window) {
    var boot = function () {
      if (window.__monkeyCursor) return;
      window.__monkeyCursor = create({ svg: window.__MONKEY_BANANA.svg, hotspot: window.__MONKEY_BANANA.hotspot,
                                       sprite: window.__MONKEY_BANANA.sprite });
      if (window.__MONKEY_BANANA.config) window.__monkeyCursor.configure(window.__MONKEY_BANANA.config);
    };
    if (document.documentElement) boot(); else document.addEventListener("readystatechange", boot, { once: true });
  }
})();
