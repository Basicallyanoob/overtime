from datetime import datetime

import pytest

from overtime.parse import LogError, parse_folder, parse_text, split_fields

STATS = ",".join(["0"] * 31)


def stat(t, rnd, team, player, hero, elims, deaths, time):
    # elims, final blows, deaths, then 30 more numeric columns, the last being time played
    tail = ["0"] * 30
    tail[-1] = str(time)
    return (f"[00:00:00] ,player_stat,{t},{rnd},{team},{player},{hero},{elims},1,{deaths},"
            + ",".join(tail))


LOG = "\n".join([
    "[00:00:00] ,match_start,0,Lijiang Tower (Lunar New Year),Control,Team 1,Team 2",
    "[00:00:01] ,round_start,0,1,0,0,0,0",
    "[00:01:00] ,****,30.5,Team 1,Ana Player,Ana,Team 2,Bob,Reinhardt,Primary Fire,70,False,0",
    "[00:01:10] ,kill,40.5,Team 2,Bob,Reinhardt,Team 1,Ana Player,Ana,Primary Fire,70,False,0",
    "[00:04:00] ,round_end,240,1,0,1,0,0,100,30,0",
    stat(240, 1, "Team 1", "Ana Player", "Ana", 5, 2, 240),
    stat(240, 1, "Team 2", "Bob", "Reinhardt", 3, 4, 240),
    "[00:04:30] ,round_start,240,2,0,1,0,1",
    "[00:08:00] ,round_end,480,2,0,2,0,1,100,10,0",
    stat(480, 2, "Team 1", "Ana Player", "Ana", 9, 3, 300),
    stat(480, 2, "Team 1", "Ana Player", "Kiriko", 2, 1, 180),
    stat(480, 2, "Team 2", "Bob", "Reinhardt", 6, 8, 480),
    "[00:08:01] ,match_end,480,2,2,0",
])


def test_split_keeps_position_vectors_together():
    assert split_fields("a,(1.0, 2.0, 3.0),b") == ["a", "(1.0, 2.0, 3.0)", "b"]


def test_parse_takes_latest_cumulative_row_per_hero():
    m = parse_text(LOG, "x", datetime(2026, 9, 2, 19, 30))
    ana = next(p for p in m.players if p.name == "Ana Player")
    assert ana.heroes["Ana"]["eliminations"] == 9  # round 2 total, not 5 + 9
    assert ana.total("eliminations") == 11
    assert ana.total("time_played") == 480
    assert ana.main_hero == "Ana"
    assert ana.team == 1


def test_score_winner_and_variant_map_name():
    m = parse_text(LOG, "x", datetime(2026, 9, 2))
    assert m.score == (2, 0) and m.winner == 1 and m.complete
    assert m.base_map == "Lijiang Tower"
    assert m.duration == 480


def test_censored_kill_event_counts_as_first_kill():
    m = parse_text(LOG, "x", datetime(2026, 9, 2))
    assert m.first_kills == {1: 1, 2: 0}


def test_log_without_match_end_is_unfinished():
    text = LOG.replace("[00:08:01] ,match_end,480,2,2,0", "")
    m = parse_text(text, "x", datetime(2026, 9, 2))
    assert not m.complete
    assert m.score == (2, 0)  # from the last round_end


def test_not_a_scrimtime_log():
    with pytest.raises(LogError):
        parse_text("hello,world", "x", datetime(2026, 9, 2))


def test_folder_reads_dates_and_skips_duplicates(tmp_path):
    (tmp_path / "Log-2026-09-02-19-30-00.txt").write_text(LOG, encoding="utf-8")
    (tmp_path / "Log-2026-09-02-19-31-00.txt").write_text(LOG, encoding="utf-8")
    (tmp_path / "notes.txt").write_text("not a log", encoding="utf-8")
    maps, warnings = parse_folder(tmp_path)
    assert len(maps) == 1
    assert maps[0].played_at == datetime(2026, 9, 2, 19, 30)
    assert any("duplicate" in w for w in warnings)
    assert any("notes.txt" in w for w in warnings)
