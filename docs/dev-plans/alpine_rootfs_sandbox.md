# Plan: Replace Host System Binds with Alpine Linux Mini Rootfs

> **Created:** 2026-02-26
> **Status:** Draft
> **Depends on:** sandbox_mode_config.md (security architecture, setup wizard, workspace management)

---

## 1. Problem

The current bwrap sandbox in `platform/components/sandboxed_backend.py` ro-binds the host's `/usr`, `/bin`, `/lib` into the sandbox. This has several issues:

1. **Unpredictable environment** — sandbox tools vary by host distro (Debian, Ubuntu, Fedora, Arch, etc.)
2. **Complex host-specific code** — `_prepare_sandbox_root()` has 45 lines of merged-usr detection, symlink creation, and mount-point scaffolding
3. **Exposes all host binaries** — the agent sees every binary in `/usr/bin`, not a controlled subset
4. **glibc venv coupling** — venv created with host python3 ties the sandbox to the host's libc
5. **Capability detection becomes guessing** — we don't control what's available, we can only discover it

## 2. Solution: Alpine Linux Mini Rootfs

Replace all host system binds with Alpine Linux's mini root filesystem (~3MB compressed, ~8MB extracted) as the sandbox root.

**Alpine provides:**
- musl libc (small, self-contained)
- `apk` package manager to install exactly the tools we want
- Consistent environment across all host distros
- x86_64, aarch64, armv7, x86 architecture support
- Used by Docker containers everywhere — battle-tested

## 3. Architecture

### 3.1 Current (host-binding)

```
bwrap --bind workspace / --ro-bind /usr /usr --ro-bind /etc/ssl /etc/ssl ...
  → Agent sees: / = workspace (rw), /usr = HOST binaries (ro)
  → Writes to ANY path persist in workspace
  → Complex _prepare_sandbox_root() for merged-usr detection
```

### 3.2 New (Alpine rootfs)

```
bwrap \
  --unshare-all \
  --ro-bind {pipelit_dir}/rootfs/alpine-{version} /  # Alpine is root (ro)
  --bind {workspace_path} /workspace                   # workspace (rw)
  --tmpfs /tmp                                          # ephemeral temp
  --proc /proc --dev /dev                               # kernel fs
  --ro-bind /etc/resolv.conf /etc/resolv.conf           # DNS (when network allowed)
  --clearenv \
  --setenv HOME /workspace \
  --setenv PATH /usr/bin:/bin:/usr/local/bin:/workspace/.packages/bin \
  --setenv PIP_TARGET /workspace/.packages \
  --setenv PYTHONPATH /workspace/.packages \
  --setenv TMPDIR /tmp \
  --setenv LANG C.UTF-8 \
  --die-with-parent \
  --chdir /workspace \
  -- bash -c "{command}"
```

**Key changes:**
- Alpine rootfs is `/` (read-only) — controlled, minimal, predictable
- Workspace at `/workspace` (read-write) — clear boundary
- `/tmp` is tmpfs — ephemeral, not persisted
- `--clearenv` — no host secrets leak
- No venv — Python3 from Alpine, pip packages via `PIP_TARGET`
- No `_prepare_sandbox_root()` — no merged-usr detection, no symlinks
- HOME=/workspace — agent writes go to workspace naturally

### 3.3 No venv approach

Python3 comes from the Alpine rootfs (read-only). When agents `pip install` packages:

- `PIP_TARGET=/workspace/.packages` — pip writes packages here
- `PYTHONPATH=/workspace/.packages` — Python imports from here
- `PATH` includes `/workspace/.packages/bin` — executable scripts found here
- `PYTHONDONTWRITEBYTECODE=1` — avoids `.pyc` clutter

Packages persist across executions because `/workspace` is the host workspace directory.

---

## 4. Rootfs Provisioning

### 4.1 Version discovery

Instead of hardcoding Alpine versions, we fetch the latest:

```
GET https://dl-cdn.alpinelinux.org/alpine/latest-stable/releases/{arch}/latest-releases.yaml

→ Parse YAML, find entry with flavor="alpine-minirootfs"
→ Extract: version, file (filename), sha256
→ Download URL: https://dl-cdn.alpinelinux.org/alpine/latest-stable/releases/{arch}/{file}
→ Verify SHA-256 after download
```

The rootfs dir is named by the discovered version (e.g., `rootfs/alpine-3.23.3`).

### 4.2 Architecture detection

```python
ARCH_MAP = {
    "x86_64": "x86_64",       # Most Linux servers
    "aarch64": "aarch64",     # ARM64 Linux (Graviton, Ampere)
    "arm64": "aarch64",       # Docker on Apple Silicon reports arm64
    "armv7l": "armv7",        # Raspberry Pi 32-bit
    "i686": "x86",            # Legacy 32-bit
    "i386": "x86",
}
```

`detect_arch()` maps `platform.machine()` through `ARCH_MAP`. Unsupported architectures raise `RuntimeError` at setup time.

### 4.3 Package installation

After extracting the rootfs tarball, install packages using bwrap with the rootfs temporarily writable:

```bash
bwrap \
  --bind {rootfs_dir} / \          # rootfs WRITABLE during setup
  --proc /proc --dev /dev \
  --share-net \                     # network needed for apk
  --tmpfs /tmp \
  --ro-bind /etc/resolv.conf /etc/resolv.conf \
  --die-with-parent \
  -- /sbin/apk add --no-cache {packages}
```

After package installation, the rootfs is only ever mounted read-only.

### 4.4 Tool tiers (installed via `apk add`)

**Tier 1 — Required:**

| Alpine package | Provides |
|---|---|
| `bash` | bash shell |
| `python3` | python3 runtime |
| `py3-pip` | pip package manager |
| `coreutils` | cat, ls, cp, mv, mkdir, rm, chmod, head, tail, wc, sort, tee |
| `grep` | grep |
| `sed` | sed |

**Tier 2 — Recommended:**

| Alpine package | Provides |
|---|---|
| `findutils` | find, xargs |
| `curl` | curl |
| `wget` | wget |
| `git` | git |
| `tar` | tar |
| `unzip` | unzip |
| `jq` | jq |
| `gawk` | awk (GNU awk, not busybox) |
| `nodejs` | node |
| `npm` | npm |

### 4.5 Deployment modes

**Docker image:** Rootfs is pre-baked during `docker build`. No download needed at runtime. `ROOTFS_DIR` env var points to the baked location.

**Bare metal:** Rootfs downloaded during setup wizard (Step 1: Environment Check). Requires internet access during setup. Stored at `{pipelit_dir}/rootfs/alpine-{version}/`.

### 4.6 Concurrency safety

Multiple RQ workers may start simultaneously. `prepare_rootfs()` uses `fcntl.flock()` on a lock file:

```python
with open(rootfs_dir.parent / ".rootfs.lock", "w") as lock_file:
    fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
    if is_rootfs_ready(rootfs_dir):
        return rootfs_dir  # another worker finished first
    # ... download, extract, install ...
```

### 4.7 Version upgrades

A `.alpine-version` file in the rootfs dir records the installed version. When `get_latest_version()` returns a newer version, `is_rootfs_ready()` returns False, triggering re-preparation.

---

## 5. Files to Create

### 5.1 `platform/services/rootfs.py` (~150 lines)

```python
ALPINE_BRANCH = "latest-stable"
TIER1_PACKAGES = ["bash", "python3", "py3-pip", "coreutils", "grep", "sed"]
TIER2_PACKAGES = ["findutils", "curl", "wget", "git", "tar", "unzip", "jq", "gawk", "nodejs", "npm"]

ARCH_MAP = {
    "x86_64": "x86_64",
    "aarch64": "aarch64",
    "arm64": "aarch64",
    "armv7l": "armv7",
    "i686": "x86",
    "i386": "x86",
}
```

Functions:
- `detect_arch()` → mapped architecture string or RuntimeError
- `get_latest_version(arch)` → `(version, filename, sha256)` from `latest-releases.yaml`
- `get_rootfs_dir()` → `Path` to rootfs directory
- `is_rootfs_ready(rootfs_dir)` → bool (checks `/bin/sh`, `/usr/bin/python3`, `.alpine-version`)
- `download_rootfs(target_dir, arch)` → downloads tarball with SHA-256 verification
- `extract_rootfs(tarball, target_dir)` → `tar xzf`
- `install_packages(rootfs_dir, packages)` → `apk add` inside bwrap
- `prepare_rootfs(tier=1)` → orchestrates everything, idempotent, file-locked

### 5.2 `platform/tests/test_rootfs.py` (~120 lines)

- `test_detect_arch_x86_64` — maps correctly
- `test_detect_arch_aarch64` — maps correctly
- `test_detect_arch_arm64_maps_to_aarch64` — Docker Apple Silicon
- `test_detect_arch_unsupported_raises` — unknown arch → RuntimeError
- `test_get_latest_version` — mocked YAML fetch → version + filename + sha256
- `test_get_latest_version_no_minirootfs` — YAML without minirootfs → clear error
- `test_get_rootfs_dir_default` — derives from pipelit_dir
- `test_is_rootfs_ready_true` — prepared rootfs → True
- `test_is_rootfs_ready_false` — empty dir → False
- `test_prepare_rootfs_idempotent` — second call skips download
- `test_download_rootfs` — mocked HTTP, verifies tarball saved
- `test_download_rootfs_checksum_mismatch` — bad SHA-256 → raises error
- `test_install_packages` — mocked subprocess
- `test_version_upgrade` — old version file → re-prepares

---

## 6. Files to Modify

### 6.1 `platform/components/sandboxed_backend.py`

**Delete entirely:**
- `_prepare_sandbox_root()` function (lines 36-72)

**Rewrite `_build_bwrap_command()`** (lines 75-130):
- New required param: `rootfs_dir: str`
- `--ro-bind rootfs_dir /` replaces `--bind workspace /` + all host binds
- `--bind workspace /workspace` for workspace
- `--tmpfs /tmp` for ephemeral temp
- `--clearenv` + explicit env vars
- `/etc/resolv.conf` ro-bind only when `allow_network=True`
- Skill paths via `extra_ro_binds` — bwrap overlays on top of rootfs
- No merged-usr handling, no /etc entries, no /lib64 checks

**Modify `SandboxedShellBackend.__init__()`:**
- Add `self._rootfs_dir: str | None = None`

**Modify `SandboxedShellBackend.execute()`:**
- Lazy rootfs init on first call
- Pass `rootfs_dir` to `_build_bwrap_command()`

### 6.2 `platform/components/deep_agent.py`

- **Delete** `_ensure_workspace_venv()` function (lines 31-60)
- **Remove** `_ensure_workspace_venv(root_dir)` call from `_build_backend()` (line 77)

### 6.3 `platform/config.py`

- Add: `ROOTFS_DIR: str = ""` (resolved at runtime)

### 6.4 `platform/tests/test_sandboxed_backend.py`

**Delete:**
- `TestPrepareSandboxRoot` class
- `TestPythonExecution._setup_venv` fixture
- `TestEnsureWorkspaceVenv` class
- Tests expecting writes to arbitrary paths to persist

**Rewrite `TestBwrapCommand`:**
- Verify `--ro-bind rootfs /` + `--bind workspace /workspace`
- Verify `--tmpfs /tmp`, `--clearenv`
- Verify env vars: HOME=/workspace, PIP_TARGET, PYTHONPATH

**Rewrite `TestSandboxedExecution`** (skipif no bwrap):
- Write to `/workspace/test.txt` → persists
- Write to `/root/evil` → fails (read-only rootfs)
- Write to `/tmp/test.txt` → does NOT persist (tmpfs)
- `python3 --version` → works (Alpine's musl python)
- `pip install` → goes to `/workspace/.packages`

### 6.5 `platform/tests/test_deep_agent.py`

- Remove references to `_ensure_workspace_venv`
- Remove assertions checking `.venv` directory creation

---

## 7. Breaking Changes

| Before | After |
|---|---|
| Workspace is `/` — writes to ANY path persist | Only `/workspace` is writable |
| `/tmp` writes persist in workspace | `/tmp` is tmpfs, ephemeral |
| HOME=/ | HOME=/workspace |
| Host glibc python3 + venv | Alpine musl python3, no venv |
| PATH includes `/.venv/bin` | PATH includes `/workspace/.packages/bin` |
| `_prepare_sandbox_root()` scaffolding | No scaffolding needed |
| Hardcoded Alpine version | Dynamic version from `latest-releases.yaml` |

---

## 8. Potential Issues

1. **musl vs glibc** — Some pip packages with C extensions may lack musl wheels. Mitigation: pre-install common ones via `apk add py3-numpy` etc. in rootfs Tier 2.
2. **Skill path mounting** — bwrap needs mount points to exist in rootfs. `prepare_rootfs()` creates `/skills` and `/home` dirs. Skill dirs mounted at their absolute host path via `--ro-bind`.
3. **Agent prompt updates** — Deep agent system prompts should mention HOME=/workspace. The capability context injection (from sandbox_mode_config.md Section 4.4) handles this.
4. **Network during rootfs setup** — `apk add` needs internet. Setup wizard must have network access. In Docker, rootfs is pre-baked so no runtime download needed.
5. **Rootfs disk space** — ~50-100MB after Tier 1+2 packages installed. Shared across all workspaces (read-only). Negligible compared to workspace contents.
6. **First execution latency** — On bare metal, first sandbox execution triggers rootfs download (~10s). Subsequent executions use cached rootfs. Setup wizard pre-triggers this.

---

## 9. Verification

1. **Unit tests**: `python -m pytest tests/test_rootfs.py tests/test_sandboxed_backend.py -v`
2. **Integration test** (requires bwrap + rootfs): verify echo, file write to /workspace, python3 execution, pip install, read-only rootfs rejection
3. **Manual test**: run a deep_agent workflow on the canvas, verify sandboxed execution works with Alpine rootfs
4. **Docker test**: build Docker image with pre-baked rootfs, verify container mode still works (no rootfs needed in container mode)
5. **Architecture test**: verify `detect_arch()` on x86_64 and aarch64 (CI runs on x86_64, aarch64 tested via mock)
