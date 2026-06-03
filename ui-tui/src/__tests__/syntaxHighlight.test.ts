/**
 * Tokenizer tests for syntax highlighting. The most important property
 * is round-trip integrity: concatenating every token's text must equal
 * the input line exactly — highlighting may never drop, duplicate, or
 * reorder a single character.
 */

import { expect, test, describe } from "bun:test";

import { tokenizeCode } from "../stream/syntaxHighlight.js";

function kinds(line: string): string[] {
  return tokenizeCode(line).map((t) => t.kind);
}
function textOf(line: string, kind: string): string[] {
  return tokenizeCode(line).filter((t) => t.kind === kind).map((t) => t.text);
}

describe("tokenizeCode — round-trip integrity", () => {
  const samples = [
    'def foo(x): return x + 1  # comment',
    'const y = "a string"; // trailing',
    "let z = `template ${x}`",
    "func main() { fmt.Println(42) }",
    "fn add(a: i32) -> i32 { a + 1 }",
    "echo $HOME && ls -la # list",
    "x='it\\'s escaped'",
    "",
    "   ",
    "no_special_tokens_here",
  ];
  for (const s of samples) {
    test(`reconstructs: ${JSON.stringify(s)}`, () => {
      const joined = tokenizeCode(s).map((t) => t.text).join("");
      expect(joined).toBe(s);
    });
  }
});

describe("tokenizeCode — classification", () => {
  test("keywords, function calls, numbers", () => {
    const toks = tokenizeCode("def foo(): return 1");
    expect(textOf("def foo(): return 1", "keyword")).toContain("def");
    expect(textOf("def foo(): return 1", "keyword")).toContain("return");
    expect(textOf("def foo(): return 1", "function")).toContain("foo");
    expect(textOf("def foo(): return 1", "number")).toContain("1");
    void toks;
  });

  test("double/single/backtick strings", () => {
    expect(textOf('a = "hi"', "string")).toContain('"hi"');
    expect(textOf("a = 'hi'", "string")).toContain("'hi'");
    expect(textOf("a = `hi`", "string")).toContain("`hi`");
  });

  test("# and // comments run to end of line", () => {
    expect(textOf("x = 1  # note here", "comment")).toContain("# note here");
    expect(textOf("foo() // c style", "comment")).toContain("// c style");
  });

  test("digit inside an identifier is not a number token", () => {
    expect(kinds("utf8")).not.toContain("number");
    expect(tokenizeCode("utf8")).toEqual([{ kind: "plain", text: "utf8" }]);
  });

  test("an unterminated quote does not gobble the line", () => {
    // No closing quote → STRING_RE fails → falls through to plain.
    expect(kinds('a = "oops')).not.toContain("string");
    expect(tokenizeCode('a = "oops').map((t) => t.text).join("")).toBe('a = "oops');
  });

  test("keyword wins over function even before a paren", () => {
    const toks = tokenizeCode("if(x)");
    expect(toks[0]).toEqual({ kind: "keyword", text: "if" });
  });
});
