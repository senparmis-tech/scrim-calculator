import pytest
from app import to_num, to_int, clean_theme, default_state, sanitize, validate_state, blank_result

def test_to_num_and_to_int():
    assert to_num("12") == 12
    assert to_num(12.5) == 12.5
    assert to_num("abc") is None
    assert to_num(None) is None

    assert to_int("10") == 10
    assert to_int(10.7) == 10
    assert to_int("invalid") is None
    assert to_int(None) is None


def test_clean_theme():
    assert clean_theme({"color": "#ff0000"}) == {"color": "#ff0000"}
    assert clean_theme({"color": "#1A2B3C"}) == {"color": "#1a2b3c"}
    # Invalid themes fallback to default #7b2fe0
    assert clean_theme({"color": "invalid"}) == {"color": "#7b2fe0"}
    assert clean_theme({"color": "#fff"}) == {"color": "#7b2fe0"}
    assert clean_theme({}) == {"color": "#7b2fe0"}
    assert clean_theme(None) == {"color": "#7b2fe0"}


def test_blank_result():
    res = blank_result()
    assert res == {"rank": None, "kills": None, "noshow": False, "dq": False, "pk": [None] * 4}


def test_default_state():
    state = default_state()
    assert state["title"] == "ST6 MIXED SCRIMMAGE"
    assert state["slots"] == 25
    assert state["games"] == 4
    assert state["kill_points"] == 2
    assert len(state["placement_points"]) == 7
    assert len(state["teams"]) == 25
    assert len(state["results"]) == 4
    assert len(state["results"][0]) == 25


def test_sanitize_clamps_and_normalizes():
    raw = {
        "title": "My Tournament",
        "date": "2026-11-10",
        "slots": 2,
        "games": 1,
        "kill_points": -5,  # negative should be clamped to 0
        "placement_points": [10, "5", "abc"],
        "teams": [
            {"name": " Team 1 ", "aliases": [" T1 ", ""], "players": ["P1", "P2"]},
        ],
        "results": [
            [
                {"rank": 1, "kills": 3, "noshow": False, "dq": False, "pk": [2, 1]},
            ]
        ]
    }
    cleaned = sanitize(raw)
    assert cleaned["title"] == "My Tournament"
    assert cleaned["date"] == "2026-11-10"
    assert cleaned["kill_points"] == 0
    assert cleaned["placement_points"] == [10, 5, 0]
    # slots was 2, so teams list should have 2 items
    assert len(cleaned["teams"]) == 2
    assert cleaned["teams"][0]["name"] == " Team 1 "
    assert cleaned["teams"][0]["aliases"] == ["T1"]
    # results grid should have dimensions games (1) x slots (2)
    assert len(cleaned["results"]) == 1
    assert len(cleaned["results"][0]) == 2


def test_validate_state():
    # Valid state
    valid = default_state()
    assert validate_state(valid) == []

    # Not a dictionary
    assert validate_state("not a dict") == ["Invalid state payload"]

    # Bad slots count
    bad_slots = default_state()
    bad_slots["slots"] = 0
    # slots < 1 is clamped to 1 in validate_state, but if invalid rank:
    bad_slots["results"][0][0]["rank"] = 99
    assert any("placement outside" in err for err in validate_state(bad_slots))
