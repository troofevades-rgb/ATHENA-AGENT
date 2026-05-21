# Gateway credentials

Every gateway platform (Discord, Slack, Telegram, Signal,
iMessage, Matrix, Email) needs a long-lived secret to run.
Two config shapes are supported:

| Shape | Example | Recommended |
|---|---|---|
| **`<key>_path`** — file on disk at 0o600 | `bot_token_path = "~/.athena/gateway/discord_bot_token.txt"` | ✅ yes |
| **`<key>`** — cleartext in config.toml | `bot_token = "MTUw..."` | deprecated; works but logs a one-shot rotation nudge |

The file-on-disk shape keeps tokens **out of** dotfile
backups, **out of** screen-shared `cat ~/.athena/config.toml`,
and **out of** any tool that picks up dotfiles automatically.

## What changes if I migrate

Nothing in the runtime — same adapter, same SDK, same
behaviour. The resolver reads from the path per call, so
**rotating the token is a single file rewrite; no athena
restart needed**.

## How to migrate (PowerShell — Windows)

```powershell
# Replace <PLATFORM> + <KEY> with your real names
# (e.g. discord + bot_token; slack + bot_token / app_token)
$tok = Read-Host "Paste secret" -AsSecureString
$plain = [System.Net.NetworkCredential]::new("", $tok).Password
$path = "$env:USERPROFILE\.athena\gateway\<PLATFORM>_<KEY>.txt"
New-Item -ItemType Directory -Force -Path (Split-Path $path) | Out-Null
[IO.File]::WriteAllText($path, $plain)
```

Then in `~/.athena/config.toml`:

```toml
[gateway.platforms.<PLATFORM>]
enabled = true
<KEY>_path = "C:/Users/<you>/.athena/gateway/<PLATFORM>_<KEY>.txt"
# remove the old cleartext <KEY> = "..." line
```

## How to migrate (bash — macOS / Linux)

```bash
mkdir -p ~/.athena/gateway
chmod 700 ~/.athena/gateway
read -rs -p "Paste secret: " tok && echo
printf '%s' "$tok" > ~/.athena/gateway/<PLATFORM>_<KEY>.txt
chmod 600 ~/.athena/gateway/<PLATFORM>_<KEY>.txt
```

## Per-platform keys

| Platform | Keys to migrate |
|---|---|
| **discord** | `bot_token` |
| **slack** | `bot_token`, `app_token` |
| **telegram** | `bot_token` |
| **matrix** | `access_token` |
| **imessage** | `password` |
| **email** | `imap_password`, `smtp_password` |
| **signal** | (no token-shaped secret — uses a REST URL) |

Each one gets a corresponding `<key>_path` counterpart.

## What the resolver does

`athena.gateway.credentials.resolve_credential(settings, key, *, platform, required=True)`:

1. **`<key>_path` set** → read the file, strip whitespace,
   return contents. Empty file → falls back to step 2 with a
   warning.
2. **`<key>` set** → return the cleartext + log a one-shot
   deprecation nudge for this `(platform, key)` pair. The
   nudge fires once per process, not once per call, so a
   flapping reconnect doesn't spam the log.
3. **Neither set** → `ValueError` (when `required=True`) with
   a message naming both possible config shapes. `None`
   (when `required=False`) for optional secrets.

The resolver **never logs the secret material**. The DEBUG
line on the success path emits `path=<path> len=<N>` so an
operator can confirm "the file was read" without knowing the
value. The deprecation nudge names the config key and the
migration path — not the value.

## Rotation

`<key>_path` shapes are read **per call**. Rotation steps:

1. Generate a new secret in the platform's developer portal /
   admin UI (revokes the old one in most cases).
2. Rewrite the secret file via the PowerShell or bash recipe
   above.
3. **Optional**: HUP / restart the gateway daemon to force a
   reconnect with the new credential. Most SDKs cache the
   token on the connection; a fresh connect uses the new value.

The cleartext `<key>` shape requires editing config.toml +
restarting the gateway, so the file-on-disk shape is also a
faster-rotation path.

## Test layout

`tests/gateway/test_credentials.py` pins:

- file path returns stripped contents
- file path wins over cleartext when both set
- `~/` expansion to the home directory
- cleartext fallback warns **once** per `(platform, key)`
- different platforms / different keys warn independently
- missing-file or empty-file → falls back to cleartext
  with a warning
- missing both + `required=True` → `ValueError` naming
  **both** config shapes
- missing both + `required=False` → None
- the secret **never** appears in any log line across both
  branches (full DEBUG capture)

## Related

- `docs/reference/social-routing.md` — the bearer-token
  migration this resolver borrows its shape from.
- `athena/safety/secure_files.py` — the atomic-replace +
  0o600 writer athena uses when it writes credential files
  itself.
