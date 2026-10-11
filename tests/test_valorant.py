"""Valorant: telling inhouses apart, fetching, typed-in scoreboards, names and the site."""
import io
import json
import shutil
import urllib.error
from pathlib import Path

import pytest

from overtime.cli import main
from overtime.config import AgentClasses, ValorantSettings, append_players, load_roster, read_roster_rows
from overtime.val_stats import build_val_season
from overtime.valorant import ValorantError, fetch, from_trimmed, import_files, is_inhouse, load_folder, trim

AGENTS = ["Jett", "Omen", "Sova", "Killjoy", "Sage"]


def api_match(mid="m1", queue=("", "Custom Game"), players=10, start="2026-10-14T18:52:38.776Z",
              names=None, blue=13, red=9, mapname="Ascent", puuids=None):
    """A match in the shape the HenrikDev v4 API returns (only the parts we read)."""
    names = names or [(f"P{i}", "EUW") for i in range(players)]
    puuids = puuids or [f"id-{n}-{t}" for n, t in names]
    ps = []
    for i, ((n, t), pid) in enumerate(zip(names, puuids)):
        ps.append({"puuid": pid, "name": n, "tag": t, "team_id": "Blue" if i < len(names) / 2 else "Red",
                   "agent": {"name": AGENTS[i % 5]},
                   "stats": {"score": 4000 + 100 * i, "kills": 15, "deaths": 12, "assists": 4, "headshots": 10,
                             "bodyshots": 30, "legshots": 2, "damage": {"dealt": 3000, "received": 2800}}})
    who = lambda i: {"puuid": puuids[i % len(puuids)], "name": names[i % len(names)][0], "tag": "EUW", "team": "Blue"}
    # Kill feed out of order on purpose: the first blood is the earliest kill in each round.
    kills = [{"round": 0, "time_in_round_in_ms": 8000, "killer": who(5)}, {"round": 0, "time_in_round_in_ms": 5000, "killer": who(0)},
             {"round": 1, "time_in_round_in_ms": 4000, "killer": who(0)}, {"round": 1, "time_in_round_in_ms": 3000, "killer": who(5)},
             {"round": 2, "time_in_round_in_ms": 1000, "killer": who(0)}]
    rounds = [{"id": 0, "plant": {"site": "A", "player": who(1)}}, {"id": 1, "plant": None},
              {"id": 2, "plant": {"site": "B", "player": who(1)}}, {"id": 3}]
    return {"metadata": {"match_id": mid, "map": {"name": mapname}, "started_at": start, "is_completed": True,
                         "game_length_in_ms": 2_000_000, "cluster": "London",
                         "queue": {"id": queue[0], "name": queue[1], "mode_type": "Standard"}},
            "players": ps, "rounds": rounds, "kills": kills,
            "teams": [{"team_id": "Blue", "rounds": {"won": blue, "lost": red}},
                      {"team_id": "Red", "rounds": {"won": red, "lost": blue}}]}


def test_only_full_custom_games_count():
    s = ValorantSettings(min_players=10)
    assert is_inhouse(api_match(), 10) == (True, "")
    assert not is_inhouse(api_match(queue=("competitive", "Competitive")), 10)[0]
    assert is_inhouse(api_match(players=2), 10) == (False, "only 2 players")
    assert is_inhouse(api_match(players=2), 2)[0]
    assert s.min_players == 10


def test_import_trims_and_skips_duplicates(tmp_path):
    dest = tmp_path / "valorant"
    saved = tmp_path / "response.json"
    saved.write_text(json.dumps({"status": 200, "data": [
        api_match("a"), api_match("b", queue=("competitive", "Competitive")), api_match("c", players=2)]}))
    roster = load_roster(tmp_path)  # empty
    r = import_files([saved], dest, ValorantSettings(), roster)
    assert len(r.added) == 1 and r.skipped == {"a Competitive game": 1, "only 2 players": 1}
    # 18:52 UTC in October is 19:52 in Dublin, and the file goes in that night's folder.
    assert r.added[0].relative_to(dest).as_posix() == "2026-10-14/1952-ascent-a.json"
    assert len(r.new_ids) == 10
    again = import_files([saved], dest, ValorantSettings(), roster)
    assert not again.added and again.duplicates == 1
    (m,), warnings = load_folder(dest)
    assert not warnings and m.score == (13, 9) and m.winner == 1 and m.rounds == 22
    assert m.played_at.hour == 19 and m.team(1)[0].first_bloods == 2 and m.team(1)[0].damage == 3000


class FakeAPI:
    """Stands in for urlopen: serves pages of a fixed history per account."""

    def __init__(self, histories, status=200):
        self.histories, self.status, self.urls = histories, status, []

    def __call__(self, req, timeout=30):
        url = req.full_url
        self.urls.append(url)
        if self.status != 200:
            raise urllib.error.HTTPError(url, self.status, "nope", {}, io.BytesIO(b"{}"))
        account = url.split("/pc/")[1].split("?")[0]
        q = dict(part.split("=") for part in url.split("?")[1].split("&"))
        start, size = int(q["start"]), int(q["size"])
        body = json.dumps({"status": 200, "data": self.histories.get(account, [])[start:start + size]}).encode()
        resp = io.BytesIO(body)
        resp.__enter__ = lambda *a: resp
        resp.__exit__ = lambda *a: None
        return resp


def test_fetch_pages_through_history_and_counts_shared_games_once(tmp_path):
    shared = api_match("shared")
    histories = {"Host%20Name/EUW": [shared] + [api_match(f"c{i}", queue=("competitive", "Competitive"))
                                               for i in range(14)],
                 "Regular/1234": [shared, api_match("only-regular", start="2026-10-14T20:00:00Z")]}
    api = FakeAPI(histories)
    settings = ValorantSettings(accounts=["Host Name#EUW", "Regular#1234"], history=20)
    r = fetch(settings, "HDEV-test", tmp_path, load_roster(tmp_path), opener=api)
    assert sorted(json.loads(p.read_text())["id"] for p in r.added) == ["only-regular", "shared"]
    assert r.duplicates == 1 and r.checked == ["Host Name#EUW", "Regular#1234"]
    assert any("start=10" in u for u in api.urls)  # second page of the host's history
    assert all("Authorization" not in u for u in api.urls)  # key goes in a header, not the URL


def test_fetch_explains_a_bad_key(tmp_path):
    settings = ValorantSettings(accounts=["Host#EUW"])
    with pytest.raises(ValorantError, match="API key was refused"):
        fetch(settings, "HDEV-wrong", tmp_path, load_roster(tmp_path), opener=FakeAPI({}, status=401))
    with pytest.raises(ValorantError, match="no API key"):
        fetch(settings, "", tmp_path, load_roster(tmp_path))
    with pytest.raises(ValorantError, match="no accounts"):
        fetch(ValorantSettings(), "HDEV-x", tmp_path, load_roster(tmp_path))


def test_names_follow_the_roster_the_account_and_typed_in_games(tmp_path):
    (tmp_path / "players.csv").write_text(
        "name,ingame_names,roles,riot_ids\nAoife,Aoife#1,support,AoifeV#EUW\n", encoding="utf-8")
    roster = load_roster(tmp_path)
    folder = tmp_path / "valorant"
    names = [("AoifeV", "EUW")] + [(f"P{i}", "EUW") for i in range(1, 10)]
    first = api_match("one", names=names, start="2026-10-07T19:00:00Z")
    # A week later Aoife has renamed her Riot account; the same account id keeps her profile.
    renamed = api_match("two", names=[("NewName", "0001")] + names[1:], start="2026-10-14T19:00:00Z",
                        puuids=[f"id-AoifeV-EUW"] + [f"id-{n}-{t}" for n, t in names[1:]])
    saved = tmp_path / "r.json"
    saved.write_text(json.dumps({"data": [first, renamed]}))
    import_files([saved], folder, ValorantSettings(), roster)
    night = folder / "2026-10-21"
    night.mkdir()
    rows = ["date,map,team,rounds,player,agent,acs,kills,deaths,assists"]
    rows += [f"2026-10-21 19:30,Bind,{'Blue' if i < 5 else 'Red'},{13 if i < 5 else 4},{n}#{t},Sage,200,10,10,5"
             for i, (n, t) in enumerate(names)]
    (night / "1930-bind.csv").write_text("\n".join(rows) + "\n", encoding="utf-8")
    maps, warnings = load_folder(folder)
    assert not warnings and len(maps) == 3
    season = build_val_season(maps, roster, AgentClasses({"Sage": "sentinel"}))
    assert len(season.players["Aoife"].appearances) == 3  # API, renamed API, typed-in
    assert season.players["Aoife"].riot_ids == {"AoifeV#EUW", "NewName#0001"}
    assert len(season.players["P1"].appearances) == 3  # typed-in rows join the API player
    assert season.players["P1"].totals["damage_rounds"] == 44  # the typed-in game has no damage
    assert len(season.players) == 10


def test_adding_riot_ids_keeps_an_old_roster(tmp_path):
    (tmp_path / "players.csv").write_text("name,ingame_names,roles\nCian,CianOW,tank\n", encoding="utf-8")
    append_players(tmp_path, ["Saoirse#EIRE"], riot=True)
    rows = read_roster_rows(tmp_path / "players.csv")
    assert rows == [{"name": "Cian", "ingame_names": "CianOW", "roles": "tank", "riot_ids": ""},
                    {"name": "Saoirse", "ingame_names": "", "roles": "", "riot_ids": "Saoirse#EIRE"}]
    assert load_roster(tmp_path).resolve_riot("saoirse", "eire") == "Saoirse"


def test_site_has_both_games_and_joins_roster_profiles(demo_logs, demo_valorant, config, tmp_path):
    (config / "players.csv").write_text(
        "name,ingame_names,roles,riot_ids\nPike,Pike#2211;PikeOnAlt,tank>support,Pike#2211\n", encoding="utf-8")
    out = tmp_path / "site"
    assert main(["--logs", str(demo_logs), "--valorant", str(demo_valorant), "--config", str(config),
                 "build", "--out", str(out)]) == 0
    index = (out / "valorant" / "index.html").read_text(encoding="utf-8")
    assert "DUES Valorant" in index and 'aria-current="page">Valorant' in index and "Kestrel" in index
    assert len(list((out / "valorant" / "matches").glob("*.html"))) == len(load_folder(demo_valorant)[0]) + 1
    pike_ow = (out / "players" / "pike.html").read_text(encoding="utf-8")
    assert 'href="../valorant/players/pike.html"' in pike_ow
    pike_val = (out / "valorant" / "players" / "pike.html").read_text(encoding="utf-8")
    assert 'href="../../players/pike.html"' in pike_val
    # Kestrel plays both but is not on the roster, so the profiles are not assumed to be one person.
    assert "valorant/players" not in (out / "players" / "kestrel.html").read_text(encoding="utf-8")
    assert "Typed in from the scoreboard" in "".join(
        p.read_text(encoding="utf-8") for p in (out / "valorant" / "matches").glob("manual-*.html"))


def test_no_valorant_config_means_no_valorant_pages(demo_logs, config, tmp_path):
    (config / "valorant.yaml").unlink()
    out = tmp_path / "site"
    assert main(["--logs", str(demo_logs), "--config", str(config), "build", "--out", str(out)]) == 0
    assert not (out / "valorant").exists()
    assert "Valorant" not in (out / "index.html").read_text(encoding="utf-8")


def test_empty_valorant_shows_how_to_start(demo_logs, config, tmp_path):
    out = tmp_path / "site"
    assert main(["--logs", str(demo_logs), "--valorant", str(tmp_path / "none"), "--config", str(config),
                 "build", "--out", str(out)]) == 0
    page = (out / "valorant" / "index.html").read_text(encoding="utf-8")
    assert "No games yet" in page and "HENRIKDEV_API_KEY" in page


def test_first_bloods_and_plants_come_from_the_kill_feed_and_rounds():
    m = from_trimmed(trim(api_match()))
    by = {p.riot_name: p for p in m.players}
    assert (by["P0"].first_bloods, by["P5"].first_bloods, by["P1"].first_bloods) == (2, 1, 0)
    assert (by["P1"].plants, by["P0"].plants) == (2, 0)
    bare = api_match()
    bare["kills"], bare["rounds"] = [], []
    m = from_trimmed(trim(bare))
    assert m.players[0].first_bloods is None and m.players[0].plants is None  # unknown, not zero
