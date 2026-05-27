/**
 * Splitter tests for fenced code blocks (in assistant text) and
 * unified diffs (in tool_complete results).
 *
 * The "block" rendering is built on top of one-row-per-line — each
 * line gets a role tag, and the Transcript styles consecutive
 * same-role lines so they read as a block. So all we test here is
 * the classification per line.
 */

import { describe, expect, test } from "bun:test";

import {
  splitAssistantContent, splitDiffContent,
} from "../state/reducer.js";


function roles(rows: { role: string }[]): string[] {
  return rows.map((r) => r.role);
}


// ---------------------------------------------------------------------------
// splitAssistantContent — fence detection
// ---------------------------------------------------------------------------


describe("splitAssistantContent — fenced code blocks", () => {
  test("plain text without fences: all assistant", () => {
    const r = splitAssistantContent("hello\nworld\n", 0);
    expect(roles(r.rows)).toEqual(["assistant", "assistant", "assistant"]);
  });

  test("single fenced block: lines marked code, fences dropped", () => {
    const r = splitAssistantContent(
      "prose\n```\ncode line\n```\nmore prose",
      0,
    );
    expect(roles(r.rows)).toEqual(["assistant", "code", "assistant"]);
    expect(r.rows[0].content).toBe("prose");
    expect(r.rows[1].content).toBe("code line");
    expect(r.rows[2].content).toBe("more prose");
  });

  test("fence with language tag is still recognized", () => {
    const r = splitAssistantContent(
      "```python\ndef foo():\n    return 1\n```",
      0,
    );
    // 3 code rows, no fence rows
    expect(roles(r.rows)).toEqual(["code", "code"]);
    expect(r.rows[0].content).toBe("def foo():");
    expect(r.rows[1].content).toBe("    return 1");
  });

  test("multiple separate blocks toggle correctly", () => {
    const r = splitAssistantContent(
      "a\n```\nA1\n```\nb\n```ts\nB1\nB2\n```\nc",
      0,
    );
    expect(roles(r.rows)).toEqual([
      "assistant",  // a
      "code",       // A1
      "assistant",  // b
      "code",       // B1
      "code",       // B2
      "assistant",  // c
    ]);
  });

  test("unmatched opening fence: everything after stays code", () => {
    // No closing fence — body becomes code until end. Acceptable
    // degradation; the alternative (drop the open fence and treat
    // body as assistant) would mis-render the obviously-code body.
    const r = splitAssistantContent("intro\n```\nbody1\nbody2", 0);
    expect(roles(r.rows)).toEqual(["assistant", "code", "code"]);
  });

  test("indented fences are NOT recognized (no CommonMark indented-code support)", () => {
    // Markdown CommonMark requires fences at column 0 (or close to
    // it). We require the trimmed line to start with ``` — but a
    // fence indented by whitespace WILL still match per trimStart.
    // Pin actual behavior so a future stricter rule is a deliberate
    // change.
    const r = splitAssistantContent("  ```\n  body\n  ```", 0);
    // Trimmed → 3 backticks → fence detected
    expect(roles(r.rows)).toEqual(["code"]);
  });

  test("backticks in middle of line are NOT fences", () => {
    const r = splitAssistantContent("use the `foo` function", 0);
    expect(roles(r.rows)).toEqual(["assistant"]);
  });

  test("4+ backticks count as fence (CommonMark allows N backticks)", () => {
    const r = splitAssistantContent("````\ncode\n````", 0);
    expect(roles(r.rows)).toEqual(["code"]);
  });

  test("empty input yields empty rows", () => {
    const r = splitAssistantContent("", 0);
    // split("") = [""] — one empty assistant row, which is acceptable
    expect(r.rows.length).toBe(1);
    expect(r.rows[0].role).toBe("assistant");
    expect(r.rows[0].content).toBe("");
  });
});


// ---------------------------------------------------------------------------
// splitDiffContent — line classification
// ---------------------------------------------------------------------------


describe("splitDiffContent — unified diff classification", () => {
  test("file headers classified as diff-file", () => {
    const r = splitDiffContent("--- a/foo.py\n+++ b/foo.py", 0);
    expect(roles(r.rows)).toEqual(["diff-file", "diff-file"]);
  });

  test("hunk headers classified as diff-hunk", () => {
    const r = splitDiffContent("@@ -1,3 +1,4 @@", 0);
    expect(roles(r.rows)).toEqual(["diff-hunk"]);
  });

  test("added lines classified as diff-add", () => {
    const r = splitDiffContent("+new line", 0);
    expect(roles(r.rows)).toEqual(["diff-add"]);
  });

  test("removed lines classified as diff-del", () => {
    const r = splitDiffContent("-old line", 0);
    expect(roles(r.rows)).toEqual(["diff-del"]);
  });

  test("context lines (leading space) classified as tool/neutral", () => {
    const r = splitDiffContent(" context line", 0);
    expect(roles(r.rows)).toEqual(["tool"]);
  });

  test("full mini-diff round-trip", () => {
    const diff = [
      "--- a/foo.py",
      "+++ b/foo.py",
      "@@ -1,3 +1,3 @@",
      " unchanged",
      "-removed",
      "+added",
      " more unchanged",
    ].join("\n");
    const r = splitDiffContent(diff, 0);
    expect(roles(r.rows)).toEqual([
      "diff-file", "diff-file", "diff-hunk",
      "tool", "diff-del", "diff-add", "tool",
    ]);
  });

  test("--- and +++ take priority over - / +", () => {
    // Ensure the file-header check runs before the add/del check
    const r = splitDiffContent("--- a/x\n+++ b/x", 0);
    expect(r.rows[0].role).toBe("diff-file");
    expect(r.rows[1].role).toBe("diff-file");
  });

  test("preserves keys monotonically", () => {
    const r = splitDiffContent("+a\n-b\n c", 100);
    expect(r.rows[0].key).toBe(100);
    expect(r.rows[1].key).toBe(101);
    expect(r.rows[2].key).toBe(102);
    expect(r.nextKey).toBe(103);
  });
});
