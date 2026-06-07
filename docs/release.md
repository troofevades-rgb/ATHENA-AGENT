# Release process

`athena-coder` ships to PyPI via GitHub Actions trusted publishing
(OIDC). There are no long-lived API tokens in repo settings or
workflow files — PyPI verifies each upload against a registered
GitHub Actions identity at handshake time.

## One-time setup (operator runs this once per package)

Two registrations are required: one on TestPyPI for staging
pre-release tags (`v*-rc*`, `v*-beta*`, `v*-alpha*`), one on real
PyPI for stable tags.

### TestPyPI

1. Create a TestPyPI account at https://test.pypi.org/account/register/
2. Once logged in: https://test.pypi.org/manage/account/publishing/
3. **Add a new pending publisher** with:
   - PyPI project name: `athena-coder`
   - Owner: `troofevades-rgb`
   - Repository name: `ATHENA-AGENT`
   - Workflow filename: `publish.yml`
   - Environment name: `testpypi`
4. Submit. TestPyPI will accept the first upload that matches
   exactly these claims and auto-create the project under your
   account.

### PyPI

Same flow on https://pypi.org/manage/account/publishing/ with one
difference: the environment name is `pypi` (no "test" prefix).

### GitHub environments

The workflow references two environments by name (`testpypi` and
`pypi`). GitHub auto-creates them on first run, but you can
optionally pre-create them in repo Settings → Environments to
add manual approval gates (e.g., require a maintainer to click
"Approve and deploy" before a real-PyPI publish runs).

## Cutting a release

Use the helper — it bumps both version surfaces in lockstep (so the
`version-sync` gate can't fail), promotes the CHANGELOG `[Unreleased]`
block to a dated section, refuses to go backwards, and prints the exact
commit + tag commands:

```bash
$ python scripts/release.py 0.2.1            # preview first:
$ python scripts/release.py 0.2.1 --dry-run  # shows the diffs, writes nothing
```

Then commit (via PR — `master` is protected), and after it merges, tag:

```bash
$ git switch -c release/0.2.1 && git commit -am "release: 0.2.1"
$ git push -u origin release/0.2.1 && gh pr create --base master --fill
# ... after merge ...
$ git switch master && git pull
$ git tag v0.2.1 && git push origin v0.2.1
```

<details><summary>By hand (what the script does for you)</summary>

```bash
$ vim pyproject.toml      # bump [project] version
$ vim athena/__init__.py  # bump __version__ to the SAME value (version-sync)
$ vim CHANGELOG.md         # move Unreleased entries under ## [0.2.1] - <date>
$ git commit -am "release: 0.2.1" && git push
$ git tag v0.2.1 && git push origin v0.2.1
```

</details>

The `v0.2.1` tag push fires the `publish` workflow. Because
`0.2.1` is not a pre-release, the build artifact goes straight to
real PyPI. Watch the workflow run; the publish step's environment
URL links directly to the new release page on PyPI.

## Staging a release candidate

```bash
$ git tag v0.3.0-rc1
$ git push origin v0.3.0-rc1
```

The tag matches the pre-release detection regex (`a|b|rc|.dev|-rc`
and friends), so the workflow's TestPyPI job fires and the real
PyPI job skips. Install the staged build:

```bash
pip install --index-url https://test.pypi.org/simple/ \
            --extra-index-url https://pypi.org/simple/ \
            athena-coder==0.3.0rc1
```

The `--extra-index-url` is required because TestPyPI doesn't mirror
production dependencies — without it, pip can't resolve `httpx`,
`rich`, etc.

## Manual dispatch

If a tag push fails partway through (transient PyPI 5xx, etc.),
re-run via `Actions → publish → Run workflow`. Pick the
`pypi` or `testpypi` target. The `skip-existing: true` flag on the
publish action means re-runs against an already-uploaded version
no-op cleanly instead of failing.

## Versioning convention

Semantic versioning with PEP 440 pre-release suffixes:

- `v0.2.1` — patch
- `v0.3.0` — minor (new feature)
- `v1.0.0` — major (1.0 GA per the roadmap)
- `v1.0.0rc1` — release candidate, publishes to TestPyPI only
- `v1.0.0b1` — beta, TestPyPI
- `v1.0.0a1` — alpha, TestPyPI

The workflow's `is_prerelease` detection runs on the version
string itself, not the tag — so `v1.0.0` and `1.0.0` both publish
to real PyPI, and `v1.0.0rc1` / `1.0.0rc1` both go to TestPyPI.

## Rollback

PyPI never lets you re-upload the same version. If a release
ships broken:

1. Bump the patch version (`0.2.1` → `0.2.2`).
2. Fix.
3. Tag and push.

You can `pip install athena-coder==0.2.0` to get the prior version
as long as it wasn't yanked. To yank a broken release (still
installable explicitly, but pip won't auto-resolve to it):

- PyPI project page → Releases → click the bad version → "Yank".
