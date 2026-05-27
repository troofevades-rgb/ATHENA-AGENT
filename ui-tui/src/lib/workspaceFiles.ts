/**
 * Workspace file enumeration for @-mention completion.
 *
 * Walks a directory tree once, caches the result, and returns
 * relative paths matching a query. Excludes common big/noisy
 * directories (.git, node_modules, dist, __pycache__) so the
 * list stays scannable.
 *
 * This is NOT a full gitignore parser — it's a pragmatic short
 * list that covers the 95% case. Projects with custom ignored
 * paths can be addressed later if it becomes a problem.
 */

import * as fs from "node:fs";
import * as path from "node:path";


/** Directories whose contents should be skipped during the walk. */
const EXCLUDED_DIRS = new Set<string>([
  ".git", "node_modules", "__pycache__", "dist", "build",
  ".next", ".nuxt", ".cache", ".pytest_cache", ".mypy_cache",
  ".ruff_cache", ".venv", "venv", "env", ".tox",
  "target", "out", ".idea", ".vscode",
  // Common output / artifact dirs in this repo
  "ui-tui/dist", "athena/_tui_bundle",
]);

/** File extensions we consider "noise" for @-mention (binary
 * artifacts mostly). */
const EXCLUDED_EXTS = new Set<string>([
  ".pyc", ".pyo", ".so", ".dll", ".exe", ".o", ".a",
  ".class", ".jar",
  ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".webp",
  ".mp3", ".mp4", ".mov", ".avi", ".wav",
  ".zip", ".tar", ".gz", ".bz2", ".7z",
  ".lock",
]);

/** Hard cap so a giant repo (or a /tmp/ shaped workspace) can't
 * lock the UI walking millions of files. */
const MAX_FILES = 5000;
const MAX_DEPTH = 8;


interface FileCache {
  root: string;
  files: string[];  // relative POSIX paths
  builtAtMs: number;
}

let cache: FileCache | null = null;


/** Build (or return cached) list of workspace files relative to
 * ``root``. Cache invalidates if the root changes or 60s passes. */
function ensureCache(root: string): string[] {
  const now = Date.now();
  if (cache && cache.root === root && now - cache.builtAtMs < 60_000) {
    return cache.files;
  }
  const files: string[] = [];
  const walk = (dir: string, depth: number): void => {
    if (files.length >= MAX_FILES) return;
    if (depth > MAX_DEPTH) return;
    let entries: fs.Dirent[];
    try {
      entries = fs.readdirSync(dir, { withFileTypes: true });
    } catch {
      return;  // permission denied, vanished, etc.
    }
    for (const ent of entries) {
      if (files.length >= MAX_FILES) return;
      const name = ent.name;
      if (name.startsWith(".") && name !== ".env" && name !== ".github") {
        // Skip dotfiles; keep a couple obviously useful ones
        if (EXCLUDED_DIRS.has(name)) continue;
        if (ent.isDirectory()) continue;
      }
      const full = path.join(dir, name);
      if (ent.isDirectory()) {
        if (EXCLUDED_DIRS.has(name)) continue;
        walk(full, depth + 1);
      } else if (ent.isFile()) {
        const ext = path.extname(name).toLowerCase();
        if (EXCLUDED_EXTS.has(ext)) continue;
        const rel = path.relative(root, full).split(path.sep).join("/");
        files.push(rel);
      }
    }
  };
  walk(root, 0);
  files.sort();
  cache = { root, files, builtAtMs: now };
  return files;
}


/** Invalidate the cache (for tests, or if the user just ran a
 * command that likely changed the tree). */
export function invalidateWorkspaceFileCache(): void {
  cache = null;
}


/** Return up to ``limit`` files matching ``query`` (case-insensitive
 * substring). Empty query returns the first ``limit`` files.
 *
 * Ranking: files whose BASENAME starts with the query come first
 * (most relevant), then basename contains, then path contains. */
export function matchWorkspaceFiles(
  root: string,
  query: string,
  limit = 10,
): string[] {
  let all: string[];
  try {
    all = ensureCache(root);
  } catch {
    return [];
  }
  if (!query) return all.slice(0, limit);
  const q = query.toLowerCase();
  const basenameStarts: string[] = [];
  const basenameContains: string[] = [];
  const pathContains: string[] = [];
  for (const f of all) {
    const lower = f.toLowerCase();
    const base = lower.split("/").pop() ?? lower;
    if (base.startsWith(q)) basenameStarts.push(f);
    else if (base.includes(q)) basenameContains.push(f);
    else if (lower.includes(q)) pathContains.push(f);
    if (
      basenameStarts.length + basenameContains.length + pathContains.length
      >= limit * 3
    ) break;
  }
  const merged = [...basenameStarts, ...basenameContains, ...pathContains];
  return merged.slice(0, limit);
}


/** Parse the editor buffer to find an in-progress @-mention.
 *
 * Returns ``{ start, query }`` where ``start`` is the index of the
 * ``@`` in ``text`` and ``query`` is the text typed after it. The
 * mention is "active" if the cursor is on a contiguous run of
 * non-whitespace chars that begins with ``@`` at either the start
 * of the buffer or after whitespace (so ``user@example`` doesn't
 * trigger). Returns ``null`` if no active mention.
 */
export function findActiveAtMention(
  text: string, cursorPos: number,
): { start: number; query: string } | null {
  let i = cursorPos - 1;
  while (i >= 0) {
    const ch = text[i];
    if (ch === "@") {
      if (i === 0 || /\s/.test(text[i - 1])) {
        return { start: i, query: text.slice(i + 1, cursorPos) };
      }
      return null;
    }
    if (/\s/.test(ch)) return null;
    i--;
  }
  return null;
}


/** Build the buffer-replacement string when the user accepts a
 * file completion. Returns the new buffer + new cursor position. */
export function applyAtMentionCompletion(
  text: string, cursorPos: number, pickedPath: string,
): { text: string; cursor: number } {
  const mention = findActiveAtMention(text, cursorPos);
  if (mention === null) return { text, cursor: cursorPos };
  // Replace from the @ up to the cursor with "@<path> " (trailing
  // space so the user can keep typing).
  const before = text.slice(0, mention.start);
  const after = text.slice(cursorPos);
  const replacement = "@" + pickedPath + " ";
  const newText = before + replacement + after;
  const newCursor = before.length + replacement.length;
  return { text: newText, cursor: newCursor };
}
