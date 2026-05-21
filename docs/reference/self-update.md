# Self-update — `athena update`

athena keeps itself current. `athena update` detects how athena
was installed, checks the latest published release, previews
the changelog, verifies integrity (via pip's hash check),
installs, and ends with "restart athena to use it" — never
hot-swapping the running process.

## Quick start

```bash
athena update --check          # current vs latest + changelog; install nothing
athena update                  # confirm → install → "restart to use it"
athena update --to 0.4.2       # pin to a specific version (up or down)
athena update --rollback       # restore the previously-installed version
athena update --yes            # skip the confirm prompt (for scripts)
```

Offline:

```bash
athena update
# → "could not reach the update source (offline?); no changes made"
```

## How install-method detection works

athena can be installed four ways; `athena update` picks the
right upgrade path per host. Detection layers four signals (in
order; first match wins):

| Method | Signal | Upgrade path |
|---|---|---|
| **editable** | `direct_url.json` has `dir_info.editable = true` | refused (warn — update via your source checkout) |
| **git** | package path has a `.git` ancestor (and isn't editable) | `git fetch` + `git checkout <tag>` + `pip install .` |
| **pipx** | package path contains `pipx` (case-insensitive) | `pipx upgrade athena-coder` (or `pipx install athena-coder==V --force` to pin) |
| **pip** | package is registered in `importlib.metadata`, no other signals | `python -m pip install --upgrade athena-coder[==V]` |
| **unknown** | none of the above | refused (warn — try one of pip/pipx/git explicitly) |

Editable wins over git when both signals are present — the user
is iterating on a source checkout; we don't `git pull` behind
them.

The detected method is shown at the top of every `athena update`
run:

```text
athena 0.2.0 installed via pip
```

## The flow

```text
detect install method
   ↓
look up latest version (per cfg.update_channel)
   ↓
offline?            → warn + exit (no changes)
up to date?         → "athena 0.2.0 is up to date." + exit
   ↓
render changelog between current and latest
   ↓
confirm? (skipped with --yes)
   ↓
record_prior(current_version)        ← for --rollback
   ↓
install via the detected method
   ↓
"installed athena 0.3.0 via pip — restart athena to use it"
```

The install step **never hot-swaps the running process.** There
is no `os.execv`, no `sys.exit`, no auto-restart. The running
session finishes on the old code; the next launch is the new
version. A test pins this — tripwires on `os.execv` /
`os.execvp` / `os._exit` fire if the install path ever calls
them. They never do.

## Integrity verification

For PyPI installs (pip / pipx), athena runs:

```bash
python -m pip install --upgrade athena-coder
```

`pip` automatically verifies the wheel's SHA-256 against PyPI's
recorded hash. We don't bypass that — every install goes
through `pip`, so its verification fires.

For git installs, the path is:

```bash
git fetch --tags
git checkout v<version>     # or  git merge --ff-only @{u}  when unpinned
python -m pip install .     # builds + installs from the checkout
```

git tag verification (signed tags via `git verify-tag`) is not
enforced today — the project's release process would need to
sign tags first. The current contract is "the user's git remote
is trusted." When signed tags land, the apply step gains a
`--verify-signature` flag.

## Changelog preview

Before installing, the command prints the diff between current
and latest:

- **pip / pipx:** the section of `CHANGELOG.md` between the two
  versions. Heading shapes recognised: `## [1.2.3]`,
  `## [Unreleased]`, `## 1.2.3`, `## v1.2.3 - 2026-01-01`.
- **git:** `git log v<current>..v<latest> --oneline`.
- **fallback:** when neither lookup works, a short pointer
  message instructing the user to read the project's CHANGELOG.

The preview always shows; the install step then prompts for
confirmation.

## `--to <version>` — pin to a specific version

Skips the latest-version lookup; installs exactly the named
version (up or down — pip handles both directions):

```bash
athena update --to 0.4.2 --yes
```

Useful for:

- Pinning to a known-good version (downgrade from a broken
  release).
- Sticking on an LTS-ish version while skipping a release you
  don't want.

## `--rollback` — restore the prior version

```bash
athena update --rollback
```

Reads `update_state.json` (default
`<CONFIG_DIR>/update_state.json`) for the version recorded
before the most recent successful upgrade, then installs that
exact version via the detected method.

When no prior version is recorded:

```bash
athena update --rollback
# → "no prior version recorded — run `athena update` once first; the next rollback will restore that version."
```

The prior version is recorded **before** the install, so even a
failed upgrade leaves a target for rollback (you can roll back
to the version that was working).

## Offline-safe

The "no network" case is the most important one to get right —
many local-first setups deliberately restrict network access:

| Trigger | Behaviour |
|---|---|
| `urlopen` raises `OSError` / `URLError` | `latest_pypi_version` returns `None` |
| PyPI returns a malformed payload | same — None |
| `git ls-remote` fails / times out | `latest_git_tag` returns `None` |
| `None` latest | command prints "could not reach update source (offline?)" + exits without changes |

Always: a network failure produces a one-line message, never a
stack trace. The `--check` and default install paths both
honour this.

## Optional startup auto-check

```toml
update_auto_check = true   # default false
```

When on, athena's startup runs a 3-second-timeout PyPI lookup
and prints a one-line notice if a newer version exists:

```text
athena 0.3.0 is available (current 0.2.0); run `athena update` to install.
```

**Notify only.** The auto-check never auto-installs. A test
pins that the lookup is the only thing that fires + the install
function is never called from `startup_notice`.

The auto-check is silent when:

- `update_auto_check = false` (the default; no lookup attempted)
- Install method is `editable` or `unknown` (the upgrade path
  isn't relevant)
- The lookup fails / returns `None` (offline)
- The lookup raises any exception (courtesy notice; never
  breaks startup)

## Configuration

```toml
# Detection override. "auto" lets athena pick; "pypi" / "git"
# forces a specific path (useful when athena is installed via
# git but you want to pull releases from PyPI).
update_source = "auto"      # auto | pypi | git

# Release channel. "stable" filters out a1 / b1 / rc1 / dev
# shapes; "pre" includes them.
update_channel = "stable"   # stable | pre

# Startup auto-check. OFF by default — when on, prints a
# one-line notice on launch if a newer version exists. Never
# auto-installs.
update_auto_check = false

# Where the prior-version record lives. None →
# <CONFIG_DIR>/update_state.json.
update_state_path = "/path/to/update_state.json"
```

## What this does not do

- **Doesn't hot-swap.** Running session finishes on old code;
  next launch is new code. The success message says so
  explicitly.
- **Doesn't auto-install.** Every install path requires explicit
  confirmation (or `--yes`). The startup auto-check is notify-
  only.
- **Doesn't install over editable installs.** EDITABLE refuses
  cleanly + tells the user to update via their source checkout.
- **Doesn't verify git signatures.** Today the contract is "the
  user's git remote is trusted." Signed-tag verification can
  land here when the project's release process signs tags.
- **Doesn't downgrade automatically.** `--to <older_version>`
  works for explicit downgrade; the default flow never picks an
  older version.

## Smoke

```bash
# Check for an update (no install).
athena update --check
# → athena 0.2.0 installed via pip
# → update available: 0.2.0 → 0.3.0
# → [changelog preview]
# → this is a --check report; run `athena update` to install

# Run the install.
athena update
# → confirm? [y/N]
# → installed athena 0.3.0 via pip — restart athena to use it

# Roll back if 0.3.0 turned out to be broken.
athena update --rollback
# → rolled back to 0.2.0

# Pin to a known version.
athena update --to 0.2.5 --yes
# → installed athena 0.2.5 via pip — restart athena to use it

# Offline — clean message, no changes.
# (After disconnecting network.)
athena update
# → could not reach the update source (offline?); no changes made
```

## Related

- [Provider capabilities](provider-capabilities.md) — independent
  manifest layer; updates don't change provider declarations.
- [Audit log](audit-log.md) — the update history is implicit in
  `update_state.json` + the CHANGELOG; not surfaced through the
  audit subsystem.
