# Proxy + alternate client runbook

Beyond Aider, every OpenAI-compatible client should work against
`athena proxy`. Pick one and run the same shape of test as the
Aider runbook. Each section below covers the client-specific
plumbing.

## Cline (VS Code extension)

1. Install Cline from the VS Code marketplace.
2. Cline settings → "API Provider" → "OpenAI Compatible".
3. Base URL: `http://localhost:11434/v1`
4. API Key: any non-empty string (athena proxy ignores it unless
   `proxy_require_auth = true`).
5. Model ID: `claude-sonnet-4-6`
6. Open Cline's chat, point it at a small file, ask for an edit.

## Codex CLI

```bash
codex \
  --provider openai \
  --api-base http://localhost:11434/v1 \
  --api-key dummy \
  --model claude-sonnet-4-6 \
  "explain main.py"
```

## Continue (VS Code extension)

`.continue/config.yaml`:

```yaml
models:
  - title: Athena (Sonnet)
    provider: openai
    model: claude-sonnet-4-6
    apiBase: http://localhost:11434/v1
    apiKey: dummy
```

## OpenAI Python SDK (smoke check from a notebook)

```python
from openai import OpenAI
client = OpenAI(base_url="http://localhost:11434/v1", api_key="dummy")
resp = client.chat.completions.create(
    model="claude-sonnet-4-6",
    messages=[{"role": "user", "content": "hi"}],
)
print(resp.choices[0].message.content)
```

## Verify

Same as the Aider runbook:

1. The client receives a sensible response.
2. `~/.athena/proxy.jsonl` records the call with the client's
   User-Agent and the resolved provider.
3. (Optional) `~/.athena/proxy_bodies/` has the full payloads when
   `--log-bodies` was passed.

## Record what you ran

After a successful session, save a short note as
`docs/proof/proxy-<client>-session.md`:

```markdown
# Proxy + <client> session — <date>

Did: started athena proxy, configured <client>, ran one edit.
Got: <one sentence summary>.

## proxy.jsonl excerpt
<the relevant 1-3 lines>
```

That gives future-you proof the wedge actually works without
re-running every client every time.
