/**
 * Workspace file enumeration + @-mention parsing.
 *
 * The file walker is exercised against a tmp directory tree so we
 * don't depend on the real repo layout (which would change every
 * time someone adds a file).
 */

import { describe, expect, test, beforeEach, afterEach } from "bun:test";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";

import {
  applyAtMentionCompletion,
  findActiveAtMention,
  invalidateWorkspaceFileCache,
  matchWorkspaceFiles,
} from "../lib/workspaceFiles.js";


let TMP: string;

beforeEach(() => {
  TMP = fs.mkdtempSync(path.join(os.tmpdir(), "atmention-"));
  invalidateWorkspaceFileCache();
});

afterEach(() => {
  try { fs.rmSync(TMP, { recursive: true, force: true }); } catch {}
  invalidateWorkspaceFileCache();
});

function touch(rel: string): void {
  const full = path.join(TMP, rel);
  fs.mkdirSync(path.dirname(full), { recursive: true });
  fs.writeFileSync(full, "");
}


// ---------------------------------------------------------------------------
// findActiveAtMention
// ---------------------------------------------------------------------------


describe("findActiveAtMention", () => {
  test("returns null when no @ in buffer", () => {
    expect(findActiveAtMention("hello world", 5)).toBeNull();
  });

  test("recognizes @ at start of buffer", () => {
    expect(findActiveAtMention("@src", 4)).toEqual({ start: 0, query: "src" });
  });

  test("recognizes @ after whitespace", () => {
    const r = findActiveAtMention("look at @src/foo", 16);
    expect(r).toEqual({ start: 8, query: "src/foo" });
  });

  test("does NOT trigger inside email-like text (user@example)", () => {
    expect(findActiveAtMention("user@example", 12)).toBeNull();
  });

  test("returns null when cursor is past a space after the mention", () => {
    expect(findActiveAtMention("@src done", 9)).toBeNull();
  });

  test("query is empty when cursor is right after @", () => {
    expect(findActiveAtMention("type @", 6)).toEqual({ start: 5, query: "" });
  });

  test("multiline: @ after newline counts as whitespace-preceded", () => {
    expect(findActiveAtMention("line1\n@foo", 10)).toEqual(
      { start: 6, query: "foo" },
    );
  });
});


// ---------------------------------------------------------------------------
// applyAtMentionCompletion
// ---------------------------------------------------------------------------


describe("applyAtMentionCompletion", () => {
  test("replaces partial with full path + trailing space", () => {
    const r = applyAtMentionCompletion("see @src/foo", 12, "src/foo/bar.ts");
    expect(r.text).toBe("see @src/foo/bar.ts ");
    expect(r.cursor).toBe("see @src/foo/bar.ts ".length);
  });

  test("preserves text after the cursor", () => {
    const r = applyAtMentionCompletion("@s here", 2, "src/file.ts");
    expect(r.text).toBe("@src/file.ts  here");
  });

  test("noop when no active mention", () => {
    const r = applyAtMentionCompletion("no at-sign", 5, "src/x.ts");
    expect(r.text).toBe("no at-sign");
    expect(r.cursor).toBe(5);
  });
});


// ---------------------------------------------------------------------------
// matchWorkspaceFiles
// ---------------------------------------------------------------------------


describe("matchWorkspaceFiles", () => {
  test("empty workspace returns empty", () => {
    expect(matchWorkspaceFiles(TMP, "anything")).toEqual([]);
  });

  test("returns matching files by basename prefix", () => {
    touch("alpha.py");
    touch("beta.py");
    touch("nested/gamma.py");
    const r = matchWorkspaceFiles(TMP, "alp");
    expect(r).toEqual(["alpha.py"]);
  });

  test("ranks basename-starts above basename-contains above path-contains", () => {
    touch("foo.py");
    touch("readme_foo.md");
    touch("nested/something/foo_handler.py");
    // Query "foo" should rank "foo.py" first (basename starts)
    const r = matchWorkspaceFiles(TMP, "foo");
    expect(r[0]).toBe("foo.py");
  });

  test("excludes .git directory", () => {
    touch(".git/HEAD");
    touch(".git/config");
    touch("real.py");
    const r = matchWorkspaceFiles(TMP, "");
    expect(r).toEqual(["real.py"]);
  });

  test("excludes node_modules", () => {
    touch("node_modules/foo/index.js");
    touch("src/index.js");
    const r = matchWorkspaceFiles(TMP, "");
    expect(r).toEqual(["src/index.js"]);
  });

  test("excludes __pycache__ and other Python noise", () => {
    touch("__pycache__/foo.cpython-311.pyc");
    touch("athena/__pycache__/bar.cpython-311.pyc");
    touch("athena/real.py");
    const r = matchWorkspaceFiles(TMP, "");
    expect(r).toEqual(["athena/real.py"]);
  });

  test("excludes binary-ish extensions", () => {
    touch("foo.png");
    touch("foo.so");
    touch("foo.lock");
    touch("foo.py");
    const r = matchWorkspaceFiles(TMP, "foo");
    expect(r).toEqual(["foo.py"]);
  });

  test("empty query returns first N files alphabetically", () => {
    touch("zebra.py");
    touch("apple.py");
    touch("mango.py");
    const r = matchWorkspaceFiles(TMP, "", 5);
    expect(r).toEqual(["apple.py", "mango.py", "zebra.py"]);
  });

  test("respects limit", () => {
    touch("a.py");
    touch("aa.py");
    touch("aaa.py");
    touch("aaaa.py");
    const r = matchWorkspaceFiles(TMP, "a", 2);
    expect(r.length).toBe(2);
  });

  test("case-insensitive query", () => {
    touch("MyFile.tsx");
    expect(matchWorkspaceFiles(TMP, "myfile")).toEqual(["MyFile.tsx"]);
    expect(matchWorkspaceFiles(TMP, "MYFILE")).toEqual(["MyFile.tsx"]);
  });

  test("returns posix paths on all platforms", () => {
    touch("nested/inner/file.py");
    const r = matchWorkspaceFiles(TMP, "file");
    expect(r[0]).toBe("nested/inner/file.py");
    expect(r[0].includes("\\")).toBe(false);
  });
});
