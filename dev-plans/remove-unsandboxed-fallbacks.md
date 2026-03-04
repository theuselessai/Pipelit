# Dev Plan: Remove Unsandboxed Fallbacks (run_command, code)

**Status:** Planned for Phase 1.6 (v0.2.0)
**Effort:** 1-2 days
**Priority:** Critical security hardening
**Architect:** Deep Agent

---

## Problem Statement

The `run_command` and `code` component tools have fallback code paths that execute outside the sandbox when certain conditions aren't met. This is a critical security vulnerability.

**Current State:**
```python
# ❌ UNSAFE: Falls back to unsandboxed execution
def run_command(command):
    if workspace_exists:
        return backend.execute(command)  # ✅ SAFE (sandbox)
    else:
        return subprocess.run(command, shell=True)  # ❌ UNSAFE (no sandbox!)

def code(python_code):
    if workspace_exists:
        return backend.execute(["python3", "-c", python_code])  # ✅ SAFE
    else:
        return subprocess.run(["python3", "-c", python_code])  # ❌ UNSAFE
```

**Why This Is Bad:**

An agent can execute arbitrary code with full system access:
- Install malware or backdoors
- Read sensitive files (API keys, database credentials)
- Access other users' data (in multi-user deployments)
- Modify or delete the platform itself
- Pivot to other systems on the network

**Desired State:**
- ✅ Require workspace for ANY agent-controlled execution
- ✅ Return clear error if workspace doesn't exist
- ✅ No unsandboxed fallbacks anywhere
- ✅ Security > convenience

---

## Solution: Fail Fast Instead of Fallback

Replace all unsandboxed `subprocess.run()` fallbacks with explicit errors:

```python
# ✅ SAFE: Always sandboxed or error
def run_command(command):
    if not workspace_exists:
        raise ValueError("Workspace required to execute commands")
    return backend.execute(command)

def code(python_code):
    if not workspace_exists:
        raise ValueError("Workspace required to execute code")
    return backend.execute(["python3", "-c", python_code])
```

---

## Implementation Steps

### Step 1: Identify All Fallbacks (2 hours)

**Search for:**
1. `subprocess.run()` calls in component files
2. Fallback patterns (if workspace else subprocess)
3. Any other unsandboxed execution paths

**Files to check:**
- `platform/components/run_command.py`
- `platform/components/code.py`
- `platform/components/*.py` (all components)
- `platform/services/*.py` (any service-level fallbacks)

**Commands:**
```bash
grep -r "subprocess.run" platform/components/
grep -r "subprocess.Popen" platform/components/
grep -r "os.system" platform/
grep -r "exec(" platform/
```

### Step 2: Fix run_command.py (1-2 hours)

**File:** `platform/components/run_command.py`

**Current code (hypothetical):**
```python
def run_command(command: str, workspace_id: str = None):
    """Execute shell command in agent workspace."""
    if workspace_id and backend_exists:
        result = backend.execute(command, workspace_id)
        return {
            "stdout": result.stdout,
            "stderr": result.stderr,
            "return_code": result.returncode
        }
    else:
        # ❌ FALLBACK: Dangerous!
        result = subprocess.run(command, shell=True, capture_output=True)
        return {
            "stdout": result.stdout.decode(),
            "stderr": result.stderr.decode(),
            "return_code": result.returncode
        }
```

**Fixed code:**
```python
def run_command(command: str, workspace_id: str = None):
    """Execute shell command in agent workspace."""
    if not workspace_id or not backend_exists:
        raise ValueError(
            "Workspace required to execute commands. "
            "Agent-controlled execution must run inside sandbox."
        )
    
    result = backend.execute(command, workspace_id)
    return {
        "stdout": result.stdout,
        "stderr": result.stderr,
        "return_code": result.returncode
    }
```

**Changes:**
- Remove subprocess fallback (~5 lines deleted)
- Add validation check (~3 lines added)
- Add clear error message (~2 lines)

### Step 3: Fix code.py (1-2 hours)

**File:** `platform/components/code.py`

**Current code (hypothetical):**
```python
def code_node(python_code: str, workspace_id: str = None):
    """Execute Python code in agent workspace."""
    if workspace_id and backend_exists:
        result = backend.execute(["python3", "-c", python_code], workspace_id)
        return {
            "output": result.stdout,
            "error": result.stderr,
            "success": result.returncode == 0
        }
    else:
        # ❌ FALLBACK: Dangerous!
        result = subprocess.run(
            ["python3", "-c", python_code],
            capture_output=True
        )
        return {
            "output": result.stdout.decode(),
            "error": result.stderr.decode(),
            "success": result.returncode == 0
        }
```

**Fixed code:**
```python
def code_node(python_code: str, workspace_id: str = None):
    """Execute Python code in agent workspace."""
    if not workspace_id or not backend_exists:
        raise ValueError(
            "Workspace required to execute code. "
            "Agent-controlled execution must run inside sandbox."
        )
    
    result = backend.execute(["python3", "-c", python_code], workspace_id)
    return {
        "output": result.stdout,
        "error": result.stderr,
        "success": result.returncode == 0
    }
```

**Changes:**
- Remove subprocess fallback (~5 lines deleted)
- Add validation check (~3 lines added)
- Add clear error message (~2 lines)

### Step 4: Audit Other Components (2-3 hours)

**Check all other components for fallbacks:**

| Component | Action |
|-----------|--------|
| `platform/components/http_request.py` | Remove tool (Phase 1.1) |
| `platform/components/web_search.py` | Remove tool (Phase 1.1) |
| `platform/components/calculator.py` | Remove tool (Phase 1.1) |
| `platform/components/datetime_tool.py` | Remove tool (Phase 1.1) |
| `platform/components/platform_api.py` | Harden: lock base_url to platform address only |
| Other components | Audit for unsandboxed execution |

**For platform_api.py hardening:**
```python
# Current: ❌ Could call external APIs
base_url = config.get("API_BASE_URL", "https://api.example.com")

# Fixed: ✅ Only allow platform's own API
PLATFORM_BASE_URL = os.getenv("PLATFORM_BASE_URL", "http://localhost:8000")
base_url = PLATFORM_BASE_URL  # Never allow override
```

### Step 5: Write Tests (2-3 hours)

**Unit tests** (`tests/test_secure_execution.py`):

```python
def test_run_command_requires_workspace():
    """Verify run_command fails without workspace."""
    with pytest.raises(ValueError) as exc:
        run_command("ls", workspace_id=None)
    assert "Workspace required" in str(exc.value)

def test_code_requires_workspace():
    """Verify code execution fails without workspace."""
    with pytest.raises(ValueError) as exc:
        code_node("print(1)", workspace_id=None)
    assert "Workspace required" in str(exc.value)

def test_run_command_with_workspace():
    """Verify run_command works with valid workspace."""
    result = run_command("echo test", workspace_id="valid-id")
    assert result["return_code"] == 0
    assert "test" in result["stdout"]

def test_code_with_workspace():
    """Verify code execution works with valid workspace."""
    result = code_node("print('hello')", workspace_id="valid-id")
    assert result["success"]
    assert "hello" in result["output"]
```

**Integration test** (`tests/test_agent_execution_security.py`):
```python
def test_agent_cannot_execute_without_workspace():
    """Verify agents are restricted to sandbox."""
    agent = create_agent()
    workflow = create_workflow([
        agent_node(agent),  # No workspace
        run_command_node("rm -rf /")  # Malicious command
    ])
    
    # Execution should fail with workspace error
    with pytest.raises(ValueError) as exc:
        execute_workflow(workflow)
    assert "Workspace required" in str(exc.value)
```

### Step 6: Document Changes (1 hour)

**Update:**
- `docs/security/agent-execution.md` — explain sandbox requirement
- `docs/migration/v0.1-to-v0.2-breaking-changes.md` — note error behavior change
- `platform/components/run_command.py` — docstring update
- `platform/components/code.py` — docstring update

**Example docstring:**
```python
"""Execute Python code in agent workspace.

**SECURITY:** Agent-controlled code execution MUST run inside a sandbox.
If no workspace is available, this raises an error rather than falling back
to unsandboxed execution.

Args:
    python_code: Python code to execute
    workspace_id: Required. Workspace to execute in.

Raises:
    ValueError: If workspace_id is None or invalid

Returns:
    Dict with keys: output, error, success
"""
```

---

## Timeline

- **Day 1 Morning:** Steps 1-2 (identify + fix run_command) — 3 hours
- **Day 1 Afternoon:** Step 3 (fix code) — 2 hours
- **Day 2 Morning:** Step 4 (audit other components) — 2-3 hours
- **Day 2 Afternoon:** Steps 5-6 (tests + docs) — 3-4 hours

**Total: 1-2 days**

---

## Breaking Changes

**This is a v0.2.0 breaking change.** Existing workflows that rely on unsandboxed fallbacks will fail:

**Old behavior:**
```python
# Worked even without workspace
result = run_command("ls")  # ✅ Returned data
```

**New behavior:**
```python
# Fails if no workspace
result = run_command("ls")  # ❌ ValueError: Workspace required
```

**Migration path:**
- Users must explicitly create workflows with workspace contexts
- Document in migration guide
- Provide error message pointing to docs

---

## Success Criteria

- [ ] No subprocess fallbacks in run_command or code
- [ ] Both require workspace or raise ValueError
- [ ] All other components audited
- [ ] platform_api.py base_url hardened
- [ ] All unit tests pass
- [ ] Integration tests pass
- [ ] Documentation updated
- [ ] No unsandboxed execution paths remain

---

## Notes

- This is a **critical security fix** for Phase 1
- Sandboxing is the core security model
- No compromises on this (security > convenience)
- Error message should be clear and helpful
- Migration guide will help users adapt workflows

---

## Risk Assessment

| Risk | Severity | Mitigation |
|------|----------|-----------|
| Breaks existing workflows | Medium | Migration guide + clear error message |
| Agents can't fallback | Low | This is the point (security) |
| Performance impact | Low | No impact (still uses sandbox) |
| Unforeseen execution paths | Medium | Thorough audit in Step 4 |

