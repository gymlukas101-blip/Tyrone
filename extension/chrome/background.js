// Monkey for Chrome — background service worker.
//
// Bridges the tabs YOU share with Monkey (the desktop app on this PC) to Monkey's browser automation, through
// chrome.debugger. Design (adapted from Playwright's extension bridge, Apache-2.0):
//   * Only shared tabs are touched. You share a tab from the toolbar popup; a tab that a shared tab opens (a Duo
//     sign-in, a course pop-up) is shared too. "Stop sharing", closing the tab, or Chrome's "Cancel" on the
//     debugging bar ends it.
//   * Monkey is reached only at ws://127.0.0.1:<port>, and only after both sides prove they hold the pairing code
//     (HMAC challenge-response both ways), so another program can't pose as Monkey and take over your browser.
//   * Browser-wide changes and cookie reads are refused here, whatever Monkey asks.

const DEFAULT_PORT = 47615;
const BLOCKED = new Set([
  // change the whole browser, not the shared tab
  "Storage.setCookies", "Storage.clearCookies", "Network.clearBrowserCookies", "Network.clearBrowserCache",
  "Browser.grantPermissions", "Browser.resetPermissions", "Browser.setPermission", "Browser.close", "Browser.crash",
  "Target.attachToTarget", "Target.activateTarget", "Target.createBrowserContext", "Target.disposeBrowserContext",
  // read your cookies / saved data
  "Storage.getCookies", "Network.getAllCookies", "Network.getCookies", "Network.setCookies", "Network.setCookie",
  "Network.deleteCookies",
]);

const state = { ws: null, ready: false, shared: new Set(), attached: new Set(), status: "not paired", lastError: "" };

// ---------------------------------------------------------------------------------------------- storage
async function settings() {
  const s = await chrome.storage.local.get(["token", "port"]);
  return { token: s.token || "", port: s.port || DEFAULT_PORT };
}
async function loadShared() {
  const s = await chrome.storage.session.get(["shared"]);
  state.shared = new Set(s.shared || []);
}
async function saveShared() {
  await chrome.storage.session.set({ shared: [...state.shared] });
}

/** "MONKEY-47615-abcd…" → {port, token} */
export function parsePairing(code) {
  const m = String(code || "").trim().match(/^MONKEY-(\d{2,5})-([A-Za-z0-9_-]{24,})$/);
  return m ? { port: Number(m[1]), token: m[2] } : null;
}

// ---------------------------------------------------------------------------------------------- crypto
async function hmac(token, msg) {
  const key = await crypto.subtle.importKey("raw", new TextEncoder().encode(token), { name: "HMAC", hash: "SHA-256" },
    false, ["sign"]);
  const sig = await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(msg));
  return [...new Uint8Array(sig)].map((b) => b.toString(16).padStart(2, "0")).join("");
}
function nonce() {
  return [...crypto.getRandomValues(new Uint8Array(16))].map((b) => b.toString(16).padStart(2, "0")).join("");
}

// ---------------------------------------------------------------------------------------------- connection
let connecting = false;
async function connect() {
  if (state.ws || connecting) return;
  const { token, port } = await settings();
  if (!token) { state.status = "not paired"; return; }
  await loadShared();
  if (!state.shared.size) { state.status = "paired, no tab shared"; return; }
  connecting = true;
  let ws;
  try {
    ws = new WebSocket(`ws://127.0.0.1:${port}/extension`);
  } catch (e) {
    connecting = false; state.status = "Monkey isn't running"; return;
  }
  const myNonce = nonce();
  let authed = false;
  ws.onopen = () => { state.status = "connecting…"; };
  ws.onerror = () => { state.lastError = "Monkey isn't running (or the port is wrong)"; };
  ws.onclose = () => {
    connecting = false;
    state.ws = null; state.ready = false;
    state.status = authed ? "Monkey disconnected" : (state.lastError || "Monkey isn't running");
    detachAll();
  };
  ws.onmessage = async (ev) => {
    let msg;
    try { msg = JSON.parse(ev.data); } catch { ws.close(); return; }
    if (!authed) {
      if (msg.type === "hello") {
        ws.send(JSON.stringify({ type: "auth", proof: await hmac(token, "ext|" + msg.nonce), nonce: myNonce, version: 1 }));
      } else if (msg.type === "auth_ok" && msg.proof === await hmac(token, "srv|" + myNonce)) {
        authed = true; connecting = false; state.ws = ws; state.ready = true; state.status = "connected";
        state.lastError = "";
        for (const tabId of [...state.shared]) {
          const tab = await chrome.tabs.get(tabId).catch(() => null);
          if (tab && debuggable(tab.url)) send("chrome.tabs.onCreated", [tab]);
          else state.shared.delete(tabId);
        }
        await saveShared();
        send("extension.initialized", []);
      } else {
        state.lastError = msg.type === "auth_failed" ? "The pairing code doesn't match Monkey's. Paste it again."
          : "That isn't Monkey answering: not connected.";
        ws.close();
      }
      return;
    }
    if (msg.type === "ping") { ws.send(JSON.stringify({ type: "pong" })); return; }
    if (msg.id !== undefined && msg.method) {
      try {
        const result = await handle(msg.method, msg.params || []);
        ws.send(JSON.stringify({ id: msg.id, result: result === undefined ? null : result }));
      } catch (e) {
        ws.send(JSON.stringify({ id: msg.id, error: String(e && e.message || e) }));
      }
    }
  };
}

function send(method, params) {
  if (state.ws && state.ready) state.ws.send(JSON.stringify({ method, params }));
}

function debuggable(url) {
  return !!url && !/^(chrome|edge|devtools|chrome-extension|about:devtools):/i.test(url);
}

// ---------------------------------------------------------------------------------------------- commands
function owned(target) {
  const tabId = target && target.tabId;
  if (tabId === undefined || !state.shared.has(tabId)) throw new Error(`Tab ${tabId} isn't shared with Monkey`);
  return tabId;
}

async function handle(method, params) {
  switch (method) {
    case "chrome.debugger.attach": {
      const tabId = owned(params[0]);
      try {
        await chrome.debugger.attach({ tabId }, params[1] || "1.3");
      } catch (e) {
        if (!/already attached/i.test(String(e))) throw e;
        await chrome.debugger.detach({ tabId }).catch(() => {});
        await chrome.debugger.attach({ tabId }, params[1] || "1.3");
      }
      state.attached.add(tabId);
      badge(tabId, true);
      return null;
    }
    case "chrome.debugger.detach": {
      const tabId = owned(params[0]);
      state.attached.delete(tabId);
      await chrome.debugger.detach({ tabId }).catch(() => {});
      return null;
    }
    case "chrome.debugger.sendCommand": {
      const [target, cdpMethod, cdpParams] = params;
      const tabId = owned(target);
      if (BLOCKED.has(cdpMethod)) throw new Error(`${cdpMethod} isn't allowed by Monkey for Chrome`);
      const debuggee = target.sessionId ? { tabId, sessionId: target.sessionId } : { tabId };
      return await chrome.debugger.sendCommand(debuggee, cdpMethod, cdpParams);
    }
    case "chrome.tabs.create": {
      // Monkey asked for a new tab (e.g. a link that must open in its own tab): it belongs to the shared set.
      const [{ url }] = params;
      const tab = await chrome.tabs.create({ url: url || "about:blank", active: true });
      state.shared.add(tab.id); await saveShared();
      return tab;
    }
    case "chrome.tabs.remove": {
      const ids = [params[0]].flat();
      ids.forEach((id) => owned({ tabId: id }));
      await chrome.tabs.remove(ids);
      return null;
    }
  }
  throw new Error(`Unknown method: ${method}`);
}

// ---------------------------------------------------------------------------------------------- tab events
chrome.tabs.onCreated.addListener(async (tab) => {
  if (tab.openerTabId !== undefined && state.shared.has(tab.openerTabId)) {
    state.shared.add(tab.id); await saveShared();            // a pop-up from a shared tab (Duo, a module window)
    if (state.ready) send("chrome.tabs.onCreated", [tab]);
  }
});
chrome.tabs.onRemoved.addListener(async (tabId, info) => {
  if (!state.shared.has(tabId)) return;
  state.shared.delete(tabId); state.attached.delete(tabId); await saveShared();
  send("chrome.tabs.onRemoved", [tabId, info]);
});
chrome.debugger.onEvent.addListener((source, method, params) => {
  if (source.tabId !== undefined && state.shared.has(source.tabId)) send("chrome.debugger.onEvent", [source, method, params]);
});
chrome.debugger.onDetach.addListener(async (source, reason) => {
  if (source.tabId === undefined || !state.shared.has(source.tabId)) return;
  state.attached.delete(source.tabId);
  badge(source.tabId, false);
  send("chrome.debugger.onDetach", [{ tabId: source.tabId }, reason]);
  if (reason === "canceled_by_user") {                          // you pressed Cancel on Chrome's debugging bar
    state.shared.clear(); await saveShared();
    if (state.ws) state.ws.close(1000, "The user stopped sharing");
  }
});

function badge(tabId, on) {
  chrome.action.setBadgeText({ tabId, text: on ? "ON" : "" }).catch(() => {});
  if (on) chrome.action.setBadgeBackgroundColor({ tabId, color: "#F5C518" }).catch(() => {});
}

async function detachAll() {
  for (const tabId of [...state.attached]) {
    await chrome.debugger.detach({ tabId }).catch(() => {});
    badge(tabId, false);
  }
  state.attached.clear();
}

// ---------------------------------------------------------------------------------------------- popup API
async function share(tabId) {
  const tab = await chrome.tabs.get(tabId);
  if (!debuggable(tab.url)) throw new Error("Chrome doesn't let extensions use this kind of page. Open the website first.");
  state.shared.add(tabId); await saveShared();
  if (state.ready) send("chrome.tabs.onCreated", [tab]);
  else await connect();
}
async function unshare(tabId) {
  const ids = tabId === "all" ? [...state.shared] : [tabId];
  for (const id of ids) {
    state.shared.delete(id);
    if (state.attached.has(id)) { state.attached.delete(id); await chrome.debugger.detach({ tabId: id }).catch(() => {}); }
    badge(id, false);
    send("chrome.debugger.onDetach", [{ tabId: id }, "target_closed"]);
  }
  await saveShared();
  if (!state.shared.size && state.ws) state.ws.close(1000, "Nothing shared");
}

chrome.runtime.onMessage.addListener((msg, _sender, reply) => {
  (async () => {
    try {
      if (msg.type === "status") {
        await loadShared();
        const { token, port } = await settings();
        reply({ ok: true, paired: !!token, port, status: state.status, error: state.lastError, connected: state.ready,
                shared: [...state.shared] });
      } else if (msg.type === "pair") {
        const p = parsePairing(msg.code);
        if (!p) { reply({ ok: false, error: "That doesn't look like Monkey's pairing code (MONKEY-…)." }); return; }
        await chrome.storage.local.set({ token: p.token, port: p.port });
        if (state.ws) state.ws.close();
        state.status = "paired"; await connect();
        reply({ ok: true });
      } else if (msg.type === "share") {
        await share(msg.tabId); reply({ ok: true });
      } else if (msg.type === "unshare") {
        await unshare(msg.tabId); reply({ ok: true });
      } else if (msg.type === "unpair") {
        await unshare("all"); await chrome.storage.local.remove(["token"]); state.status = "not paired"; reply({ ok: true });
      }
    } catch (e) {
      reply({ ok: false, error: String(e && e.message || e) });
    }
  })();
  return true;
});

// For tests and the popup: the same actions, callable from the service worker console.
globalThis.monkey = { pair: (code) => chrome.storage.local.set(parsePairing(code) || {}).then(connect), share, unshare,
                      status: () => ({ ...state, ws: !!state.ws, shared: [...state.shared] }) };

// ---------------------------------------------------------------------------------------------- keep trying
chrome.alarms.create("monkey-reconnect", { periodInMinutes: 0.5 });
chrome.alarms.onAlarm.addListener((a) => { if (a.name === "monkey-reconnect") connect(); });
chrome.runtime.onStartup.addListener(connect);
connect();
