# Releasing — Internal Runbook

Quick-reference for cutting a Pipelit release.

## Version source of truth

`VERSION` at repo root. Read by `platform/main.py` at startup. Also mirrored in `platform/frontend/package.json`.

## Release flow

```bash
# 1. Branch
git checkout master && git pull origin master
git checkout -b release/vX.Y.Z

# 2. Bump version
echo "X.Y.Z" > VERSION

# 3. Sync frontend version
# Edit platform/frontend/package.json — set "version": "X.Y.Z"

# 4. Update changelog
# In docs-site/docs/changelog.md:
#   - Add empty ## [Unreleased] section at top
#   - Rename old [Unreleased] → [X.Y.Z] - YYYY-MM-DD

# 5. Commit & PR
git add VERSION platform/main.py platform/frontend/package.json docs-site/docs/changelog.md
git commit -m "Prepare vX.Y.Z release"
git push -u origin release/vX.Y.Z
gh pr create --title "Release vX.Y.Z" --body "Release prep for vX.Y.Z"

# 6. After PR merges — tag on master
git checkout master && git pull
git tag -a vX.Y.Z -m "Pipelit vX.Y.Z"
git push origin vX.Y.Z
```

Tag push triggers `.github/workflows/release.yml` → creates GitHub Release with changelog notes automatically.

## Hotfix

```bash
git checkout master && git pull
git checkout -b hotfix/vX.Y.Z
# fix, bump VERSION, update changelog, PR, merge, tag
```

## What the CI does

`.github/workflows/release.yml` runs on `v*` tag pushes:

1. Extracts version from tag name
2. Parses changelog for the matching `## [X.Y.Z]` section
3. Creates a GitHub Release with those notes via `gh release create`
