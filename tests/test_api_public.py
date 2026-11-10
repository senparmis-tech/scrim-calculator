import json
import pytest
from app import save_state, default_state, write_json_file, SCHEDULE_FILE

def test_index_page(client):
    res = client.get("/")
    assert res.status_code == 200
    assert b"Scrim Results" in res.data


def test_public_state(client, sample_state):
    save_state(sample_state)
    res = client.get("/api/state")
    assert res.status_code == 200
    data = res.get_json()
    assert data["title"] == "Championship Finals"
    assert data["kill_points"] == 2
    assert len(data["standings"]) == 3
    assert data["standings"][0]["name"] == "Alpha Squad"


def test_public_scrims(client, sample_state):
    save_state(sample_state)
    res = client.get("/api/scrims")
    assert res.status_code == 200
    data = res.get_json()
    assert "current" in data
    assert len(data["scrims"]) >= 1


def test_analytics_routes(client, sample_state):
    save_state(sample_state)
    # HTML page
    res_html = client.get("/analytics")
    assert res_html.status_code == 200
    assert b"Scrim Analytics" in res_html.data

    # JSON API
    res_api = client.get("/api/analytics")
    assert res_api.status_code == 200
    data = res_api.get_json()
    assert "analytics" in data
    assert len(data["analytics"]["teams"]) == 3


def test_schedule_and_team_registration(client, sample_state):
    save_state(sample_state, "test-scrim-1")

    # Set up a schedule for test-scrim-1
    import app as app_module
    schedules = {
        "test-scrim-1": {
            "title": "Weekly Scrim",
            "start_at": "2026-11-15 18:00 UTC",
            "max_teams": 16,
            "registration_open": True,
            "status": "upcoming",
            "registrations_count": 0,
            "registrations": []
        }
    }
    write_json_file(app_module.SCHEDULE_FILE, schedules)

    # Check schedule page & API
    res = client.get("/schedule")
    assert res.status_code == 200
    assert b"Scrim Schedule" in res.data

    res_api = client.get("/api/schedules")
    assert res_api.status_code == 200
    s_data = res_api.get_json()
    assert len(s_data["schedules"]) >= 1

    # Missing fields
    res_bad = client.post("/api/scrims/test-scrim-1/register", json={"team": "Delta"})
    assert res_bad.status_code == 400

    # Successful registration
    reg_payload = {"team": "Delta Force", "captain": "DeltaLead", "contact": "discord:deltalead"}
    res_ok = client.post("/api/scrims/test-scrim-1/register", json=reg_payload)
    assert res_ok.status_code == 201
    assert res_ok.get_json()["message"] == "Registration received"

    # Duplicate team name returns 409 Conflict
    res_dup = client.post("/api/scrims/test-scrim-1/register", json=reg_payload)
    assert res_dup.status_code == 409
    assert "already registered" in res_dup.get_json()["error"].lower()


def test_csv_exports(client, sample_state):
    save_state(sample_state, "test-csv-scrim")

    # Scrim results CSV
    res_csv = client.get("/api/export/test-csv-scrim.csv")
    assert res_csv.status_code == 200
    assert res_csv.content_type.startswith("text/csv")
    csv_text = res_csv.data.decode("utf-8")
    assert "Rank" in csv_text
    assert "Alpha Squad" in csv_text
    assert "Bravo Team" in csv_text

    # Players CSV
    res_player_csv = client.get("/api/export/test-csv-scrim-players.csv")
    assert res_player_csv.status_code == 200
    assert res_player_csv.content_type.startswith("text/csv")
    player_csv_text = res_player_csv.data.decode("utf-8")
    assert "Player" in player_csv_text
    assert "Alice" in player_csv_text


def test_pwa_assets(client):
    res_manifest = client.get("/manifest.webmanifest")
    assert res_manifest.status_code == 200
    manifest = res_manifest.get_json()
    assert manifest["name"] == "Scrim Calculator"

    res_sw = client.get("/sw.js")
    assert res_sw.status_code == 200
    assert "application/javascript" in res_sw.content_type
