# `tool_call_outputs/` — per-provider tool-call response samples

Real and lightly-synthesized model outputs grouped by provider and model,
used by Phase 9's tool-call parser tests. Different providers and even
different models within a provider emit tool calls in noticeably
different shapes (Anthropic XML, OpenAI function-call JSON, Ollama
native, Qwen's leaked `<tool_call>` tags, harmony's `<function>` tags,
JSON-fenced content, etc.). Each parser in `ocode/providers/parsers/`
is verified against the corpus to lock in robustness.

## Layout

```
tool_call_outputs/
└── <provider>/
    └── <model>/
        ├── normal/                  # Cleanly-formed calls
        ├── content_leakage/         # Calls that leaked into content
        ├── partial_streams/         # Mid-stream interruption shapes
        └── pathological/            # Real cases that broke a parser once
```

Provider names match `ocode/providers/` module names: `ollama`,
`anthropic`, `openai`, `google`, `openai_compat`, `openrouter`, `nous`.
Model names match what the provider returns when asked (e.g.
`claude-sonnet-4-5`, `gpt-4o-2024-08-06`, `qwen2.5-coder-32b-instruct`).

## Sample file shape

Each sample is a single file containing the raw text that came back from
the provider — exactly what the parser will see. Most are `.txt`
(streamed completions concatenated) or `.json` (one-shot responses).
Adjacent `<sample>.expected.json` files document the parser's intended
output for that sample so the parser test is a black-box round-trip:

```
ollama/qwen2.5-coder-32b/normal/
├── single_tool_call.txt
├── single_tool_call.expected.json
├── two_tool_calls.txt
└── two_tool_calls.expected.json
```

## Naming

`<descriptive-slug>.<ext>` for samples; `<descriptive-slug>.expected.json`
for the expected parsed output. Slugs describe what the sample exercises:
`unicode_in_argument.txt`, `nested_object_argument.txt`,
`stream_cut_mid_tag.txt`.

## Adding a new sample

1. Capture the raw provider output (curl `-N` for streaming, save raw
   request body for one-shot).
2. Anonymize per provenance rules below.
3. Place under the correct `<provider>/<model>/<category>/` path.
4. Add the corresponding `.expected.json` describing what the parser
   should produce.
5. Run `pytest tests/providers/parsers/ -v` and confirm the relevant
   parser passes on the new sample.

## Provenance

Samples come from:

- Real model calls captured during development against the provider's
  public API (preferred)
- Hand-crafted to exercise a specific parser branch (label these clearly
  in the slug, e.g. `synthetic_no_closing_tag.txt`)
- Issues reported by users (anonymize and credit in the commit message
  if appropriate)

**Anonymization rules**:

- Strip API keys and tokens that appear in response headers or content
- Replace prompts and user messages that name people, projects, or
  organizations with generic placeholders — the sample exists to test
  the parser, not to preserve the original prompt
- File paths in tool-call arguments → `/path/to/example`
