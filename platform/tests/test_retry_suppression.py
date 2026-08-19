"""Retry suppression for failures that are not safe to repeat.

The orchestrator retries a failed node up to MAX_NODE_RETRIES. For a node that
performs an external write, a retry is a SECOND write if the first one landed —
and a timeout or killed process gives no envelope at all, so nothing can say
whether it did. Two guards exist:

- the binary's envelope carries `error.retryable`, preserved onto the raised
  exception, and `false` suppresses the retry;
- `extra_config["retryable"] = false` marks a node never-retryable outright,
  which is the only guard that also covers the no-envelope case.

These tests plant each violation and assert on the enqueue call itself — the
retry must not merely fail loudly later, it must never be scheduled.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

_platform_dir = str(Path(__file__).resolve().parent.parent)
if _platform_dir not in sys.path:
    sys.path.insert(0, _platform_dir)


def _mock_redis():
    r = MagicMock()
    r.get.return_value = None
    r.set.return_value = True
    r.delete.return_value = True
    r.incr.return_value = 1
    r.decr.return_value = 0
    r.expire.return_value = True
    r.sadd.return_value = 1
    r.smembers.return_value = set()
    r.keys.return_value = []
    return r


def _make_topo_data(node_id="node_1", component_type="binary_op"):
    return {
        "workflow_slug": "wf",
        "nodes": {
            node_id: {
                "node_id": node_id, "component_type": component_type,
                "db_id": 10, "component_config_id": 20,
                "interrupt_before": False, "interrupt_after": False,
            }
        },
        "edges_by_source": {},
        "incoming_count": {},
        "loop_bodies": {},
        "loop_return_nodes": {},
        "loop_body_all_nodes": {},
    }


def _make_mock_db(extra_config=None):
    mock_config = MagicMock()
    mock_config.system_prompt = ""
    mock_config.extra_config = extra_config if extra_config is not None else {}
    mock_db_node = MagicMock()
    mock_db_node.component_config = mock_config

    mock_db = MagicMock()
    mock_execution = MagicMock()
    mock_execution.status = "running"
    mock_execution.execution_id = "exec-1"
    mock_execution.started_at = None
    mock_db.query.return_value.filter.return_value.first.return_value = mock_execution
    mock_db.get.return_value = mock_db_node
    return mock_db, mock_execution


def _envelope(retryable=..., code="WRITE_UNVERIFIED"):
    """A failure envelope; `retryable=...` (unset) omits the field entirely."""
    error = {"code": code, "message": "the write could not be confirmed", "details": {}}
    if retryable is not ...:
        error["retryable"] = retryable
    return {"ok": False, "data": None, "proof": None, "slot_patch": None, "error": error}


_OPERATIONS = {
    "op.write": {
        "summary": "", "domain": "op", "session_required": False,
        "params": {"properties": {}}, "timeout_default_s": 5,
        "outputs": ["result"],
        # Explicitly non-mutating so tests that exercise the OTHER two
        # suppression sources (envelope verdict, config flag) in isolation
        # aren't also swept up by the "omits mutates" guard tested separately
        # below in TestBinaryOperationMutationGuard.
        "mutates": False,
    }
}

_PLUGIN = SimpleNamespace(name="fake-bin", argv=["fake-bin"], directory="/nonexistent")

# Distinguishes "caller did not pass operations, use the default catalog" from
# "caller explicitly wants operations_for() to return None" (an unresolvable
# binary/catalog), since None is itself a meaningful value to pass.
_DEFAULT_OPS = object()


def _run_binary_node(envelope=None, extra_config=None, retry_count=0, spawn=None, operations=_DEFAULT_OPS):
    """Drive execute_node_job over the REAL binary_op component.

    Only the process spawn is canned: the envelope is parsed, the exception
    built, and the retry decision taken by the production code. Returns the
    mocked queue, execution and _write_log for assertions.

    `operations` overrides the catalog entries seen by BOTH the component
    (which builds the call from them) and the orchestrator's own retry-guard
    lookup — they import `operations_for` independently, so both call sites
    must be patched for a fake catalog to be visible everywhere.
    """
    from services.orchestrator import execute_node_job

    if spawn is None:
        def spawn(*a, **kw):
            return SimpleNamespace(stdout=json.dumps(envelope), stderr="", returncode=6)

    ops = _OPERATIONS if operations is _DEFAULT_OPS else operations

    # `op.write` needs no identity, and an operation with neither a session nor
    # an environment is refused BEFORE the spawn — it leaves the binary nothing
    # to resolve a host from. These tests are about what happens to the
    # ENVELOPE, so the node has to be configured well enough to produce one.
    config = {"binary": "fake-bin", "operation": "op.write", "env": "e1"}
    config.update(extra_config or {})
    mock_db, mock_execution = _make_mock_db(extra_config=config)
    mock_q = MagicMock()

    with patch("services.orchestrator._load_topology", return_value=_make_topo_data()), \
         patch("services.orchestrator.load_state",
               return_value={"messages": [], "node_outputs": {}, "trigger": {}}), \
         patch("services.orchestrator.save_state"), \
         patch("services.orchestrator._redis", return_value=_mock_redis()), \
         patch("services.orchestrator._publish_event"), \
         patch("services.orchestrator._queue", return_value=mock_q), \
         patch("services.orchestrator._write_log") as mock_log, \
         patch("services.orchestrator._clear_stale_checkpoints"), \
         patch("components.binary_op.verified_plugin", return_value=(_PLUGIN, None)), \
         patch("components.binary_op.operations_for", return_value=ops), \
         patch("schemas.binary_catalogs.operations_for", return_value=ops), \
         patch("components.binary_op.subprocess.run", side_effect=spawn), \
         patch("database.SessionLocal", return_value=mock_db):
        execute_node_job("exec-1", "node_1", retry_count=retry_count)

    return mock_q, mock_execution, mock_log


def _run_binary_auth_node(envelope=None, extra_config=None, retry_count=0, spawn=None):
    """Drive execute_node_job over the REAL binary_auth component.

    Mirrors _run_binary_node but for the identity/environment verb surface —
    `binary_auth` reads `mutates` from the fixed VERBS table rather than a
    per-binary catalog, so there is no `operations_for` to patch here.
    """
    from services.orchestrator import execute_node_job

    if spawn is None:
        def spawn(*a, **kw):
            return SimpleNamespace(stdout=json.dumps(envelope), stderr="", returncode=6)

    config = {"binary": "fake-bin", "operation": "auth.sessionRemove", "session": "s1"}
    config.update(extra_config or {})
    mock_db, mock_execution = _make_mock_db(extra_config=config)
    mock_q = MagicMock()

    with patch("services.orchestrator._load_topology",
               return_value=_make_topo_data(component_type="binary_auth")), \
         patch("services.orchestrator.load_state",
               return_value={"messages": [], "node_outputs": {}, "trigger": {}}), \
         patch("services.orchestrator.save_state"), \
         patch("services.orchestrator._redis", return_value=_mock_redis()), \
         patch("services.orchestrator._publish_event"), \
         patch("services.orchestrator._queue", return_value=mock_q), \
         patch("services.orchestrator._write_log") as mock_log, \
         patch("services.orchestrator._clear_stale_checkpoints"), \
         patch("components.binary_auth.verified_plugin", return_value=(_PLUGIN, None)), \
         patch("components.binary_auth.subprocess.run", side_effect=spawn), \
         patch("database.SessionLocal", return_value=mock_db):
        execute_node_job("exec-1", "node_1", retry_count=retry_count)

    return mock_q, mock_execution, mock_log


def _logged_error(mock_log):
    failed_calls = [c for c in mock_log.call_args_list if "failed" in c.args]
    assert failed_calls, "no failure was written to the execution log"
    return failed_calls[0].kwargs.get("error") or ""


class TestEnvelopeVerdict:
    """The binary's own `retryable` travels envelope → exception → decision."""

    def test_a_failure_the_binary_calls_unrepeatable_is_not_reenqueued(self):
        mock_q, mock_execution, _ = _run_binary_node(_envelope(retryable=False))
        mock_q.enqueue_in.assert_not_called()
        assert mock_execution.status == "failed"

    def test_a_failure_the_binary_calls_repeatable_is_retried(self):
        """The guard discriminates — it does not blanket-disable retry."""
        mock_q, _, _ = _run_binary_node(_envelope(retryable=True))
        assert mock_q.enqueue_in.call_count == 1
        assert mock_q.enqueue_in.call_args.args[-1] == 1  # retry_count + 1

    def test_a_failure_with_no_verdict_keeps_the_default_retry(self):
        """Regression guard: an envelope that says nothing changes nothing."""
        mock_q, _, _ = _run_binary_node(_envelope())
        assert mock_q.enqueue_in.call_count == 1

    def test_the_suppression_names_the_binary_as_the_reason(self):
        """Whoever reads the execution log must not have to read the source."""
        _, _, mock_log = _run_binary_node(_envelope(retryable=False))
        assert "reported this failure as not retryable" in _logged_error(mock_log)


class TestNodeRetryableFlag:
    """`extra_config["retryable"] = false` — the node itself says never retry."""

    def test_the_flag_wins_even_when_the_exception_says_retryable_true(self):
        mock_q, mock_execution, _ = _run_binary_node(
            _envelope(retryable=True), extra_config={"retryable": False},
        )
        mock_q.enqueue_in.assert_not_called()
        assert mock_execution.status == "failed"

    def test_the_flag_covers_a_killed_process_that_left_no_envelope(self):
        """The worst case: a timeout produces nothing to read a verdict from,
        yet the first attempt may already have applied its write."""
        def hang(*a, **kw):
            raise subprocess.TimeoutExpired(cmd="x", timeout=1)

        mock_q, mock_execution, _ = _run_binary_node(
            extra_config={"retryable": False}, spawn=hang,
        )
        mock_q.enqueue_in.assert_not_called()
        assert mock_execution.status == "failed"

    def test_the_string_false_is_honoured(self):
        """extra_config is hand-edited JSON; "false" must count."""
        mock_q, _, _ = _run_binary_node(
            _envelope(retryable=True), extra_config={"retryable": "false"},
        )
        mock_q.enqueue_in.assert_not_called()

    def test_the_suppression_names_the_node_flag_as_the_reason(self):
        """Distinguishable from the binary's verdict in the same log."""
        _, _, mock_log = _run_binary_node(
            _envelope(), extra_config={"retryable": False},
        )
        assert "marked non-retryable" in _logged_error(mock_log)

    def test_the_flag_is_not_binary_specific(self):
        """Any component type can carry it — the hazard is the side effect,
        not the transport."""
        from services.orchestrator import execute_node_job

        mock_db, _ = _make_mock_db(extra_config={"retryable": False})
        mock_q = MagicMock()

        def _raise(*a, **kw):
            raise RuntimeError("request sent; response never arrived")

        with patch("services.orchestrator._load_topology",
                   return_value=_make_topo_data(component_type="agent")), \
             patch("services.orchestrator.load_state",
                   return_value={"messages": [], "node_outputs": {}, "trigger": {}}), \
             patch("services.orchestrator.save_state"), \
             patch("services.orchestrator._redis", return_value=_mock_redis()), \
             patch("services.orchestrator._publish_event"), \
             patch("services.orchestrator._queue", return_value=mock_q), \
             patch("services.orchestrator._write_log"), \
             patch("services.orchestrator._clear_stale_checkpoints"), \
             patch("components.get_component_factory", return_value=lambda node: _raise), \
             patch("database.SessionLocal", return_value=mock_db):
            execute_node_job("exec-1", "node_1", retry_count=0)

        mock_q.enqueue_in.assert_not_called()


class TestDefaultBehaviourUnchanged:
    """Nothing that retries today stops retrying."""

    def _run_plain_node(self, retry_count):
        from services.orchestrator import execute_node_job

        mock_db, mock_execution = _make_mock_db()
        mock_q = MagicMock()

        def _raise(*a, **kw):
            raise RuntimeError("transient failure")

        with patch("services.orchestrator._load_topology",
                   return_value=_make_topo_data(component_type="agent")), \
             patch("services.orchestrator.load_state",
                   return_value={"messages": [], "node_outputs": {}, "trigger": {}}), \
             patch("services.orchestrator.save_state"), \
             patch("services.orchestrator._redis", return_value=_mock_redis()), \
             patch("services.orchestrator._publish_event"), \
             patch("services.orchestrator._queue", return_value=mock_q), \
             patch("services.orchestrator._write_log"), \
             patch("services.orchestrator._clear_stale_checkpoints"), \
             patch("components.get_component_factory", return_value=lambda node: _raise), \
             patch("database.SessionLocal", return_value=mock_db):
            execute_node_job("exec-1", "node_1", retry_count=retry_count)

        return mock_q, mock_execution

    def test_a_plain_node_still_retries(self):
        mock_q, _ = self._run_plain_node(retry_count=0)
        assert mock_q.enqueue_in.call_count == 1
        assert mock_q.enqueue_in.call_args.args[-1] == 1

    def test_retries_still_stop_at_the_cap(self):
        from services.orchestrator import MAX_NODE_RETRIES

        mock_q, mock_execution = self._run_plain_node(retry_count=MAX_NODE_RETRIES)
        mock_q.enqueue_in.assert_not_called()
        assert mock_execution.status == "failed"

    def test_a_retryable_true_string_changes_nothing(self):
        """"true" in config is 'stated, and permissive' — default behaviour."""
        mock_q, _, _ = _run_binary_node(
            _envelope(retryable=True), extra_config={"retryable": "true"},
        )
        assert mock_q.enqueue_in.call_count == 1


class TestConfigFlagParsing:
    def test_only_an_explicit_false_forbids(self):
        from services.orchestrator import _config_forbids_retry

        assert _config_forbids_retry({"retryable": False}) is True
        assert _config_forbids_retry({"retryable": "false"}) is True
        assert _config_forbids_retry({"retryable": "FALSE"}) is True
        assert _config_forbids_retry({"retryable": " false "}) is True
        assert _config_forbids_retry({"retryable": True}) is False
        assert _config_forbids_retry({"retryable": "true"}) is False
        assert _config_forbids_retry({"retryable": None}) is False
        assert _config_forbids_retry({"retryable": 0}) is False
        assert _config_forbids_retry({}) is False
        assert _config_forbids_retry(None) is False


def _op(mutates=...):
    """A single-operation catalog entry; `mutates=...` (unset) omits the key."""
    entry = {
        "summary": "", "domain": "op", "session_required": False,
        "params": {"properties": {}}, "timeout_default_s": 5,
        "outputs": ["result"],
    }
    if mutates is not ...:
        entry["mutates"] = mutates
    return {"op.write": entry}


class TestBinaryOperationMutationGuard:
    """The third suppression source: a `binary_op` node's configured operation
    declares (or fails to declare) whether it mutates state outside the binary.
    """

    def test_an_operation_declared_mutating_is_not_reenqueued(self):
        mock_q, mock_execution, _ = _run_binary_node(_envelope(), operations=_op(mutates=True))
        mock_q.enqueue_in.assert_not_called()
        assert mock_execution.status == "failed"

    def test_an_operation_declared_non_mutating_is_retried(self):
        """The guard discriminates — it does not blanket-disable binary retry."""
        mock_q, _, _ = _run_binary_node(_envelope(), operations=_op(mutates=False))
        assert mock_q.enqueue_in.call_count == 1
        assert mock_q.enqueue_in.call_args.args[-1] == 1

    def test_an_operation_that_omits_mutates_is_not_retried(self):
        """Unknown-means-mutating: the catalog simply doesn't say."""
        mock_q, mock_execution, _ = _run_binary_node(_envelope(), operations=_op())
        mock_q.enqueue_in.assert_not_called()
        assert mock_execution.status == "failed"

    def test_an_unknown_operation_is_not_retried(self):
        """The configured operation isn't in the (resolvable) catalog at all."""
        mock_q, mock_execution, _ = _run_binary_node(_envelope(), operations={})
        mock_q.enqueue_in.assert_not_called()
        assert mock_execution.status == "failed"

    def test_an_unregistered_binary_is_not_retried(self):
        """operations_for() itself returns None — no catalog to consult."""
        mock_q, mock_execution, _ = _run_binary_node(_envelope(), operations=None)
        mock_q.enqueue_in.assert_not_called()
        assert mock_execution.status == "failed"

    def test_the_suppression_names_declared_mutating_distinctly(self):
        _, _, mock_log = _run_binary_node(_envelope(), operations=_op(mutates=True))
        error = _logged_error(mock_log)
        assert "declared mutating" in error
        assert "could not be determined" not in error

    def test_the_suppression_names_unknown_status_distinctly(self):
        _, _, mock_log = _run_binary_node(_envelope(), operations=_op())
        error = _logged_error(mock_log)
        assert "could not be determined" in error
        assert error.count("declared mutating") == 0

    def test_the_envelope_verdict_still_wins_ahead_of_the_binary_guard(self):
        """A repeatable envelope verdict is the OUTER guard's business; this
        third source only engages once the first two have nothing to say —
        but an operation declared mutating still suppresses even when the
        envelope itself said nothing (regression: order of the three checks)."""
        mock_q, _, mock_log = _run_binary_node(_envelope(retryable=True), operations=_op(mutates=True))
        # The envelope explicitly permitted retry, but the operation's own
        # mutating declaration still forbids it — envelope permission is not
        # the last word.
        mock_q.enqueue_in.assert_not_called()
        assert "declared mutating" in _logged_error(mock_log)


class TestBinaryAuthMutationGuard:
    """Same guard, fed from the fixed VERBS table instead of a catalog."""

    def test_a_mutating_verb_is_not_reenqueued(self):
        mock_q, mock_execution, _ = _run_binary_auth_node(
            _envelope(), extra_config={"operation": "auth.sessionRemove", "session": "s1"},
        )
        mock_q.enqueue_in.assert_not_called()
        assert mock_execution.status == "failed"

    def test_a_read_only_verb_is_retried(self):
        mock_q, _, _ = _run_binary_auth_node(
            _envelope(), extra_config={"operation": "auth.sessionList"},
        )
        assert mock_q.enqueue_in.call_count == 1
        assert mock_q.enqueue_in.call_args.args[-1] == 1

    def test_env_add_is_not_reenqueued(self):
        mock_q, mock_execution, _ = _run_binary_auth_node(
            _envelope(),
            extra_config={"operation": "env.add", "name": "e1", "url": "http://x", "kind": "uat"},
        )
        mock_q.enqueue_in.assert_not_called()
        assert mock_execution.status == "failed"

    def test_env_list_is_retried(self):
        mock_q, _, _ = _run_binary_auth_node(
            _envelope(), extra_config={"operation": "env.list"},
        )
        assert mock_q.enqueue_in.call_count == 1


class TestNonBinaryNodesUnaffected:
    """The new guard only ever looks at binary_op / binary_auth nodes."""

    def test_the_helper_is_a_no_op_for_other_component_types(self):
        from services.orchestrator import _binary_no_retry_reason

        assert _binary_no_retry_reason("agent", {"binary": "fake-bin", "operation": "op.write"}) is None
        assert _binary_no_retry_reason(None, {}) is None

    def test_a_plain_node_still_retries_even_with_binary_shaped_config(self):
        """Regression: only the component TYPE gates this guard, never the
        mere presence of `binary`/`operation` keys in extra_config."""
        from services.orchestrator import execute_node_job

        mock_db, _ = _make_mock_db(extra_config={"binary": "fake-bin", "operation": "op.write"})
        mock_q = MagicMock()

        def _raise(*a, **kw):
            raise RuntimeError("transient failure")

        with patch("services.orchestrator._load_topology",
                   return_value=_make_topo_data(component_type="agent")), \
             patch("services.orchestrator.load_state",
                   return_value={"messages": [], "node_outputs": {}, "trigger": {}}), \
             patch("services.orchestrator.save_state"), \
             patch("services.orchestrator._redis", return_value=_mock_redis()), \
             patch("services.orchestrator._publish_event"), \
             patch("services.orchestrator._queue", return_value=mock_q), \
             patch("services.orchestrator._write_log"), \
             patch("services.orchestrator._clear_stale_checkpoints"), \
             patch("components.get_component_factory", return_value=lambda node: _raise), \
             patch("database.SessionLocal", return_value=mock_db):
            execute_node_job("exec-1", "node_1", retry_count=0)

        assert mock_q.enqueue_in.call_count == 1


class TestBinaryNoRetryReasonHelper:
    """Direct unit coverage of the resolution logic, independent of the full
    execute_node_job plumbing."""

    def test_mutates_true_forbids(self):
        from services.orchestrator import _binary_no_retry_reason

        with patch("schemas.binary_catalogs.operations_for", return_value=_op(mutates=True)):
            reason = _binary_no_retry_reason("binary_op", {"binary": "b", "operation": "op.write"})
        assert reason is not None
        assert "declared mutating" in reason

    def test_mutates_false_permits(self):
        from services.orchestrator import _binary_no_retry_reason

        with patch("schemas.binary_catalogs.operations_for", return_value=_op(mutates=False)):
            reason = _binary_no_retry_reason("binary_op", {"binary": "b", "operation": "op.write"})
        assert reason is None

    def test_missing_mutates_forbids(self):
        from services.orchestrator import _binary_no_retry_reason

        with patch("schemas.binary_catalogs.operations_for", return_value=_op()):
            reason = _binary_no_retry_reason("binary_op", {"binary": "b", "operation": "op.write"})
        assert reason is not None
        assert "could not be determined" in reason

    def test_unresolvable_catalog_forbids(self):
        from services.orchestrator import _binary_no_retry_reason

        with patch("schemas.binary_catalogs.operations_for", return_value=None):
            reason = _binary_no_retry_reason("binary_op", {"binary": "b", "operation": "op.write"})
        assert reason is not None

    def test_binary_auth_mutating_verb_forbids(self):
        from services.orchestrator import _binary_no_retry_reason

        reason = _binary_no_retry_reason("binary_auth", {"binary": "b", "operation": "auth.login"})
        assert reason is not None

    def test_binary_auth_read_only_verb_permits(self):
        from services.orchestrator import _binary_no_retry_reason

        reason = _binary_no_retry_reason("binary_auth", {"binary": "b", "operation": "auth.sessionList"})
        assert reason is None

    def test_binary_auth_unknown_verb_forbids(self):
        from services.orchestrator import _binary_no_retry_reason

        reason = _binary_no_retry_reason("binary_auth", {"binary": "b", "operation": "not.a.verb"})
        assert reason is not None
