import { describe, expect, it } from "vitest";
import { phoneStatusText, qrSvg } from "../src/reminders";

describe("Settings → Reminders helpers", () => {
  it("draws the topic's QR code locally as an SVG", () => {
    const svg = qrSvg("https://ntfy.sh/monkey-demo-not-a-real-topic-0000000000");
    expect(svg.startsWith("<svg")).toBe(true);
    expect(svg).toContain("<path");
    expect(svg).not.toContain("http://www.w3.org/1999/xlink\" href=\"http");   // no image fetched from anywhere
    expect(qrSvg("https://ntfy.sh/a")).not.toEqual(svg);
  });

  it("says quietly how the last phone notification went", () => {
    expect(phoneStatusText(undefined)).toBe("");
    expect(phoneStatusText({ state: "idle", at: null, detail: "" })).toBe("");
    expect(phoneStatusText({ state: "ok", at: 1_800_000_000, detail: "sent" })).toMatch(/^✓ Last phone notification went out at /);
    const bad = phoneStatusText({ state: "failed", at: 1_800_000_000, detail: "the server didn't answer within 5 seconds" });
    expect(bad).toContain("didn't go through");
    expect(bad).toContain("the server didn't answer within 5 seconds");
    expect(bad).toContain("Reminders still show on this PC");
  });
});
