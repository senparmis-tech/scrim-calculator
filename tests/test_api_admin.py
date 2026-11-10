import json
import re
import pytest
from app import save_state, default_state, load_state, current_id

def test_admin_auth_required(client):
    # Unauthenticated access to /admin redirects to /login
    res = client.get("/admin")
    assert res.status_code == 302
    assert "/login" in res.headers["Location"]

    # Unauthenticated access to /api/admin/* returns 401
    res_api = client.get("/api/admin/state")
    assert res_api.status_code == 401


def test_csrf_protection_on_post(client):
    # Authenticate without setting CSRF header on POST
    with client.session_transaction() as sess:
        sess["admin"] = True
        sess["username"] = "admin"
        sess["csrf_token"] = "valid-token"

    res = client.post("/api/admin/save", json=default_state())
    assert res.status_code == 400
    assert "token expired" in res.get_json()["error"].lower()


def test_login_flow(client):
    # GET /login to initialize session and extract CSRF token
    get_res = client.get("/login")
    assert get_res.status_code == 200
    html = get_res.data.decode("utf-8")
    m = re.search(r'name="csrf_token" value="([^"]+)"', html)
    assert m is not None
    token = m.group(1)

    # Wrong password
    res_bad = client.post(
        "/login",
        data={"username": "admin", "password": "wrong-password", "csrf_token": token}
    )
    assert res_bad.status_code == 200
    assert b"Incorrect username or password" in res_bad.data

    # Correct password ("test-password" created in conftest.py)
    # Re-fetch CSRF token if needed
    get_res2 = client.get("/login")
    m2 = re.search(r'name="csrf_token" value="([^"]+)"', get_res2.data.decode("utf-8"))
    token2 = m2.group(1)

    res_ok = client.post(
        "/login",
        data={"username": "admin", "password": "test-password", "csrf_token": token2}
    )
    assert res_ok.status_code == 302
    assert "/admin" in res_ok.headers["Location"]


def test_admin_state_and_save(admin_client, sample_state):
    headers = {"X-CSRF-Token": "valid-test-csrf-token"}

    # Get admin state
    res = admin_client.get("/api/admin/state")
    assert res.status_code == 200

    # Save state (admin_save accepts the state dict directly)
    sample_state["title"] = "Updated Scrim Title"
    res_save = admin_client.post(
        "/api/admin/save",
        json=sample_state,
        headers=headers
    )
    assert res_save.status_code == 200
    data = res_save.get_json()
    assert data["state"]["title"] == "Updated Scrim Title"

    # Verify updated state in storage
    cur = load_state()
    assert cur["title"] == "Updated Scrim Title"


def test_undo_and_redo(admin_client, sample_state):
    headers = {"X-CSRF-Token": "valid-test-csrf-token"}

    # Initial save
    sample_state["title"] = "Version 1"
    admin_client.post("/api/admin/save", json=sample_state, headers=headers)

    # Second save
    sample_state["title"] = "Version 2"
    admin_client.post("/api/admin/save", json=sample_state, headers=headers)

    # Undo
    res_undo = admin_client.post("/api/admin/undo", headers=headers)
    assert res_undo.status_code == 200

    # Redo
    res_redo = admin_client.post("/api/admin/redo", headers=headers)
    assert res_redo.status_code == 200


def test_scrim_management_lifecycle(admin_client):
    headers = {"X-CSRF-Token": "valid-test-csrf-token"}

    # Create new scrim
    res_new = admin_client.post("/api/admin/scrims/new", headers=headers)
    assert res_new.status_code == 200
    new_scrim_id = res_new.get_json()["id"]
    assert new_scrim_id

    # Switch scrim
    res_switch = admin_client.post(
        "/api/admin/scrims/switch",
        json={"id": new_scrim_id},
        headers=headers
    )
    assert res_switch.status_code == 200
    assert current_id() == new_scrim_id

    # Archive scrim
    res_archive = admin_client.post(
        "/api/admin/scrims/archive",
        json={"id": new_scrim_id, "archived": True},
        headers=headers
    )
    assert res_archive.status_code == 200
    assert res_archive.get_json()["archived"] is True

    # Delete scrim
    res_del = admin_client.post(
        "/api/admin/scrims/delete",
        json={"id": new_scrim_id},
        headers=headers
    )
    assert res_del.status_code == 200
    assert "id" in res_del.get_json()


def test_admin_backup_download(admin_client, sample_state):
    save_state(sample_state)
    res = admin_client.get("/api/admin/backup")
    assert res.status_code == 200
    assert res.content_type == "application/zip"


def test_team_logo_memory_across_new_scrims(admin_client, sample_state):
    headers = {"X-CSRF-Token": "valid-test-csrf-token"}
    logo_url = "/uploads/196bf5372a049024ce456ac4.png"

    # 1. Save a scrim where "Alpha Squad" has a logo
    sample_state["teams"][0]["logo"] = logo_url
    res1 = admin_client.post("/api/admin/save", json=sample_state, headers=headers)
    assert res1.status_code == 200
    assert res1.get_json()["team_logos"].get("alpha squad") == logo_url

    # 2. Create a brand new empty scrim
    res_new = admin_client.post(
        "/api/admin/scrims/new",
        json={"title": "Next Day Scrim", "mode": "empty"},
        headers=headers
    )
    assert res_new.status_code == 200
    new_state = res_new.get_json()["state"]

    # 3. Enter "Alpha Squad" in Slot 2 without specifying a logo
    new_state["teams"][1]["name"] = "Alpha Squad"
    new_state["teams"][1]["logo"] = ""
    res_save2 = admin_client.post("/api/admin/save", json=new_state, headers=headers)
    assert res_save2.status_code == 200
    saved_state = res_save2.get_json()["state"]

    # The logo is automatically populated from memory!
    assert saved_state["teams"][1]["logo"] == logo_url

