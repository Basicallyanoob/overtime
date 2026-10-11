"""Write an invented season of Valorant inhouses, for trying the site and for tests.

Every player, name and number here is made up. Each player has a hidden skill;
teams are drawn at random and results follow the skill gap, so the ratings
should roughly rediscover who is good. Most games are stored as the importer
stores API games; one night is a typed-in scoreboard CSV, to show both routes.

    python scripts/make_demo_valorant.py --out demo-valorant
    python -m overtime --valorant demo-valorant build --out demo-site
"""
from __future__ import annotations

import csv
import json
import math
import random
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

# name: (Riot tag, skill in [-2, 2], favourite agents)
PLAYERS = {
    "Kestrel": ("EUW", 1.7, ["Jett", "Raze", "Neon"]),
    "Marrow": ("1916", 0.4, ["Omen", "Clove", "Brimstone"]),
    "Lumen": ("TCD", 0.9, ["Sova", "Fade", "Skye"]),
    "Quill": ("0042", 1.2, ["Reyna", "Iso", "Phoenix"]),
    "Pike": ("2211", 0.2, ["Killjoy", "Cypher", "Sage"]),
    "Vesper": ("EUW", -0.3, ["Viper", "Astra", "Miks"]),
    "Halcyon": ("DUB", -0.9, ["Sage", "Skye", "Deadlock"]),
    "Tidal": ("777", 0.0, ["Harbor", "Omen", "KAY/O"]),
    "Saoirse": ("EIRE", 1.0, ["Chamber", "Vyse", "Jett"]),
    "Oisin": ("4471", -0.6, ["Breach", "Gekko", "Tejo"]),
    "Niamh": ("GG", 0.6, ["Waylay", "Yoru", "Neon"]),
    "Cathal": ("0101", -1.3, ["Brimstone", "Sage", "Killjoy"]),
    "Ronan": ("TCD", 0.3, ["Fade", "KAY/O", "Sova"]),
    "Aoibhe": ("2020", -0.2, ["Clove", "Viper", "Veto"]),
}
MAPS = ["Ascent", "Bind", "Haven", "Lotus", "Sunset", "Abyss", "Split", "Summit", "Corrode"]


def _ids(rng) -> dict[str, str]:
    return {n: str(uuid.UUID(int=rng.getrandbits(128))) for n in PLAYERS}


def game(rng, ids, lineup, start: datetime, mapname: str) -> dict:
    blue, red = lineup[:5], lineup[5:]
    gap = sum(PLAYERS[p][1] for p in blue) - sum(PLAYERS[p][1] for p in red)
    p_blue = 1 / (1 + math.exp(-gap / 1.6))
    blue_wins = rng.random() < p_blue
    loser = max(1, min(12, round(rng.gauss(8.5 - abs(gap) * 0.8, 2.3))))
    win_score = 13
    if loser == 12:  # overtime
        win_score, loser = 14, 12
    score = {"Blue": win_score if blue_wins else loser, "Red": loser if blue_wins else win_score}
    rounds = win_score + loser
    used = set()
    players = []
    team_kills = {"Blue": 0, "Red": 0}
    for team, members in (("Blue", blue), ("Red", red)):
        for p in members:
            tag, skill, favs = PLAYERS[p]
            agent = next((a for a in rng.sample(favs, len(favs)) if (team, a) not in used), favs[0])
            used.add((team, agent))
            won_share = score[team] / rounds
            kills = max(0, round(rng.gauss(rounds * (0.62 + 0.13 * skill + 0.25 * (won_share - 0.5)), 3)))
            assists = max(0, round(rng.gauss(rounds * 0.22, 2)))
            damage = max(0, round(kills * rng.uniform(128, 160) + assists * 30 + rng.gauss(0, 120)))
            shots = max(kills * 6, round(damage / 30))
            hs_rate = min(0.45, max(0.08, rng.gauss(0.2 + 0.04 * skill, 0.04)))
            heads = round(shots * hs_rate)
            legs = round(shots * 0.05)
            players.append({"puuid": ids[p], "name": p, "tag": tag, "team": team, "agent": agent,
                            "score": round(kills * 150 + damage * 0.9 + assists * 25 + rng.gauss(0, 150)),
                            "kills": kills, "assists": assists, "damage": damage, "headshots": heads,
                            "bodyshots": shots - heads - legs, "legshots": legs, "deaths": 0, "first_bloods": 0})
            team_kills[team] += kills
    # Deaths mirror the other team's kills; first bloods lean towards strong players.
    for team, other in (("Blue", "Red"), ("Red", "Blue")):
        pool = [x for x in players if x["team"] == team]
        left = team_kills[other]
        for i, x in enumerate(pool):
            share = left if i == len(pool) - 1 else round(team_kills[other] / 5 + rng.gauss(0, 2))
            x["deaths"] = max(0, min(share, left))
            left -= x["deaths"]
    for _ in range(rounds):
        weights = [math.exp(0.5 * PLAYERS[x["name"]][1]) for x in players]
        rng.choices(players, weights)[0]["first_bloods"] += 1
    return {"format": "overtime-valorant-1", "source": "henrikdev", "id": str(uuid.UUID(int=rng.getrandbits(128))),
            "map": mapname, "started_at": start.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
            "length_ms": rounds * rng.randint(95000, 115000), "server": "London",
            "rounds": score, "players": players}


def write_csv(path: Path, g: dict, start: datetime) -> None:
    rounds = sum(g["rounds"].values())
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["date", "map", "team", "rounds", "player", "agent", "acs", "kills", "deaths", "assists", "first_bloods"])
        for p in g["players"]:
            w.writerow([f"{start:%Y-%m-%d %H:%M}", g["map"], p["team"], g["rounds"][p["team"]], f"{p['name']}#{p['tag']}",
                        p["agent"], round(p["score"] / rounds), p["kills"], p["deaths"], p["assists"], p["first_bloods"]])


def main(folder: Path, seed: int = 11) -> int:
    rng = random.Random(seed)
    ids = _ids(rng)
    folder.mkdir(parents=True, exist_ok=True)
    first = datetime(2026, 9, 3, 19, 30)  # Thursdays in Michaelmas term, Irish time (UTC+1)
    n = 0
    for week in range(6):
        night = first + timedelta(days=7 * week)
        lobby = rng.sample(list(PLAYERS), 10)
        for g_no in range(rng.choice([3, 4])):
            start = night + timedelta(minutes=45 * g_no + rng.randint(0, 6))
            rng.shuffle(lobby)
            g = game(rng, ids, lobby, start.replace(tzinfo=timezone(timedelta(hours=1))), rng.choice(MAPS))
            day = folder / f"{start:%Y-%m-%d}"
            day.mkdir(exist_ok=True)
            if week == 2 and g_no == 0:
                write_csv(day / f"{start:%H%M}-{g['map'].lower()}-typed-in.csv", g, start)
            else:
                (day / f"{start:%H%M}-{g['map'].lower()}-{g['id'][:8]}.json").write_text(
                    json.dumps(g, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
            n += 1
    print(f"Wrote {n} invented games to {folder}/")
    return n


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default="demo-valorant")
    ap.add_argument("--seed", type=int, default=11)
    a = ap.parse_args()
    main(Path(a.out), a.seed)
