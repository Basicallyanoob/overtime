"""Parse Overwatch Workshop Inspector logs written by the ScrimTime mode.

Each log file holds one map. Every line looks like::

    [00:06:42] ,player_stat,243.02,1,Team 1,sun,Lúcio,5,2,1,1551.96,...

The bracketed wall-clock time is dropped; the rest is a comma-separated event.
``player_stat`` rows are cumulative: each round repeats every player's totals
on every hero so far, so the latest row per (player, hero) is the map total.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

# Column order of a player_stat row after the event type, per ScrimTime's docs.
PLAYER_STAT_FIELDS = [
    "match_time", "round", "team", "player", "hero",
    "eliminations", "final_blows", "deaths", "all_damage", "barrier_damage",
    "hero_damage", "healing", "healing_received", "self_healing", "damage_taken",
    "damage_blocked", "defensive_assists", "offensive_assists", "ults_earned",
    "ults_used", "multikill_best", "multikills", "solo_kills", "objective_kills",
    "environmental_kills", "environmental_deaths", "critical_hits",
    "critical_hit_accuracy", "scoped_accuracy", "scoped_critical_hit_accuracy",
    "scoped_critical_hit_kills", "shots_fired", "shots_hit", "shots_missed",
    "scoped_shots_fired", "scoped_shots_hit", "weapon_accuracy", "time_played",
]
TEXT_FIELDS = {"team", "player", "hero"}

# The stats we keep. Everything else in the row is parsed but not stored.
STAT_KEYS = [
    "eliminations", "final_blows", "deaths", "hero_damage", "healing",
    "damage_blocked", "damage_taken", "offensive_assists", "defensive_assists",
    "ults_used", "solo_kills", "shots_fired", "shots_hit", "time_played",
]

FILENAME_TIME = re.compile(r"Log-(\d{4})-(\d{2})-(\d{2})-(\d{2})-(\d{2})-(\d{2})")


class LogError(ValueError):
    """The file is not a usable ScrimTime log."""


@dataclass
class PlayerMap:
    name: str
    team: int  # 1 or 2
    heroes: dict[str, dict[str, float]] = field(default_factory=dict)

    def total(self, key: str) -> float:
        return sum(h[key] for h in self.heroes.values())

    @property
    def main_hero(self) -> str:
        return max(self.heroes, key=lambda h: self.heroes[h]["time_played"])


@dataclass
class MapResult:
    id: str
    played_at: datetime
    map_name: str
    map_type: str
    team_names: tuple[str, str]
    score: tuple[int, int]
    complete: bool  # True if the log reached match_end
    duration: float  # seconds of match time
    players: list[PlayerMap]
    first_kills: dict[int, int] = field(default_factory=dict)  # team -> rounds won first fight

    @property
    def winner(self) -> int:
        """1 or 2 for the winning team, 0 for a draw."""
        a, b = self.score
        return 0 if a == b else (1 if a > b else 2)

    @property
    def base_map(self) -> str:
        """Map name without event variants, e.g. 'Lijiang Tower (Lunar New Year)'."""
        return re.sub(r"\s*\(.*\)$", "", self.map_name)

    def team(self, n: int) -> list[PlayerMap]:
        return [p for p in self.players if p.team == n]


def split_fields(line: str) -> list[str]:
    """Split on commas, keeping '(x, y, z)' position vectors intact."""
    out, cur, depth = [], [], 0
    for ch in line:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "," and depth == 0:
            out.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    out.append("".join(cur))
    return out


def to_number(value: str) -> float:
    """Numbers in logs can be blank or censored by the chat filter ('***')."""
    value = value.strip()
    if not value or "*" in value:
        return 0.0
    try:
        return float(value)
    except ValueError:
        return 0.0


def read_events(text: str) -> list[list[str]]:
    events = []
    for raw in text.lstrip("﻿").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        fields = split_fields(raw)
        if raw.startswith("["):
            fields = fields[1:]  # drop the '[hh:mm:ss] ' wall-clock prefix
        if not fields:
            continue
        # Recent game builds censor the word 'kill' in the log to '****'.
        if fields[0] == "****":
            fields[0] = "kill"
        events.append([f.strip() for f in fields])
    return events


def played_at_from(path: Path) -> datetime:
    m = FILENAME_TIME.search(path.name)
    if m:
        return datetime(*map(int, m.groups()))
    return datetime.fromtimestamp(path.stat().st_mtime).replace(microsecond=0)


def parse_text(text: str, map_id: str, played_at: datetime) -> MapResult:
    events = read_events(text)
    starts = [e for e in events if e[0] == "match_start"]
    if not starts:
        raise LogError("no match_start event; is this a ScrimTime log?")
    start = starts[-1]  # a restarted lobby logs a fresh match_start
    if len(start) < 6:
        raise LogError("match_start row is too short")
    map_name, map_type, t1, t2 = start[2], start[3], start[4], start[5]
    team_no = {t1: 1, t2: 2}
    events = events[events.index(start):]

    latest: dict[tuple[str, str], dict] = {}
    team_of: dict[str, int] = {}
    last_time = 0.0
    score = (0, 0)
    complete = False
    first_kill_round: dict[int, int] = {}
    current_round = 0

    for e in events:
        kind = e[0]
        if len(e) > 1:
            last_time = max(last_time, to_number(e[1]))
        if kind == "round_start" and len(e) > 2:
            current_round = int(to_number(e[2]))
        elif kind == "kill" and len(e) > 5 and current_round not in first_kill_round:
            killer_team = team_no.get(e[2]) or team_no.get(e[5])
            if e[2] in team_no:
                first_kill_round[current_round] = team_no[e[2]]
            elif killer_team:  # environmental kill credited to 'All Teams'
                first_kill_round[current_round] = 3 - team_no[e[5]]
        elif kind == "round_end" and len(e) > 5:
            score = (int(to_number(e[4])), int(to_number(e[5])))
        elif kind == "match_end" and len(e) > 4:
            score = (int(to_number(e[3])), int(to_number(e[4])))
            complete = True
        elif kind == "player_stat" and len(e) > len(PLAYER_STAT_FIELDS):
            row = {}
            for name, value in zip(PLAYER_STAT_FIELDS, e[1:]):
                row[name] = value if name in TEXT_FIELDS else to_number(value)
            if row["team"] not in team_no or not row["player"]:
                continue
            key = (row["player"], row["hero"])
            if key not in latest or row["round"] >= latest[key]["round"]:
                latest[key] = row
                team_of[row["player"]] = team_no[row["team"]]

    if not latest:
        raise LogError("no player_stat rows; enable the Player Stat Summary in ScrimTime")

    players: dict[str, PlayerMap] = {}
    for (name, hero), row in latest.items():
        p = players.setdefault(name, PlayerMap(name=name, team=team_of[name]))
        p.heroes[hero] = {k: row[k] for k in STAT_KEYS}
    # Drop heroes picked for a moment and never played (zero time).
    for p in players.values():
        played = {h: s for h, s in p.heroes.items() if s["time_played"] > 0}
        p.heroes = played or p.heroes

    first_kills = {1: 0, 2: 0}
    for team in first_kill_round.values():
        first_kills[team] += 1

    return MapResult(
        id=map_id,
        played_at=played_at,
        map_name=map_name,
        map_type=map_type,
        team_names=(t1, t2),
        score=score,
        complete=complete,
        duration=last_time,
        players=sorted(players.values(), key=lambda p: (p.team, p.name.lower())),
        first_kills=first_kills,
    )


def parse_file(path: str | Path) -> MapResult:
    path = Path(path)
    text = path.read_text(encoding="utf-8", errors="replace")
    return parse_text(text, map_id=path.stem, played_at=played_at_from(path))


def parse_folder(folder: str | Path) -> tuple[list[MapResult], list[str]]:
    """Parse every .txt log in a folder. Returns maps (oldest first) and warnings."""
    maps, warnings, seen = [], [], {}
    for path in sorted(Path(folder).glob("*.txt")):
        try:
            m = parse_file(path)
        except LogError as exc:
            warnings.append(f"{path.name}: skipped, {exc}")
            continue
        fingerprint = (m.map_name, round(m.duration, 2),
                       tuple(sorted(p.name for p in m.players)))
        if fingerprint in seen:
            warnings.append(f"{path.name}: skipped, duplicate of {seen[fingerprint]}")
            continue
        seen[fingerprint] = path.name
        if not m.complete:
            warnings.append(f"{path.name}: no match_end, so it is shown but not rated")
        maps.append(m)
    maps.sort(key=lambda m: (m.played_at, m.id))
    return maps, warnings
