import { describe, expect, it } from "vitest";
import { removedText } from "../src/coursedrop";

// The "Removed … Undo" line after a class is dropped (made-up class name).
describe("removedText", () => {
  it("names the class and counts both kinds, with plurals", () => {
    expect(removedText({ name: "MKTG 777", assignments: 6, todos: [1, 2] })).toBe("Removed 6 MKTG 777 assignments and 2 to-dos");
    expect(removedText({ name: "MKTG 777", assignments: 1, todos: [1] })).toBe("Removed 1 MKTG 777 assignment and 1 to-do");
    expect(removedText({ name: "MKTG 777", assignments: 0, todos: [] })).toBe("Removed 0 MKTG 777 assignments and 0 to-dos");
  });
});
