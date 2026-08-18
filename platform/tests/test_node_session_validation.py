"""The session handle on binary_op / binary_auth nodes is validated on write.

`extra_config["session"]` is passed straight to the binary as `--session
<value>` (components/binary_op.py) and used by the binary DIRECTLY AS A
FILENAME inside its credential store, which is SHARED ACROSS ALL BINARIES by
design. A crafted handle here is not a cosmetics problem — it is a path into
another binary's stored identities. This suite plants exactly the violations
that guard must catch, and pins the two live-data session values ("agent_user",
"admin1") that must keep working.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def app(db):
    """A test FastAPI app with the DB dependency overridden."""
    from database import get_db
    from main import app as _app

    def _override_get_db():
        try:
            yield db
        finally:
            pass

    _app.dependency_overrides[get_db] = _override_get_db
    yield _app
    _app.dependency_overrides.clear()


@pytest.fixture
def auth_client(app, api_key):
    client = TestClient(app)
    client.headers["Authorization"] = f"Bearer {api_key.key}"
    return client


def _post_node(client, slug, node_id, component_type="binary_op", **extra_config):
    return client.post(f"/api/v1/workflows/{slug}/nodes/", json={
        "node_id": node_id,
        "component_type": component_type,
        # binary is left empty: the allowlist check on `binary` short-circuits
        # for a falsy value, so these tests exercise the session check alone.
        "config": {"extra_config": {"binary": "", **extra_config}},
    })


class TestSessionValidationOnCreate:
    def test_a_traversal_handle_is_refused(self, auth_client, workflow):
        resp = _post_node(auth_client, workflow.slug, "n1", session="../../../../etc/passwd")
        assert resp.status_code == 422
        assert "session" in resp.json()["detail"].lower()

    def test_a_65_character_handle_is_refused(self, auth_client, workflow):
        resp = _post_node(auth_client, workflow.slug, "n1", session="a" * 65)
        assert resp.status_code == 422

    def test_a_64_character_handle_is_accepted(self, auth_client, workflow):
        resp = _post_node(auth_client, workflow.slug, "n1", session="a" * 64)
        assert resp.status_code == 201, resp.json()

    def test_a_handle_starting_with_a_dot_is_refused(self, auth_client, workflow):
        resp = _post_node(auth_client, workflow.slug, "n1", session=".hidden")
        assert resp.status_code == 422

    def test_a_handle_starting_with_a_dash_is_refused(self, auth_client, workflow):
        resp = _post_node(auth_client, workflow.slug, "n1", session="-x")
        assert resp.status_code == 422

    def test_an_absent_session_is_accepted(self, auth_client, workflow):
        resp = auth_client.post(f"/api/v1/workflows/{workflow.slug}/nodes/", json={
            "node_id": "n1", "component_type": "binary_op",
            "config": {"extra_config": {"binary": ""}},
        })
        assert resp.status_code == 201, resp.json()

    def test_an_empty_session_is_accepted(self, auth_client, workflow):
        resp = _post_node(auth_client, workflow.slug, "n1", session="")
        assert resp.status_code == 201, resp.json()

    @pytest.mark.parametrize("session", ["agent_user", "admin1"])
    def test_the_live_session_values_are_accepted(self, auth_client, workflow, session):
        """Regression guard: existing saved nodes carry these two values —
        this proves the guard does not lock out real, already-stored data."""
        resp = _post_node(auth_client, workflow.slug, f"n_{session}", session=session)
        assert resp.status_code == 201, resp.json()

    def test_binary_auth_nodes_are_checked_too(self, auth_client, workflow):
        resp = _post_node(
            auth_client, workflow.slug, "n1",
            component_type="binary_auth", session="../evil",
        )
        assert resp.status_code == 422


class TestSessionValidationOnUpdate:
    def test_changing_session_to_a_traversal_handle_is_refused(self, auth_client, workflow):
        create = _post_node(auth_client, workflow.slug, "n1", session="agent_user")
        assert create.status_code == 201, create.json()

        resp = auth_client.patch(
            f"/api/v1/workflows/{workflow.slug}/nodes/n1/",
            json={"config": {"extra_config": {"binary": "", "session": "../evil"}}},
        )
        assert resp.status_code == 422
        assert "session" in resp.json()["detail"].lower()

    def test_changing_session_to_a_valid_handle_is_accepted(self, auth_client, workflow):
        create = _post_node(auth_client, workflow.slug, "n1", session="agent_user")
        assert create.status_code == 201, create.json()

        resp = auth_client.patch(
            f"/api/v1/workflows/{workflow.slug}/nodes/n1/",
            json={"config": {"extra_config": {"binary": "", "session": "admin1"}}},
        )
        assert resp.status_code == 200, resp.json()
        assert resp.json()["config"]["extra_config"]["session"] == "admin1"
