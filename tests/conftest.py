import os
import shutil
import tempfile
import pytest
from app import app, password_hash

@pytest.fixture(autouse=True)
def test_environment(tmp_path, monkeypatch):
    """Isolate file storage and data directories in a temporary directory for each test."""
    scrims_dir = tmp_path / "scrims"
    scrims_dir.mkdir(parents=True, exist_ok=True)
    backups_dir = tmp_path / "backups"
    backups_dir.mkdir(parents=True, exist_ok=True)
    uploads_dir = tmp_path / "uploads"
    uploads_dir.mkdir(parents=True, exist_ok=True)

    cur_file = str(scrims_dir / "current.txt")
    data_file = str(tmp_path / "data.json")
    audit_file = str(tmp_path / "activity.json")
    schedule_file = str(tmp_path / "schedules.json")
    users_file = str(tmp_path / "admin_users.json")
    team_logos_file = str(tmp_path / "team_logos.json")

    # Patch module-level paths in app
    monkeypatch.setattr("app.SCRIM_DIR", str(scrims_dir))
    monkeypatch.setattr("app.CUR_FILE", cur_file)
    monkeypatch.setattr("app.DATA_FILE", data_file)
    monkeypatch.setattr("app.BACKUP_DIR", str(backups_dir))
    monkeypatch.setattr("app.UPLOAD_DIR", str(uploads_dir))
    monkeypatch.setattr("app.AUDIT_FILE", audit_file)
    monkeypatch.setattr("app.SCHEDULE_FILE", schedule_file)
    monkeypatch.setattr("app.USERS_FILE", users_file)
    monkeypatch.setattr("app.TEAM_LOGOS_FILE", team_logos_file)

    # Reset in-memory rate limiting dictionaries
    import app as app_module
    app_module.LOGIN_ATTEMPTS.clear()
    app_module.REGISTRATION_ATTEMPTS.clear()

    # Create default admin user in USERS_FILE
    import json
    initial_user = {"admin": password_hash("test-password")}
    with open(users_file, "w", encoding="utf-8") as f:
        json.dump(initial_user, f)

    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    return tmp_path


@pytest.fixture
def client():
    """Flask test client."""
    with app.test_client() as c:
        yield c


@pytest.fixture
def sample_state():
    """A realistic scrim state with 3 teams, 2 games, known PP and KP."""
    return {
        "title": "Championship Finals",
        "date": "2026-11-10",
        "theme": "#7b2fe0",
        "slots": 3,
        "games": 2,
        "placement_points": [15, 12, 10, 8, 6],
        "kill_points": 2,
        "teams": [
            {
                "name": "Alpha Squad",
                "logo": "",
                "aliases": ["Alpha", "AS"],
                "players": ["Alice", "Bob", "Charlie", "Dave"],
            },
            {
                "name": "Bravo Team",
                "logo": "",
                "aliases": ["Bravo", "BT"],
                "players": ["Eve", "Frank", "Grace", "Hank"],
            },
            {
                "name": "Charlie Crew",
                "logo": "",
                "aliases": ["Crew", "CC"],
                "players": ["Ivy", "Jack", "Karl", "Leo"],
            },
        ],
        "results": [
            # Game 1
            [
                {"rank": 1, "kills": 5, "noshow": False, "dq": False, "pk": [3, 2, 0, 0]},
                {"rank": 2, "kills": 3, "noshow": False, "dq": False, "pk": [1, 1, 1, 0]},
                {"rank": 3, "kills": 0, "noshow": False, "dq": False, "pk": [0, 0, 0, 0]},
            ],
            # Game 2
            [
                {"rank": 2, "kills": 4, "noshow": False, "dq": False, "pk": [2, 1, 1, 0]},
                {"rank": 1, "kills": 6, "noshow": False, "dq": False, "pk": [3, 2, 1, 0]},
                {"rank": None, "kills": 0, "noshow": True, "dq": False, "pk": [None, None, None, None]},
            ],
        ],
    }


@pytest.fixture
def admin_client(client):
    """Flask test client authenticated as admin with a CSRF token."""
    with client.session_transaction() as sess:
        sess["admin"] = True
        sess["username"] = "admin"
        sess["csrf_token"] = "valid-test-csrf-token"
    return client
