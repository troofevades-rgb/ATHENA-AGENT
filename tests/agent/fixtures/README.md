# Agent test fixtures

JSONL files representing scripted provider stream sequences. One
file = one or more scenarios. Each line is a JSON object with `kind`
and `payload` fields matching `athena.providers.base.StreamChunk`.

## Stream chunk kinds

| `kind`       | `payload` shape                                                          |
|--------------|--------------------------------------------------------------------------|
| `content`    | `str` — the text the model is streaming                                   |
| `tool_call`  | `{"id": str, "name": str, "arguments": dict}` — one resolved call          |
| `usage`      | `{"prompt_tokens": int, "completion_tokens": int}` (or Ollama-shape keys)   |
| `end`        | `null` or `{"reason": str}` — terminates the stream                        |

## Multi-scenario files

A line may include `"scenario": N` to group chunks into separate
streaming calls. Useful for multi-turn scripts where the loop calls
`stream_chat` multiple times:

```jsonl
{"scenario": 0, "kind": "tool_call", "payload": {"id": "c1", "name": "Read", "arguments": {"file_path": "x"}}}
{"scenario": 0, "kind": "end", "payload": null}
{"scenario": 1, "kind": "content", "payload": "Done."}
{"scenario": 1, "kind": "end", "payload": null}
```

The `scenario` key is consumed by `FakeProvider.from_fixture`; it
doesn't reach the StreamChunk constructor.

## Convention

- One file per failure mode, named after the scenario it represents.
- Tests load fixtures via `FakeProvider.from_fixture(path)` for shared
  scenarios, or call `fake_provider.add_scenario([...])` inline for
  one-off scripts.
- New fixture? Document the scenario in 1–2 lines at the top of the
  file as a comment (`// ...` lines are skipped by the loader).
