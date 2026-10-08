"""Load club settings, the hero list and the player roster from config/."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

ROLES = ("tank", "damage", "support")
TEAM_SHAPE = {"tank": 1, "damage": 2, "support": 2}  # 5v5 role queue


@dataclass
class Club:
    name: str = "Overwatch Club"
    season: str = ""
    min_maps: int = 5
    repo: str = ""


@dataclass
class Roster:
    """Maps in-game names to one canonical name per person."""
    canonical: dict[str, str] = field(default_factory=dict)  # lowercased alias -> name

    def resolve(self, ingame: str) -> str:
        return self.canonical.get(ingame.casefold(), ingame)


def _load(path: Path):
    if not path.exists():
        return None
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def load_club(config_dir: Path) -> Club:
    data = _load(config_dir / "club.yaml") or {}
    return Club(**{k: v for k, v in data.items() if k in Club.__dataclass_fields__})


def load_heroes(config_dir: Path) -> dict[str, str]:
    data = _load(config_dir / "heroes.yaml") or {}
    roles = {}
    for role, heroes in data.items():
        if role not in ROLES:
            raise ValueError(f"heroes.yaml: unknown role '{role}', use one of {ROLES}")
        for hero in heroes or []:
            roles[str(hero)] = role
    return roles


def load_roster(config_dir: Path) -> Roster:
    data = _load(config_dir / "players.yaml") or {}
    roster = Roster()
    for entry in data.get("players", []) or []:
        name = str(entry["name"])
        for alias in [name, *map(str, entry.get("aliases", []) or [])]:
            key = alias.casefold()
            if key in roster.canonical and roster.canonical[key] != name:
                raise ValueError(f"players.yaml: '{alias}' is listed under two players")
            roster.canonical[key] = name
    return roster
