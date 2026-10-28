# Releasing

Releases are cut from `main` by pushing a version tag. The tag starts the
[release workflow](../.github/workflows/release.yml), which builds the package, creates the GitHub
release and publishes to PyPI.

## One-time PyPI setup

The workflow publishes with [Trusted Publishing](https://docs.pypi.org/trusted-publishers/), so no
API token is stored anywhere. Before the first release, the maintainer registers the project as a
pending publisher:

1. Sign in to [pypi.org](https://pypi.org).
2. Open **Account settings**, then **Publishing**, then **Add a new pending publisher**.
3. Fill in:

   | Field | Value |
   |---|---|
   | PyPI project name | `agent-mem-vault` |
   | Owner | `kursatdinc` |
   | Repository name | `agent-mem-vault` |
   | Workflow name | `release.yml` |
   | Environment name | `pypi` |

4. Save. The first successful publish creates the project and turns the pending publisher into a
   normal one.

The `pypi` environment already exists in the GitHub repository settings. To require a manual
approval before each publish, add a required reviewer to it under
**Settings, Environments, pypi**.

## Cutting a release

1. Update the version in `pyproject.toml` (`version = "X.Y.Z"`). `agent-mem-vault --version`
   reads it from the package metadata.
2. In `CHANGELOG.md`, rename `Unreleased` to the new version with today's date, add a fresh empty
   `Unreleased` section, and update the compare links at the bottom.
3. Run the checks and refresh the lock file:

   ```sh
   uv sync
   uv run ruff check
   uv run pytest -q
   uv build
   ```

4. Commit, for example `chore: release X.Y.Z`, and push to `main`. Wait for CI to pass.
5. Tag and push the tag:

   ```sh
   git tag -a vX.Y.Z -m "vX.Y.Z"
   git push origin vX.Y.Z
   ```

## What the workflow does

For every tag matching `v*`:

1. **build** checks that a stable tag equals the version in `pyproject.toml`, runs `uv build`, and
   uploads the sdist and wheel as the `dist` artifact.
2. **github-release** creates a GitHub release named after the tag. The notes are the matching
   section of `CHANGELOG.md`, and the sdist and wheel are attached. A tag with a suffix, such as
   `v1.1.0-rc.1`, is marked as a pre-release.
3. **publish-pypi** runs only for stable tags (`vX.Y.Z`, no suffix). It waits for `build`, runs in the
   `pypi` environment, and uploads the same `dist` files to PyPI through Trusted Publishing.

A pre-release tag therefore never reaches PyPI.

## Re-running the publish

If the publish failed after the tag was pushed (for example before the pending publisher existed),
fix the cause and re-run the workflow for the existing tag:

```sh
gh workflow run release.yml --ref vX.Y.Z
```

This runs `build` and `publish-pypi` again; the GitHub release is only created on the original tag
push. PyPI refuses to upload a file twice, so a re-run only helps when the earlier publish did not
upload anything. A version that is on PyPI cannot be replaced: fix forward with a new version.

## Publishing the wiki

The wiki pages live in `docs/wiki/` so they are reviewed with the code. GitHub creates the wiki's git
repository only after its first page exists, so once, create any page in the web UI
(**Wiki, Create the first page**). After that:

```sh
git clone https://github.com/kursatdinc/agent-mem-vault.wiki.git
cp docs/wiki/*.md agent-mem-vault.wiki/
cd agent-mem-vault.wiki && git add -A && git commit -m "docs: sync wiki" && git push
```
