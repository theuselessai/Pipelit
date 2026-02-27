"""Tests for the Workspace API."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

_platform_dir = str(Path(__file__).resolve().parent.parent)
if _platform_dir not in sys.path:
    sys.path.insert(0, _platform_dir)

from models.workspace import Workspace


@pytest.fixture
def app(db):
    from main import app as _app
    from database import get_db

    def _override_get_db():
        yield db

    _app.dependency_overrides[get_db] = _override_get_db
    yield _app
    _app.dependency_overrides.clear()


@pytest.fixture
def client(app):
    return TestClient(app)


@pytest.fixture
def auth_client(client, api_key):
    client.headers["Authorization"] = f"Bearer {api_key.key}"
    return client


@pytest.fixture
def workspace(db, user_profile, tmp_path):
    ws = Workspace(
        name="test-workspace",
        path=str(tmp_path / "workspaces" / "test-workspace"),
        user_profile_id=user_profile.id,
    )
    db.add(ws)
    db.commit()
    db.refresh(ws)
    return ws


@pytest.fixture
def default_workspace(db, user_profile, tmp_path):
    ws = Workspace(
        name="default",
        path=str(tmp_path / "workspaces" / "default"),
        user_profile_id=user_profile.id,
    )
    db.add(ws)
    db.commit()
    db.refresh(ws)
    return ws


# -- List --

def test_list_workspaces_empty(auth_client):
    resp = auth_client.get("/api/v1/workspaces/")
    assert resp.status_code == 200
    data = resp.json()
    assert data["items"] == []
    assert data["total"] == 0


def test_list_workspaces(auth_client, workspace):
    resp = auth_client.get("/api/v1/workspaces/")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["items"][0]["name"] == "test-workspace"


def test_list_workspaces_includes_env_vars(auth_client, workspace):
    resp = auth_client.get("/api/v1/workspaces/")
    data = resp.json()
    assert "env_vars" in data["items"][0]
    assert data["items"][0]["env_vars"] == []


# -- Create --

def test_create_workspace(auth_client, tmp_path, monkeypatch):
    monkeypatch.setattr("api.workspaces.get_pipelit_dir", lambda: tmp_path)
    resp = auth_client.post("/api/v1/workspaces/", json={"name": "new-ws"})
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "new-ws"
    assert "new-ws" in data["path"]
    assert data["allow_network"] is False
    assert data["env_vars"] == []
    # Directory should be created
    assert Path(data["path"]).exists()
    assert (Path(data["path"]) / ".tmp").exists()


def test_create_workspace_with_path(auth_client, tmp_path, monkeypatch):
    monkeypatch.setattr("api.workspaces.get_pipelit_dir", lambda: tmp_path)
    custom_path = str(tmp_path / "workspaces" / "custom-workspace")
    resp = auth_client.post("/api/v1/workspaces/", json={"name": "custom", "path": custom_path, "allow_network": True})
    assert resp.status_code == 201
    data = resp.json()
    assert data["path"] == custom_path
    assert data["allow_network"] is True


def test_create_workspace_with_env_vars(auth_client, tmp_path, monkeypatch):
    monkeypatch.setattr("api.workspaces.get_pipelit_dir", lambda: tmp_path)
    env_vars = [
        {"key": "FOO", "value": "bar", "source": "raw"},
        {"key": "BAZ", "value": "qux", "source": "raw"},
    ]
    resp = auth_client.post("/api/v1/workspaces/", json={"name": "env-ws", "env_vars": env_vars})
    assert resp.status_code == 201
    data = resp.json()
    assert len(data["env_vars"]) == 2
    assert data["env_vars"][0]["key"] == "FOO"
    assert data["env_vars"][0]["value"] == "bar"
    assert data["env_vars"][1]["key"] == "BAZ"


def test_create_workspace_duplicate_name(auth_client, workspace):
    resp = auth_client.post("/api/v1/workspaces/", json={"name": "test-workspace"})
    assert resp.status_code == 409


def test_create_workspace_path_traversal_blocked(auth_client):
    resp = auth_client.post("/api/v1/workspaces/", json={"name": "evil", "path": "/etc/evil-workspace"})
    assert resp.status_code == 400
    assert "must be under" in resp.json()["detail"]


# -- Get --

def test_get_workspace(auth_client, workspace):
    resp = auth_client.get(f"/api/v1/workspaces/{workspace.id}/")
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "test-workspace"
    assert "env_vars" in data


def test_get_workspace_not_found(auth_client):
    resp = auth_client.get("/api/v1/workspaces/9999/")
    assert resp.status_code == 404


# -- Update --

def test_update_workspace(auth_client, workspace):
    resp = auth_client.patch(f"/api/v1/workspaces/{workspace.id}/", json={"allow_network": True})
    assert resp.status_code == 200
    assert resp.json()["allow_network"] is True


def test_update_workspace_env_vars(auth_client, workspace):
    env_vars = [{"key": "SECRET", "value": "s3cret", "source": "raw"}]
    resp = auth_client.patch(f"/api/v1/workspaces/{workspace.id}/", json={"env_vars": env_vars})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["env_vars"]) == 1
    assert data["env_vars"][0]["key"] == "SECRET"
    assert data["env_vars"][0]["value"] == "s3cret"


def test_update_workspace_env_vars_replace(auth_client, workspace):
    """Updating env_vars replaces the entire list."""
    env1 = [{"key": "A", "value": "1", "source": "raw"}]
    auth_client.patch(f"/api/v1/workspaces/{workspace.id}/", json={"env_vars": env1})
    env2 = [{"key": "B", "value": "2", "source": "raw"}, {"key": "C", "value": "3", "source": "raw"}]
    resp = auth_client.patch(f"/api/v1/workspaces/{workspace.id}/", json={"env_vars": env2})
    data = resp.json()
    assert len(data["env_vars"]) == 2
    assert data["env_vars"][0]["key"] == "B"


def test_update_workspace_env_vars_credential_source(auth_client, workspace):
    env_vars = [{"key": "API_KEY", "credential_id": 1, "credential_field": "api_key", "source": "credential"}]
    resp = auth_client.patch(f"/api/v1/workspaces/{workspace.id}/", json={"env_vars": env_vars})
    assert resp.status_code == 200
    data = resp.json()
    assert data["env_vars"][0]["source"] == "credential"
    assert data["env_vars"][0]["credential_id"] == 1


# -- Delete --

def test_delete_workspace(auth_client, workspace):
    resp = auth_client.delete(f"/api/v1/workspaces/{workspace.id}/")
    assert resp.status_code == 204


def test_delete_default_workspace_blocked(auth_client, default_workspace):
    resp = auth_client.delete(f"/api/v1/workspaces/{default_workspace.id}/")
    assert resp.status_code == 403


def test_delete_workspace_not_found(auth_client):
    resp = auth_client.delete("/api/v1/workspaces/9999/")
    assert resp.status_code == 404


# -- Batch Delete --

def test_batch_delete(auth_client, workspace, default_workspace):
    resp = auth_client.post("/api/v1/workspaces/batch-delete/", json={"ids": [workspace.id, default_workspace.id]})
    assert resp.status_code == 204
    # Default should still exist
    resp2 = auth_client.get(f"/api/v1/workspaces/{default_workspace.id}/")
    assert resp2.status_code == 200
    # Other should be deleted
    resp3 = auth_client.get(f"/api/v1/workspaces/{workspace.id}/")
    assert resp3.status_code == 404


def test_batch_delete_empty(auth_client):
    resp = auth_client.post("/api/v1/workspaces/batch-delete/", json={"ids": []})
    assert resp.status_code == 204


# -- Reset Workspace --

def test_reset_workspace(auth_client, workspace, tmp_path):
    # Create workspace directory with various content
    ws_dir = Path(workspace.path)
    ws_dir.mkdir(parents=True, exist_ok=True)
    (ws_dir / ".rootfs").mkdir()
    (ws_dir / ".rootfs" / "somefile").touch()
    (ws_dir / ".venv").mkdir()
    (ws_dir / ".tmp").mkdir()
    (ws_dir / "myfile.py").touch()

    resp = auth_client.post(f"/api/v1/workspaces/{workspace.id}/reset/")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    # Everything should be gone except the re-created dirs
    assert ws_dir.exists()
    assert (ws_dir / ".tmp").exists()
    assert not (ws_dir / ".rootfs").exists()
    assert not (ws_dir / ".venv").exists()
    assert not (ws_dir / "myfile.py").exists()


def test_reset_workspace_not_found(auth_client):
    resp = auth_client.post("/api/v1/workspaces/9999/reset/")
    assert resp.status_code == 404


# -- Reset Rootfs (legacy) --

def test_reset_rootfs(auth_client, workspace, tmp_path):
    # Create a fake .rootfs directory
    rootfs_dir = Path(workspace.path) / ".rootfs"
    rootfs_dir.mkdir(parents=True)
    (rootfs_dir / "somefile").touch()
    assert rootfs_dir.exists()

    resp = auth_client.post(f"/api/v1/workspaces/{workspace.id}/reset-rootfs/")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    assert not rootfs_dir.exists()


def test_reset_rootfs_not_found(auth_client):
    resp = auth_client.post("/api/v1/workspaces/9999/reset-rootfs/")
    assert resp.status_code == 404


# -- Auth required --

def test_unauthenticated(client):
    resp = client.get("/api/v1/workspaces/")
    assert resp.status_code in (401, 403)


# -- Pagination --

def test_pagination(auth_client, db, user_profile, tmp_path):
    for i in range(5):
        ws = Workspace(name=f"ws-{i}", path=str(tmp_path / f"ws-{i}"), user_profile_id=user_profile.id)
        db.add(ws)
    db.commit()

    resp = auth_client.get("/api/v1/workspaces/?limit=2&offset=0")
    data = resp.json()
    assert data["total"] == 5
    assert len(data["items"]) == 2

    resp2 = auth_client.get("/api/v1/workspaces/?limit=2&offset=4")
    data2 = resp2.json()
    assert len(data2["items"]) == 1


# -- Default workspace auto-creation --

def test_default_workspace_model_env_vars_default(db, user_profile, tmp_path):
    """Workspace env_vars defaults to empty list."""
    ws = Workspace(
        name="env-test",
        path=str(tmp_path / "env-test"),
        user_profile_id=user_profile.id,
    )
    db.add(ws)
    db.commit()
    db.refresh(ws)
    assert ws.env_vars == []


def test_workspace_model_with_env_vars(db, user_profile, tmp_path):
    """Workspace env_vars can be set to a list of dicts."""
    ws = Workspace(
        name="env-test-2",
        path=str(tmp_path / "env-test-2"),
        user_profile_id=user_profile.id,
        env_vars=[{"key": "FOO", "value": "bar", "source": "raw"}],
    )
    db.add(ws)
    db.commit()
    db.refresh(ws)
    assert len(ws.env_vars) == 1
    assert ws.env_vars[0]["key"] == "FOO"
