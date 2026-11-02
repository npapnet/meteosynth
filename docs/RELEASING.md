# Releasing `meteosynth`

Step-by-step procedure for cutting a release with **git-flow** and **uv**, from a clean
`develop` to a package on PyPI. Written for `v0.3.3`; for later releases change the
version string throughout.

Commands are PowerShell (Windows). Run everything from the repository root.

## TL;DR — SmartGit + uv

Git-flow actions are done from SmartGit's GUI (*Repository → Git-Flow*); everything else
is a uv command or a documentation edit. Full CLI detail is in the
[detailed procedure](#detailed-procedure-cli-version) below.

**Pre-flight (on `develop`)**
- Pull `develop`; working tree clean.
- `uv sync` — environment matches `uv.lock`.
- `uv run pytest` — all green.
- Docs: confirm `CHANGELOG.md` → `## Current sprint — unreleased` describes everything
  that is shipping, and that finished items are removed from `TODOs.md`.

**Start release**
- SmartGit: **Start gitflow release** → name `v0.3.3` (with the `v`; it becomes the tag).

**On the release branch**
- `uv version 0.3.3` — bumps `pyproject.toml` and `uv.lock`. Check with `uv version`.
- Docs:
  - `CHANGELOG.md`: rename `## Current sprint — unreleased` → `## [0.3.3] — YYYY-MM-DD`.
  - `docs/design/architecture.md` and `docs/design/README.md`: update the hand-written
    version and release date (`git grep -n "0\.3\.2"` finds them).
  - `docs/source/conf.py` and `meteosynth.__version__` need no edit — they read the version.
- `uv run pytest`
- `uv run sphinx-build -b html docs/source docs/build/html` — docs build with the new version.
- Delete `dist/`, then `uv build`.
- `uv run --isolated --no-project --with ./dist/meteosynth-0.3.3-py3-none-any.whl python -c "import meteosynth; print(meteosynth.__version__)"` → `0.3.3`.
- `uvx twine check dist/*`
- Commit (`pyproject.toml`, `uv.lock`, `CHANGELOG.md`, `TODOs.md`, `docs/design/`).

**Finish release**
- SmartGit: **Finish gitflow release** → tag message `Finish v0.3.3`.
- Push `main`, `develop` and the tag `v0.3.3` (pushing `main` deploys the docs site via
  GitHub Actions — check it goes green).

**Publish** (`uv publish` ignores `.pypirc`, so upload with twine through uv)
- `uvx twine upload --repository testpypi dist/*` → install check from TestPyPI.
- `uvx twine upload --repository pypi dist/*`
- `uv run --isolated --no-project --refresh --with meteosynth==0.3.3 python -c "import meteosynth; print(meteosynth.__version__)"`

**After**
- On `develop`: add a fresh empty `## Current sprint — unreleased` to `CHANGELOG.md`.
- Optional: GitHub release from tag `v0.3.3` with the `## [0.3.3]` changelog section.

---

# Detailed procedure (CLI version)

> This section uses the git-flow / git **command line** for every step. If you drive
> git-flow from SmartGit, the TL;DR above is all you need; use this section for the
> exact commands, explanations and troubleshooting.

## Conventions this repo already uses

| Thing | Convention | Example |
|---|---|---|
| Production branch | `main` | |
| Integration branch | `develop` | |
| Release branch | `release/v<X.Y.Z>` | `release/v0.3.3` |
| Tag | `v<X.Y.Z>` (git-flow tag prefix is empty, so the `v` comes from the release name) | `v0.3.3` |
| Tag / merge message | `Finish v<X.Y.Z>` | `Finish v0.3.3` |
| Version source of truth | `version = "..."` in `pyproject.toml` (set with `uv version`) | `0.3.3` |
| Runtime version | `meteosynth.__version__` reads installed metadata, no edit needed | |
| Docs version | `docs/source/conf.py` reads `pyproject.toml`, no edit needed | |
| Changelog | Rename `## Current sprint — unreleased` to `## [X.Y.Z] — YYYY-MM-DD` | |

> **Name the release `v0.3.3`, not `0.3.3`.** git-flow builds the tag from
> `<versiontag prefix><release name>`, and the prefix here is empty. Starting the release as
> `0.3.3` would produce the tag `0.3.3`, out of line with `v0.2.0` … `v0.3.2`.

---

## 0. Pre-flight

```powershell
git switch develop
git pull --ff-only origin develop
git fetch origin main --tags
git status                      # must be clean
uv sync                         # lockfile and env up to date
uv run pytest                   # all green before you start
```

Nothing goes into the release branch that is not already on `develop`. If a feature is
still open, finish it first (`git flow feature finish <name>`).

## 1. Start the release branch

With git-flow (AVH edition, bundled with Git for Windows):

```powershell
git flow release start v0.3.3
```

Plain-git equivalent:

```powershell
git switch -c release/v0.3.3 develop
```

From here until step 5, only release-preparation commits go on this branch (version bump,
changelog, docs sync, last-minute fixes). No new features.

## 2. Bump the version with uv

```powershell
uv version 0.3.3                # explicit
# or, equivalently for a patch release:
# uv version --bump patch
uv version                      # prints: meteosynth 0.3.3
```

`uv version` rewrites `version` in `pyproject.toml` **and** updates the `meteosynth` entry
in `uv.lock`, so both files change. Commit both. (Use `--no-sync` if you want to skip the
environment re-sync it does afterwards.)

## 3. Update the changelog and synced docs

1. **`CHANGELOG.md`** — rename the heading, don't copy the section:

   ```markdown
   ## Current sprint — unreleased        →        ## [0.3.3] — 2026-11-02
   ```

   Then add a fresh, empty `## Current sprint — unreleased` heading above it if you want
   the bucket ready for the next sprint. Check that completed `TODOs.md` items have been
   folded in and removed from `TODOs.md`, and that any `### Decisions` lines link to
   their design docs.

2. **Hand-written version mentions** — these do not update themselves. Find them:

   ```powershell
   git grep -n "0\.3\.2" -- ':!uv.lock' ':!CHANGELOG.md'
   ```

   As of `v0.3.2` they were in:
   - `docs/design/architecture.md` — the *In Scope* line, the *Current Package State*
     heading and the *Version* bullet (version **and** release date).
   - `docs/design/README.md` — the `architecture.md` row in the index table.

   Leave historical references alone (e.g. the "Recorded … at 0.3.2" comment in
   `tests/test_sampler_calibration.py` is a record, not a current-version claim).

3. Re-run the tests and build the docs locally, since `conf.py` now picks up `0.3.3`:

   ```powershell
   uv run pytest
   uv run sphinx-build -b html docs/source docs/build/html
   ```

4. Commit:

   ```powershell
   git add pyproject.toml uv.lock CHANGELOG.md TODOs.md docs/design
   git commit -m "chore: bump version to 0.3.3 and sync documentation"
   ```

## 4. Build and test the artifacts (before finishing)

Build on the release branch so any packaging problem is fixed *before* the tag exists.
`uv build` does not empty `dist/` (which still holds old `0.1.0` files), so clear it first:

```powershell
Remove-Item -Recurse -Force dist -ErrorAction SilentlyContinue
uv build                        # -> dist/meteosynth-0.3.3.tar.gz + dist/meteosynth-0.3.3-py3-none-any.whl
```

Smoke-test the wheel in a throwaway environment that does **not** see the source tree:

```powershell
uv run --isolated --no-project --with ./dist/meteosynth-0.3.3-py3-none-any.whl `
    python -c "import meteosynth; print(meteosynth.__version__)"
# expected: 0.3.3
```

Optional, check the metadata/README render the way PyPI will:

```powershell
uvx twine check dist/*
```

If something is wrong, fix it, commit on the release branch, and rebuild.

## 5. Finish the release (merge to `main`, tag, back-merge to `develop`)

With git-flow:

```powershell
git flow release finish -m "Finish v0.3.3" v0.3.3
```

This merges `release/v0.3.3` into `main`, creates the annotated tag `v0.3.3` on `main`,
merges back into `develop`, and deletes the release branch.

Plain-git equivalent:

```powershell
git switch main
git merge --no-ff release/v0.3.3 -m "Finish v0.3.3"
git tag -a v0.3.3 -m "Finish v0.3.3"
git switch develop
git merge --no-ff v0.3.3 -m "Finish v0.3.3"
git branch -d release/v0.3.3
```

Verify:

```powershell
git log --oneline --graph -5 main
git describe --tags main        # v0.3.3
```

## 6. Push branches and tag

```powershell
git push origin main
git push origin develop
git push origin v0.3.3
```

Pushing `main` triggers `.github/workflows/docs.yml`, which rebuilds and deploys the
documentation site. Check the Actions tab that it went green.

## 7. Rebuild from the tag

Publish exactly what the tag contains. If the tree on `main` is identical to the release
branch (it normally is) the artifacts from step 4 are fine, but a clean rebuild from the
tag is cheap and removes any doubt:

```powershell
git switch --detach v0.3.3
Remove-Item -Recurse -Force dist -ErrorAction SilentlyContinue
uv build
git switch develop
```

## 8. Publish — TestPyPI first, then PyPI

> **Important: `uv publish` does not read `~/.pypirc`.** It takes credentials only from
> `--token` / `UV_PUBLISH_TOKEN`, `--username`/`--password`, keyring, or Trusted Publishing.
> Since authorisation here lives in `.pypirc`, the recommended upload tool is **twine run
> through uv** (`uvx twine`), which reads `.pypirc` directly and needs no install.

### 8a. TestPyPI (dry run)

```powershell
uvx twine upload --repository testpypi dist/*
```

Check that it installs from TestPyPI (dependencies still resolve from real PyPI):

```powershell
uv run --isolated --no-project `
    --index https://test.pypi.org/simple/ --index-strategy unsafe-best-match `
    --with meteosynth==0.3.3 `
    python -c "import meteosynth; print(meteosynth.__version__)"
```

TestPyPI, like PyPI, never accepts the same filename twice. If you need to retry, it has to
be a new version — another reason to get step 4 right.

### 8b. PyPI

```powershell
uvx twine upload --repository pypi dist/*
```

Then verify from the real index (allow a minute for the CDN):

```powershell
uv run --isolated --no-project --refresh --with meteosynth==0.3.3 `
    python -c "import meteosynth; print(meteosynth.__version__)"
```

and look at <https://pypi.org/project/meteosynth/0.3.3/>.

### Alternative: `uv publish` with a token

If you prefer uv end to end, pass the API token yourself (the value after `password =` in
the `[pypi]` section of `.pypirc`):

```powershell
$env:UV_PUBLISH_TOKEN = "pypi-..."            # PyPI token
uv publish

# TestPyPI needs its own token and URL:
uv publish --publish-url https://test.pypi.org/legacy/ --token "pypi-..."
```

`uv publish` uploads `dist/*` by default, so the `dist/` clean-up in steps 4 and 7 matters
here too. Never commit a token, and clear it afterwards: `Remove-Item Env:UV_PUBLISH_TOKEN`.

## 9. GitHub release (optional)

```powershell
gh release create v0.3.3 dist/* --title "v0.3.3" --notes-file <file-with-0.3.3-changelog-section>
```

or create it in the web UI from the existing tag and paste the `## [0.3.3]` changelog
section.

## 10. Prepare `develop` for the next sprint

```powershell
git switch develop
git pull --ff-only origin develop
```

Make sure `CHANGELOG.md` on `develop` has an empty `## Current sprint — unreleased` heading
at the top. The version in `pyproject.toml` stays at `0.3.3` until the next release branch
bumps it.

---

## If something goes wrong

| Situation | What to do |
|---|---|
| Tests fail on the release branch | Fix on the release branch, commit, continue. The fix is merged back to `develop` at finish. |
| Mistake found after finish, **before** pushing | `git tag -d v0.3.3`, fix on `main`/`develop` by resetting the merges, redo step 5. Only do this when nothing has been pushed. |
| Mistake found after pushing, **before** PyPI upload | Prefer a new patch (`v0.3.4`). Moving a published tag breaks anyone who fetched it. |
| Bad upload on PyPI | You cannot overwrite a file. **Yank** `0.3.3` in the PyPI web UI (Manage → Release → Options → Yank) and release a hotfix: `git flow hotfix start v0.3.4` from `main`. |
| `File already exists` on upload | `dist/` contains an old version, or this version is already uploaded. Clean `dist/` and rebuild; if it really was uploaded, bump the version. |
| `403 Forbidden` on upload | Wrong token / wrong `--repository` section in `.pypirc` (TestPyPI and PyPI tokens are different). |

## Quick checklist

- [ ] `develop` clean, pulled, tests green
- [ ] `git flow release start v0.3.3`
- [ ] `uv version 0.3.3` (pyproject + uv.lock)
- [ ] `CHANGELOG.md` heading renamed; `TODOs.md` pruned
- [ ] Version strings in `docs/design/` updated
- [ ] Tests + docs build green; commit
- [ ] Clean `dist/`, `uv build`, wheel smoke test, `twine check`
- [ ] `git flow release finish -m "Finish v0.3.3" v0.3.3`
- [ ] Push `main`, `develop`, `v0.3.3`; docs workflow green
- [ ] Rebuild from tag
- [ ] `uvx twine upload -r testpypi dist/*` → install check
- [ ] `uvx twine upload -r pypi dist/*` → install check
- [ ] GitHub release (optional)
