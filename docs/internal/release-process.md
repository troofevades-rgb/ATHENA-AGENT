# Release process

Checklist for cutting a new athena-coder release.

## Before tagging

- [ ] All planned work for this version is on `master`
- [ ] CI is green on `master` (`gh run list --branch master --limit 5`)
- [ ] `CHANGELOG.md` `## [Unreleased]` content is moved into
      `## [X.Y.Z] - YYYY-MM-DD`
- [ ] New empty `## [Unreleased]` section is added at the top of
      `CHANGELOG.md`
- [ ] `RELEASE_v<X.Y.Z>.md` file exists at repo root summarizing the
      release for the GitHub Releases UI
- [ ] `pyproject.toml` `[project].version` matches `X.Y.Z`
- [ ] `athena/__init__.py` `__version__` matches `X.Y.Z`
- [ ] `python scripts/verify_version.py` passes
- [ ] `pytest -q` passes locally
- [ ] `ruff check athena tests` passes
- [ ] `ruff format --check athena tests` passes
- [ ] `python -m build && twine check dist/*` passes
- [ ] (Optional) Staged on TestPyPI via a `v<X.Y.Z>rc<N>` tag and
      installed cleanly from a fresh venv before cutting the real tag

## Tagging

```bash
git tag v<X.Y.Z>
git push origin v<X.Y.Z>
```

The `.github/workflows/publish.yml` workflow fires automatically on
the tag push.

## After tag is pushed

- [ ] GitHub Actions `publish.yml` workflow runs to completion
- [ ] PyPI shows the new version at
      https://pypi.org/project/athena-coder/
- [ ] Fresh-venv install + launch verified from a different machine
      (or at minimum a different directory):
      ```bash
      python -m venv /tmp/verify
      /tmp/verify/bin/pip install athena-coder==<X.Y.Z>
      /tmp/verify/bin/athena --version
      # → 'athena-coder <X.Y.Z>'
      ```
- [ ] Draft a GitHub Release at
      https://github.com/troofevades-rgb/ATHENA-AGENT/releases/new
      with:
      - Tag: `v<X.Y.Z>`
      - Title: `v<X.Y.Z> — <release name>`
      - Body: contents of `RELEASE_v<X.Y.Z>.md`
- [ ] Announce on X / Bluesky with a link to the release

## Version-bump conventions

- **Patch (0.2.0 → 0.2.1):** bug fixes, security fixes, no API changes
- **Minor (0.2.0 → 0.3.0):** new features, backward-compatible
- **Major (0.2.0 → 1.0.0):** breaking changes; reserved for 1.0 GA

## Pre-release staging

```bash
git tag v0.3.0rc1
git push origin v0.3.0rc1
```

The publish workflow's pre-release detection (PEP 440 `a`/`b`/`rc`/`.dev`
suffixes) routes the build to TestPyPI instead of real PyPI. Install
the staged build:

```bash
pip install --index-url https://test.pypi.org/simple/ \
            --extra-index-url https://pypi.org/simple/ \
            athena-coder==0.3.0rc1
```

The `--extra-index-url` is required because TestPyPI doesn't mirror
production dependencies — without it pip can't resolve `httpx`,
`rich`, etc.

## Rollback

PyPI does not allow re-uploads of the same version. If a release
ships broken:

1. Bump the patch version (`0.2.1` → `0.2.2`).
2. Fix the bug.
3. Tag and push the new version.

To yank a broken release (still installable explicitly via
`==<version>` pin, but pip's resolver will skip it for `~=` /
`>=` specs):

- PyPI project page → Releases → click the bad version → "Yank".

## Manual workflow dispatch

If the tag push triggered the workflow but it failed mid-run
(transient PyPI 5xx, network glitch, etc.), re-run via the
Actions tab → publish workflow → "Run workflow". Pick `pypi` or
`testpypi` as the target. The `skip-existing: true` flag on the
publish action means re-runs against an already-uploaded version
no-op cleanly instead of failing.
