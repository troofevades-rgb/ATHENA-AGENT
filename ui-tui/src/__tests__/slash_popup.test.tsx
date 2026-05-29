/**
 * SlashPopup matcher + completion behavior.
 *
 * Pure logic only — the rendered output is exercised by manual
 * walkthrough; here we pin the filter and the completion-text rule.
 */

import { describe, expect, test } from "bun:test";

import {
  completionText, matchSlashCommands, SLASH_COMMANDS,
} from "../components/SlashPopup.js";


describe("matchSlashCommands", () => {
  test("returns empty for non-slash queries", () => {
    expect(matchSlashCommands("")).toEqual([]);
    expect(matchSlashCommands("hello")).toEqual([]);
    expect(matchSlashCommands(" /help")).toEqual([]);
  });

  test("returns ALL commands for bare '/'", () => {
    const all = matchSlashCommands("/", 999);
    expect(all.length).toBe(SLASH_COMMANDS.length);
  });

  test("prefix filter is case-insensitive", () => {
    const lower = matchSlashCommands("/me");
    const upper = matchSlashCommands("/ME");
    expect(lower.length).toBeGreaterThan(0);
    expect(upper).toEqual(lower);
  });

  test("'/me' matches /memory and /models (both 'me'-prefixed?)", () => {
    // Actually only /memory starts with /me; /model also does
    const hits = matchSlashCommands("/me").map((c) => c.name);
    expect(hits).toContain("/memory");
    // /model and /models start with /mod, not /me. So this is the
    // contrast: only /memory should be in this set.
    expect(hits).not.toContain("/model");
    expect(hits).not.toContain("/models");
  });

  test("'/mod' matches /model AND /models in priority order", () => {
    const hits = matchSlashCommands("/mod").map((c) => c.name);
    expect(hits).toContain("/model");
    expect(hits).toContain("/models");
    // The one without 's' should come first (defined earlier — matches
    // the help text order from athena/commands/help.py)
    expect(hits.indexOf("/model")).toBeLessThan(hits.indexOf("/models"));
  });

  test("exact full name still matches itself", () => {
    const hits = matchSlashCommands("/help");
    expect(hits.length).toBeGreaterThan(0);
    expect(hits[0].name).toBe("/help");
  });

  test("nonexistent prefix returns empty", () => {
    expect(matchSlashCommands("/xyznever")).toEqual([]);
  });

  test("respects limit parameter", () => {
    const hits = matchSlashCommands("/", 3);
    expect(hits.length).toBe(3);
  });
});


describe("completionText", () => {
  test("appends trailing space so user can type args immediately", () => {
    const help = SLASH_COMMANDS.find((c) => c.name === "/help");
    if (!help) throw new Error("/help not in catalog");
    expect(completionText(help)).toBe("/help ");
  });
});


describe("SLASH_COMMANDS catalog hygiene", () => {
  test("every name starts with /", () => {
    for (const c of SLASH_COMMANDS) {
      expect(c.name.startsWith("/")).toBe(true);
    }
  });

  test("every name is unique", () => {
    const seen = new Set<string>();
    for (const c of SLASH_COMMANDS) {
      expect(seen.has(c.name)).toBe(false);
      seen.add(c.name);
    }
  });

  test("every description is non-empty", () => {
    for (const c of SLASH_COMMANDS) {
      expect(c.description.length).toBeGreaterThan(0);
    }
  });
});
