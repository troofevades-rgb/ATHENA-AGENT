/**
 * Lightweight, language-agnostic code tokenizer for the TUI.
 *
 * Full grammar-aware highlighting (shiki/prism) means a heavy dep and
 * ANSI strings that fight Ink's own width/wrap accounting. Instead we
 * do a small left-to-right scan that classifies the token kinds that
 * actually read as "highlighted" — keywords, strings, comments,
 * numbers, function calls — and let the renderer map each kind to an
 * Ink <Text color>. Good enough for the code snippets that show up in
 * agent replies across Python / JS / TS / Go / Rust / shell, without a
 * dependency or air-gap concern.
 *
 * Scanning is per-line (the Markdown renderer splits code blocks by
 * line). Block comments / strings that span lines aren't tracked —
 * rare in pasted snippets and not worth the state machine.
 */

export type CodeTokenKind =
  | "keyword"
  | "string"
  | "comment"
  | "number"
  | "function"
  | "plain";

export interface CodeToken {
  kind: CodeTokenKind;
  text: string;
}

// Union of keywords across the languages that show up in agent output.
// A superset is fine — a stray match just tints a word; it never drops
// or reorders text.
const KEYWORDS = new Set([
  // python
  "def", "class", "return", "if", "elif", "else", "for", "while", "import",
  "from", "as", "try", "except", "finally", "with", "lambda", "pass", "break",
  "continue", "raise", "yield", "global", "nonlocal", "assert", "del",
  "in", "is", "not", "and", "or", "None", "True", "False",
  // js / ts
  "const", "let", "var", "function", "async", "await", "new", "typeof",
  "instanceof", "of", "this", "null", "undefined", "true", "false", "export",
  "default", "extends", "implements", "interface", "type", "enum", "public",
  "private", "protected", "static", "readonly", "void", "abstract", "super",
  // go
  "func", "package", "go", "defer", "chan", "map", "range", "select",
  "struct", "switch", "case", "fallthrough", "goto",
  // rust
  "fn", "pub", "impl", "trait", "mut", "match", "use", "mod", "crate",
  "self", "Self", "where", "dyn", "unsafe", "move", "ref",
  // shell-ish / common
  "echo", "then", "fi", "do", "done", "esac", "local", "set", "exit",
]);

const COMMENT_RE = /^(#.*|\/\/.*)/;
// Quoted strings: ", ', or ` with backslash escapes. Each alternative
// requires its closing quote, so an unterminated quote falls through to
// plain (no greedy gobble of the rest of the line).
const STRING_RE = /^("(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*'|`(?:[^`\\]|\\.)*`)/;
const NUMBER_RE = /^\d+(?:\.\d+)?/;
const IDENT_RE = /^[A-Za-z_$][\w$]*/;

/**
 * Tokenize a single line of code. Consecutive plain characters are
 * merged into one token so the renderer emits fewer spans. The
 * concatenation of all token `text` equals the input line exactly.
 */
export function tokenizeCode(line: string): CodeToken[] {
  const tokens: CodeToken[] = [];
  let plain = "";
  const flushPlain = (): void => {
    if (plain) {
      tokens.push({ kind: "plain", text: plain });
      plain = "";
    }
  };

  let i = 0;
  while (i < line.length) {
    const rest = line.slice(i);

    // Comment runs to end of line — consume everything left.
    const c = rest.match(COMMENT_RE);
    if (c) {
      flushPlain();
      tokens.push({ kind: "comment", text: c[0] });
      break;
    }

    const s = rest.match(STRING_RE);
    if (s) {
      flushPlain();
      tokens.push({ kind: "string", text: s[0] });
      i += s[0].length;
      continue;
    }

    // Numbers only at a token boundary (prev char not identifier-ish),
    // so we don't tint the "1" in "utf8".
    const prev = i > 0 ? line[i - 1]! : "";
    if (!/[\w$]/.test(prev)) {
      const n = rest.match(NUMBER_RE);
      if (n) {
        flushPlain();
        tokens.push({ kind: "number", text: n[0] });
        i += n[0].length;
        continue;
      }
    }

    const id = rest.match(IDENT_RE);
    if (id) {
      flushPlain();
      const word = id[0];
      const after = line[i + word.length];
      if (KEYWORDS.has(word)) {
        tokens.push({ kind: "keyword", text: word });
      } else if (after === "(") {
        tokens.push({ kind: "function", text: word });
      } else {
        tokens.push({ kind: "plain", text: word });
      }
      i += word.length;
      continue;
    }

    // Any other single character is plain; accumulate.
    plain += line[i];
    i += 1;
  }
  flushPlain();
  return tokens;
}
