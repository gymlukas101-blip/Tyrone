import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { dueDate, isOverdue, splitQuick } from "../src/todoparse";

// The same cases the Python parser (monkey/memory/todos.py split_quick) must pass: tests/todo_due_cases.json.
const data = JSON.parse(readFileSync(new URL("../../tests/todo_due_cases.json", import.meta.url), "utf8")) as {
  now: string; cases: { in: string; text: string; due: string | null; priority: string; list: string }[];
};
const [d, t] = data.now.split("T");
const [Y, M, D] = d.split("-").map(Number);
const [hh, mm] = t.split(":").map(Number);
const NOW = new Date(Y, M - 1, D, hh, mm);

describe("quick-add parsing", () => {
  for (const c of data.cases) {
    it(c.in, () => {
      expect(splitQuick(c.in, NOW)).toEqual({ text: c.text, due: c.due, priority: c.priority, list: c.list });
    });
  }
});

describe("due dates", () => {
  it("a day-only item is due at the end of that day", () => {
    expect(dueDate("2026-11-23")!.getHours()).toBe(23);
    expect(isOverdue("2026-11-23", NOW)).toBe(false);
    expect(isOverdue("2026-11-22", NOW)).toBe(true);
    expect(isOverdue("2026-11-23T09:59", NOW)).toBe(true);
    expect(isOverdue(null, NOW)).toBe(false);
    expect(dueDate("not a date")).toBeNull();
  });
});
