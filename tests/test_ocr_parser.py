import pytest
from app import norm, parse_rows, merge_rows, match_rows, ScanError

def test_norm():
    assert norm("Team-Alpha #1") == "teamalpha1"
    assert norm("   Hello   World! ") == "helloworld"
    assert norm("") == ""


def test_parse_rows_valid_json():
    ai_output = """Here are the results:
    [
        {"rank": 1, "lobby_no": 4, "kills": 10, "players": ["P1", "P2"], "player_kills": [6, 4], "team_tag": "TAG"},
        {"rank": 2, "lobby_no": 1, "kills": 5, "players": ["P3"], "player_kills": [5], "team_tag": ""}
    ]
    Hope this helps!"""
    rows = parse_rows(ai_output)
    assert len(rows) == 2
    assert rows[0]["rank"] == 1
    assert rows[0]["lobby_no"] == 4
    assert rows[0]["kills"] == 10
    assert rows[0]["players"] == ["P1", "P2"]
    assert rows[0]["player_kills"] == [6, 4]
    assert rows[0]["team_tag"] == "TAG"


def test_parse_rows_invalid_json():
    # No json array at all
    with pytest.raises(ScanError) as exc_info:
        parse_rows("No valid array here")
    assert "no results" in str(exc_info.value).lower()

    # Broken json syntax within brackets
    with pytest.raises(ScanError) as exc_info:
        parse_rows("[ { broken json: 123 ]")
    assert "could not be read" in str(exc_info.value).lower()


def test_merge_rows_deduplication():
    # Screenshot 1 saw team in lobby 3 with 1 player cut off
    screenshot_1 = [
        {"rank": None, "lobby_no": 3, "kills": 2, "players": ["PlayerA"], "player_kills": [2], "team_tag": "X"}
    ]
    # Screenshot 2 saw team in lobby 3 more completely with 2 players and rank 1
    screenshot_2 = [
        {"rank": 1, "lobby_no": 3, "kills": 5, "players": ["PlayerA", "PlayerB"], "player_kills": [2, 3], "team_tag": "X"},
        {"rank": 2, "lobby_no": 5, "kills": 1, "players": ["Solo"], "player_kills": [1], "team_tag": "Y"},
    ]

    merged = merge_rows([screenshot_1, screenshot_2])
    assert len(merged) == 2
    lobby3 = next(r for r in merged if r["lobby_no"] == 3)
    assert lobby3["rank"] == 1
    assert lobby3["kills"] == 5
    assert len(lobby3["players"]) == 2


def test_match_rows_fuzzy_matching(sample_state):
    rows = [
        {"rank": 1, "lobby_no": 10, "kills": 5, "players": ["Alice", "Bob"], "player_kills": [3, 2], "team_tag": "Alpha"},
        {"rank": 2, "lobby_no": 11, "kills": 3, "players": ["BT_Eve"], "player_kills": [3], "team_tag": "BT"},
    ]
    matched = match_rows(rows, sample_state)
    assert len(matched) == 2

    # Alpha Squad is slot 1 in sample_state
    assert matched[0]["suggested_slot"] == 1
    assert matched[0]["match_confidence"] >= 0.75

    # Bravo Team (BT alias) is slot 2 in sample_state
    assert matched[1]["suggested_slot"] == 2
    assert matched[1]["match_confidence"] >= 0.75
