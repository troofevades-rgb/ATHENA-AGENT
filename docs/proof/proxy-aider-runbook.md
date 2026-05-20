# Proxy + Aider smoke test runbook

Manual smoke test for `athena proxy` against [Aider](https://aider.chat).
Run on your laptop or VPS once an Anthropic credential is loaded.

## Prereqs

- An Anthropic API key already added: `athena providers add-key anthropic <key>`
- `pipx install --force "athena-coder[proxy]"` (the `proxy` extra pulls
  FastAPI + uvicorn)
- `pip install aider-chat`

## Steps

```bash
# Terminal 1: start the proxy
athena proxy --port 11434 --log-bodies

# Terminal 2: scratch git repo
cd /tmp && rm -rf aider-test && mkdir aider-test && cd aider-test
git init && echo "def foo(): return 1" > main.py
git add . && git commit -m "init"

# Same terminal, run Aider against the proxy
aider \
  --openai-api-base http://localhost:11434/v1 \
  --openai-api-key dummy \
  --model claude-sonnet-4-6 \
  main.py

# In Aider, ask: "Change foo to return 42 instead of 1."
```

## Verify

1. Aider completes the edit; `cat main.py` shows `def foo(): return 42`.
2. `tail -n 5 ~/.athena/proxy.jsonl` shows entries with
   `"client_ua": "Aider/..."` and `"provider_used": "anthropic"`.
3. `ls ~/.athena/proxy_bodies/` has one JSON per request, each
   containing the full request and response payloads.
4. `git diff` shows the intended change.

## When it fails

- Open the latest `proxy_bodies/<id>.json` and read the request that
  was actually sent to Anthropic. If the message shape looks wrong
  (system message in `messages` array, etc.) the translator regressed.
- Look at the response — Anthropic's error bodies are usually clear.
- Re-run with `--no-translate` to bypass athena's translation entirely
  and prove whether the bug is in athena or the upstream.
- File the diff as `docs/proof/proxy-aider-bug-<date>.md` with the
  bodies attached.

## Notes

This proves the round-trip works end-to-end with a real client
issuing real edits. The unit tests in `tests/proxy/` already cover
the translation surface; this runbook is the wedge-validating
integration test.
