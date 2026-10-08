"""Write an invented season of ScrimTime logs, for trying the site and for tests.

Every player, name and number here is made up. Each player has a hidden skill
per role; teams are drawn at random and results follow the skill gap, so the
ratings should roughly rediscover who is good at what.

    python scripts/make_demo_logs.py --out demo-logs
    python -m overtime --logs demo-logs build --out demo-site
"""
from __future__ import annotations

import math
import random
from datetime import datetime, timedelta
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
HEROES = yaml.safe_load((ROOT / "config" / "heroes.yaml").read_text(encoding="utf-8"))

# name: (tank, damage, support skill in [-2, 2], role preferences, favourite heroes)
PLAYERS = {
    "Kestrel":  (0.2, 1.8, -0.5, ["damage"], ["Tracer", "Sojourn", "Genji"]),
    "Marrow":   (1.6, 0.1, -0.3, ["tank"], ["Winston", "D.Va", "Sigma"]),
    "Bramble":  (-0.4, 0.0, 1.3, ["support"], ["Ana", "Baptiste", "Kiriko"]),
    "Quill":    (0.3, 1.1, 0.4, ["damage", "support"], ["Cassidy", "Ashe", "Zenyatta"]),
    "Tidal":    (-0.8, -0.2, 0.9, ["support"], ["Lúcio", "Juno", "Mercy"]),
    "Ember":    (0.9, 0.6, 0.0, ["tank", "damage"], ["Reinhardt", "Ramattra", "Reaper"]),
    "Sorrel":   (-0.5, 0.7, 0.2, ["damage"], ["Widowmaker", "Hanzo", "Ashe"]),
    "Lumen":    (0.1, -0.3, 1.7, ["support"], ["Kiriko", "Brigitte", "Ana"]),
    "Pike":     (1.0, 0.4, 0.3, ["tank", "damage", "support"], ["Orisa", "Mei", "Moira"]),
    "Vesper":   (-1.0, 0.5, -0.4, ["damage"], ["Pharah", "Echo", "Junkrat"]),
    "Juniper":  (0.4, -0.6, 0.2, ["support", "tank"], ["Mercy", "Zarya", "Illari"]),
    "Halcyon":  (-0.2, -1.1, -0.6, ["damage", "support"], ["Soldier: 76", "Moira", "Torbjörn"]),
    "Rook":     (-0.3, -0.4, -1.2, ["tank"], ["Roadhog", "Mauga", "Junker Queen"]),
    "Fennel":   (-1.2, -0.9, -0.1, ["support", "damage"], ["Lifeweaver", "Symmetra", "Baptiste"]),
    "Wren":     (0.0, 0.2, 0.6, ["damage", "support"], ["Sombra", "Venture", "Juno"]),
    "Cobalt":   (0.7, -0.8, -0.9, ["tank", "damage"], ["Doomfist", "Wrecking Ball", "Bastion"]),
}
SECOND_NAME = {"Pike": "PikeOnAlt"}  # one person, two accounts: shows the roster aliases
MAPS = [
    ("Lijiang Tower", "Control"), ("Ilios", "Control"), ("Busan", "Control"),
    ("Antarctic Peninsula", "Control"), ("King's Row", "Hybrid"), ("Midtown", "Hybrid"),
    ("Eichenwalde", "Hybrid"), ("Watchpoint: Gibraltar", "Escort"), ("Circuit Royal", "Escort"),
    ("Havana", "Escort"), ("New Queen Street", "Push"), ("Colosseo", "Push"),
    ("Suravasa", "Flashpoint"), ("New Junk City", "Flashpoint"),
]
ROLE_INDEX = {"tank": 0, "damage": 1, "support": 2}
SHAPE = ["tank", "damage", "damage", "support", "support"]

# Per-10-minute baselines by role: elims, final blows, deaths, hero dmg, healing, blocked
BASE = {
    "tank":    (22, 8, 5.5, 8500, 0, 9000),
    "damage":  (22, 10, 6.5, 9500, 300, 0),
    "support": (13, 3.5, 5.0, 4200, 8800, 0),
}


def hero_for(rng, name, role):
    favs = [h for h in PLAYERS[name][4] if h in HEROES[role]]
    return rng.choice(favs) if favs and rng.random() < 0.8 else rng.choice(HEROES[role])


def pick_roles(rng, names):
    """Give ten players a 1-2-2 per team using their preferences where possible."""
    for _ in range(500):
        rng.shuffle(names)
        need = {"tank": 2, "damage": 4, "support": 4}
        out = {}
        for n in sorted(names, key=lambda n: len(PLAYERS[n][3])):
            for r in PLAYERS[n][3] + [r for r in need if r not in PLAYERS[n][3]]:
                if need[r]:
                    out[n] = r
                    need[r] -= 1
                    break
        if not any(need.values()):
            return out
    raise RuntimeError("could not assign roles")


def fmt(x):
    return f"{x:.2f}"


def write_map(rng, when: datetime, lobby: list[str], folder: Path):
    roles = pick_roles(rng, lobby)
    teams = {1: [], 2: []}
    for role in ("tank", "damage", "support"):
        group = [n for n in lobby if roles[n] == role]
        rng.shuffle(group)
        half = len(group) // 2
        teams[1] += group[:half]
        teams[2] += group[half:]
    skill = {t: sum(PLAYERS[n][ROLE_INDEX[roles[n]]] for n in teams[t]) for t in (1, 2)}
    p1 = 1 / (1 + math.exp(-(skill[1] - skill[2]) * 0.55))

    map_name, map_type = rng.choice(MAPS)
    n_rounds = {"Control": 3, "Push": 1, "Flashpoint": 1}.get(map_type, 2)
    winner = 1 if rng.random() < p1 else 2
    if map_type == "Control":
        loser_wins = rng.choice([0, 1])
        n_rounds = 2 + loser_wins
    lines, t = [], 0.0
    clock = lambda sec: f"[{int(sec // 3600):02d}:{int(sec % 3600 // 60):02d}:{int(sec % 60):02d}] "
    lines.append(f"{clock(0)},match_start,0,{map_name},{map_type},Team 1,Team 2")

    hero = {n: hero_for(rng, n, roles[n]) for n in lobby}
    ingame = {n: SECOND_NAME[n] if n in SECOND_NAME and rng.random() < 0.4 else n for n in lobby}
    cum = {n: {} for n in lobby}  # hero -> stat vector
    score = [0, 0]
    round_winners = []
    if map_type == "Control":
        loser = 3 - winner
        seq = [winner, winner] if n_rounds == 2 else rng.choice([[winner, loser, winner], [loser, winner, winner]])
        round_winners = seq
    else:
        round_winners = [winner] * n_rounds

    for rnd, rw in enumerate(round_winners, start=1):
        lines.append(f"{clock(t + 30)},round_start,{fmt(t)},{rnd},0,{score[0]},{score[1]},0")
        length = rng.uniform(170, 300) if map_type == "Control" else rng.uniform(320, 520)
        # One mid-round hero swap now and then.
        for n in lobby:
            if rng.random() < 0.12:
                new = hero_for(rng, n, roles[n])
                if new != hero[n]:
                    lines.append(f"{clock(t + 90)},hero_swap,{fmt(t + 60)},Team {1 if n in teams[1] else 2},"
                                 f"{ingame[n]},{new},{hero[n]},0")
                    split = rng.uniform(0.3, 0.7)
                    _add(rng, cum[n], hero[n], roles[n], length * split, PLAYERS[n][ROLE_INDEX[roles[n]]], n in teams[rw])
                    hero[n] = new
                    _add(rng, cum[n], hero[n], roles[n], length * (1 - split), PLAYERS[n][ROLE_INDEX[roles[n]]], n in teams[rw])
                    continue
            _add(rng, cum[n], hero[n], roles[n], length, PLAYERS[n][ROLE_INDEX[roles[n]]], n in teams[rw])
        # A few kill-feed lines; recent builds censor the event name to ****.
        for k in range(rng.randint(3, 6)):
            killer = rng.choice(teams[rw] if rng.random() < 0.6 else teams[3 - rw])
            kt = 1 if killer in teams[1] else 2
            victim = rng.choice(teams[3 - kt])
            event = "****" if rng.random() < 0.5 else "kill"
            lines.append(f"{clock(t + 60 + k * 20)},{event},{fmt(t + 30 + k * 20)},Team {kt},{ingame[killer]},"
                         f"{hero[killer]},Team {3 - kt},{ingame[victim]},{hero[victim]},Primary Fire,"
                         f"{rng.uniform(20, 200):.2f},False,0")
        t += length
        score[rw - 1] += 1 if map_type != "Escort" and map_type != "Hybrid" else rng.choice([2, 3])
        if map_type in ("Escort", "Hybrid") and rnd == len(round_winners):
            score = [3, rng.choice([1, 2])] if winner == 1 else [rng.choice([1, 2]), 3]
        lines.append(f"{clock(t + 30)},round_end,{fmt(t)},{rnd},0,{score[0]},{score[1]},0,100,0,0")
        for n in lobby:
            team = 1 if n in teams[1] else 2
            for h, v in cum[n].items():
                lines.append(f"{clock(t + 30)},player_stat,{fmt(t)},{rnd},Team {team},{ingame[n]},{h},"
                             + ",".join(v[:-7]))
    if map_type in ("Push", "Flashpoint"):
        score = [1, 0] if winner == 1 else [0, 1]
    lines.append(f"{clock(t + 31)},match_end,{fmt(t)},{len(round_winners)},{score[0]},{score[1]}")
    name = f"Log-{when:%Y-%m-%d-%H-%M-%S}.txt"
    (folder / name).write_text("\n".join(lines) + "\n", encoding="utf-8")


def _add(rng, cum, hero, role, seconds, skill, won):
    """Add one stint's stats to a player's cumulative row for a hero."""
    mins = seconds / 60
    e, fb, d, dmg, heal, blk = BASE[role]
    form = math.exp(0.18 * skill + rng.gauss(0, 0.18) + (0.08 if won else -0.08))
    worse = math.exp(-0.15 * skill + rng.gauss(0, 0.2) + (-0.1 if won else 0.1))
    add = {
        "elims": e * form * mins / 10, "fb": fb * form * mins / 10, "deaths": d * worse * mins / 10,
        "dmg": dmg * form * mins / 10, "heal": heal * form * mins / 10, "blk": blk * form * mins / 10,
        "time": seconds,
    }
    prev = cum.get(hero)
    acc = dict(zip(["elims", "fb", "deaths", "dmg", "heal", "blk", "time"],
                   [float(x) for x in prev[-7:]])) if prev else {k: 0.0 for k in add}
    for k in add:
        acc[k] += add[k]
    elims, fb, deaths = round(acc["elims"]), round(acc["fb"]), round(acc["deaths"])
    shots = int(acc["time"] * 3)
    hit = int(shots * min(0.65, max(0.2, 0.38 + 0.04 * skill)))
    row = [
        elims, fb, deaths, fmt(acc["dmg"] * 1.15), fmt(acc["dmg"] * 0.15), fmt(acc["dmg"]),
        fmt(acc["heal"]), fmt(acc["heal"] * 0.3), fmt(acc["heal"] * 0.1), fmt(acc["dmg"] * 0.9),
        fmt(acc["blk"]), round(elims * 0.2), round(elims * 0.3), round(acc["time"] / 140),
        round(acc["time"] / 150), min(5, 1 + elims // 12), elims // 15, fb // 4, elims // 6, 0, 0,
        hit // 9, "0.11", 0, 0, 0, shots, hit, shots - hit, 0, 0, fmt(hit / shots if shots else 0),
        fmt(acc["time"]),
    ]
    # Keep the raw accumulators at the end of the stored list so the next stint can add to them.
    cum[hero] = [str(x) for x in row] + [str(acc[k]) for k in ("elims", "fb", "deaths", "dmg", "heal", "blk", "time")]


def main(folder: Path, seed: int = 7) -> int:
    rng = random.Random(seed)
    folder.mkdir(exist_ok=True)
    for old in folder.glob("Log-*.txt"):
        old.unlink()
    start = datetime(2026, 9, 2, 19, 30)
    count = 0
    for week in range(6):  # Wednesday nights, September to early October
        night = start + timedelta(weeks=week)
        attending = rng.sample(sorted(PLAYERS), rng.randint(12, 16))
        for i in range(rng.randint(5, 7)):
            lobby = rng.sample(attending, 10)
            write_map(rng, night + timedelta(minutes=17 * i, seconds=rng.randint(0, 59)), lobby, folder)
            count += 1
    print(f"wrote {count} demo maps to {folder}")
    return count


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default="demo-logs", help="folder to write logs into (default: demo-logs)")
    ap.add_argument("--seed", type=int, default=7)
    a = ap.parse_args()
    main(Path(a.out), a.seed)
