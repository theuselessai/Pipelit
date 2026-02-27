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
        try:
            yield db
        finally:
            pass

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


# -- Create --

def test_create_workspace(auth_client, tmp_path, monkeypatch):
    monkeypatch.setattr("api.workspaces.get_pipelit_dir", lambda: tmp_path)
    resp = auth_client.post("/api/v1/workspaces/", json={"name": "new-ws"})
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "new-ws"
    assert "new-ws" in data["path"]
    assert data["allow_network"] is False
    # Directory should be created
    assert Path(data["path"]).exists()
    assert (Path(data["path"]) / ".tmp").exists()


def test_create_workspace_with_path(auth_client, tmp_path):
    custom_path = str(tmp_path / "custom-workspace")
    resp = auth_client.post("/api/v1/workspaces/", json={"name": "custom", "path": custom_path, "allow_network": True})
    assert resp.status_code == 201
    data = resp.json()
    assert data["path"] == custom_path
    assert data["allow_network"] is True


def test_create_workspace_duplicate_name(auth_client, workspace):
    resp = auth_client.post("/api/v1/workspaces/", json={"name": "test-workspace"})
    assert resp.status_code == 409


# -- Get --

def test_get_workspace(auth_client, workspace):
    resp = auth_client.get(f"/api/v1/workspaces/{workspace.id}/")
    assert resp.status_code == 200
    assert resp.json()["name"] == "test-workspace"


def test_get_workspace_not_found(auth_client):
    resp = auth_client.get("/api/v1/workspaces/9999/")
    assert resp.status_code == 404


# -- Update --

def test_update_workspace(auth_client, workspace):
    resp = auth_client.patch(f"/api/v1/workspaces/{workspace.id}/", json={"allow_network": True})
    assert resp.status_code == 200
    assert resp.json()["allow_network"] is True


def test_update_workspace_name(auth_client, workspace):
    resp = auth_client.patch(f"/api/v1/workspaces/{workspace.id}/", json={"name": "renamed"})
    assert resp.status_code == 200
    assert resp.json()["name"] == "renamed"


def test_update_workspace_duplicate_name(auth_client, workspace, default_workspace):
    resp = auth_client.patch(f"/api/v1/workspaces/{workspace.id}/", json={"name": "default"})
    assert resp.status_code == 409


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


# -- Reset Rootfs --

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
