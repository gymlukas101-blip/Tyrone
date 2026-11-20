const $ = (id) => document.getElementById(id);
const ask = (msg) => chrome.runtime.sendMessage(msg);

async function draw() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  const s = await ask({ type: "status" });
  $("pairBox").hidden = s.paired;
  $("shareBox").hidden = !s.paired;
  const sharedHere = tab && s.shared.includes(tab.id);
  $("dot").className = "dot" + (s.connected ? " on" : s.paired ? " wait" : "");
  $("status").textContent = !s.paired ? "Not paired with Monkey yet"
    : s.connected ? `Connected to Monkey · ${s.shared.length} tab${s.shared.length === 1 ? "" : "s"} shared`
    : s.shared.length ? (s.error || "Waiting for Monkey (is the app running?)") : "Paired · no tab shared";
  if (tab) $("tabInfo").textContent = sharedHere ? `Monkey can use this tab: ${tab.title ?? ""}` : `This tab: ${tab.title ?? ""}`;
  $("share").hidden = !!sharedHere;
  $("unshare").hidden = !sharedHere;
  $("stopAll").hidden = s.shared.length < 2;
  $("err").textContent = s.connected ? "" : (s.error || "");
}

$("pair").onclick = async () => {
  const r = await ask({ type: "pair", code: $("code").value });
  $("err").textContent = r.ok ? "" : r.error;
  setTimeout(draw, 400);
};
$("share").onclick = async () => {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  const r = await ask({ type: "share", tabId: tab.id });
  $("err").textContent = r.ok ? "" : r.error;
  setTimeout(draw, 600);
};
$("unshare").onclick = async () => {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  await ask({ type: "unshare", tabId: tab.id });
  draw();
};
$("stopAll").onclick = async () => { await ask({ type: "unshare", tabId: "all" }); draw(); };
$("unpair").onclick = async () => { await ask({ type: "unpair" }); draw(); };
draw();
setInterval(draw, 1500);
