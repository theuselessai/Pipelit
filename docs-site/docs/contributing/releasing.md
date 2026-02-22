# Releasing

This guide covers how to create a new Pipelit release: version bumping, changelog management, tagging, and the automated GitHub Release workflow.

## Version source of truth

The version lives in a single file at the repository root:

```
VERSION
```

This file contains just the version number (e.g., `0.1.0`). It is read by:

- **`platform/main.py`** — loaded at startup to set the FastAPI app version (visible at `/docs`)
- **`platform/frontend/package.json`** — mirrored manually (npm convention)

## Release checklist

### 1. Create a release branch

```bash
git checkout master && git pull origin master
git checkout -b release/vX.Y.Z
```

### 2. Bump the version

```bash
echo "X.Y.Z" > VERSION
```

### 3. Sync `package.json`

Edit `platform/frontend/package.json` and set `"version": "X.Y.Z"` to match.

### 4. Update the changelog

In `docs-site/docs/changelog.md`:

1. Add an empty `## [Unreleased]` section at the top (below the header)
2. Rename the previous `## [Unreleased]` to `## [X.Y.Z] - YYYY-MM-DD`
3. Review all entries under the new version heading for accuracy

### 5. Commit and open a PR

```bash
git add VERSION platform/frontend/package.json docs-site/docs/changelog.md
git commit -m "Prepare vX.Y.Z release"
git push -u origin release/vX.Y.Z
gh pr create --title "Release vX.Y.Z" --body "Release prep for vX.Y.Z"
```

### 6. Merge and tag

After the PR is reviewed and merged:

```bash
git checkout master && git pull
git tag -a vX.Y.Z -m "Pipelit vX.Y.Z"
git push origin vX.Y.Z
```

The tag push triggers the release CI workflow automatically.

## Versioning guidelines

Pipelit follows [Semantic Versioning](https://semver.org/):

| Bump | When |
|------|------|
| **Major** (X.0.0) | Breaking API or workflow schema changes |
| **Minor** (0.X.0) | New features, new node types, non-breaking additions |
| **Patch** (0.0.X) | Bug fixes, documentation updates, dependency bumps |

While the project is pre-1.0, minor versions may include breaking changes.

## Changelog format

The changelog follows [Keep a Changelog](https://keepachangelog.com/) conventions:

| Category | Use for |
|----------|---------|
| **Added** | New features, new node types, new API endpoints |
| **Changed** | Changes to existing functionality |
| **Deprecated** | Features that will be removed in a future version |
| **Removed** | Features that were removed |
| **Fixed** | Bug fixes |
| **Security** | Vulnerability fixes |

## Hotfix releases

For urgent fixes on top of a released version:

```bash
git checkout master && git pull
git checkout -b hotfix/vX.Y.Z
# Apply the fix
# Bump VERSION to the patch version
# Add changelog entry under a new version heading
# PR, merge, tag as usual
```

## CI automation

The `.github/workflows/release.yml` workflow runs on every `v*` tag push:

1. **Extracts** the version from the tag name (strips the `v` prefix)
2. **Parses** `docs-site/docs/changelog.md` for the matching `## [X.Y.Z]` section
3. **Creates** a GitHub Release with the extracted changelog notes

No manual release creation on GitHub is needed — just push the tag.
