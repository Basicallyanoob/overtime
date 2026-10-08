"""Load club settings, the hero list and the player roster from config/."""
from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

ROLES = ("tank", "damage", "support")
TEAM_SHAPE = {"tank": 1, "damage": 2, "support": 2}  # 5v5 role queue
ROSTER_FILE = "players.csv"
ROSTER_HEADER = ["name", "ingame_names", "roles"]

# Column headings people tend to use in a sign-up sheet, mapped to ours.
_COLUMNS = {
    "name": {"name", "player", "display name", "member", "full name"},
    "ingame_names": {"ingame_names", "in-game names", "in-game name", "ingame names", "ingame",
                     "battletag", "battletags", "battle tag", "battle.net", "btag", "aliases",
                     "overwatch name", "overwatch names"},
    "roles": {"roles", "role", "preferred roles", "preferred role", "main role", "roles played"},
}


@dataclass
class Club:
    name: str = "Overwatch Club"
    short_name: str = ""
    game: str = "Overwatch"
    season: str = ""
    logo: str = ""
    min_maps: int = 5
    repo: str = ""


@dataclass
class Roster:
    """Who is in the club, every name they play under, and the roles they want."""
    canonical: dict[str, str] = field(default_factory=dict)  # normalised in-game name -> name
    roles: dict[str, list[str]] = field(default_factory=dict)  # name -> roles in preference order
    names: list[str] = field(default_factory=list)  # club members in file order

    def resolve(self, ingame: str) -> str:
        return self.canonical.get(normalise(ingame), ingame)

    def knows(self, ingame: str) -> bool:
        return normalise(ingame) in self.canonical


def normalise(name: str) -> str:
    """Logs show 'Kestrel' where a BattleTag reads 'Kestrel#21934'."""
    return re.sub(r"#\d+$", "", name.strip()).casefold()


def split_names(text: str) -> list[str]:
    return [n.strip() for n in re.split(r"[;|\n]", text or "") if n.strip()]


def _load_yaml(path: Path):
    if not path.exists():
        return None
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def load_club(config_dir: Path) -> Club:
    data = _load_yaml(config_dir / "club.yaml") or {}
    return Club(**{k: v for k, v in data.items() if k in Club.__dataclass_fields__})


def load_heroes(config_dir: Path) -> dict[str, str]:
    data = _load_yaml(config_dir / "heroes.yaml") or {}
    roles = {}
    for role, heroes in data.items():
        if role not in ROLES:
            raise ValueError(f"heroes.yaml: unknown role '{role}', use one of {ROLES}")
        for hero in heroes or []:
            roles[str(hero)] = role
    return roles


def read_roster_rows(path: Path) -> list[dict[str, str]]:
    """Read players.csv, accepting a spreadsheet export with its own headings."""
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as fh:
        reader = csv.reader(fh)
        header = next(reader, [])
        index = {}
        for i, col in enumerate(header):
            key = col.strip().lower()
            for ours, aliases in _COLUMNS.items():
                if key in aliases and ours not in index:
                    index[ours] = i
        if "name" not in index:
            raise ValueError(f"{path.name}: needs a 'name' column (found: {', '.join(header)})")
        rows = []
        for raw in reader:
            if not any(c.strip() for c in raw) or raw[0].lstrip().startswith("#"):
                continue
            get = lambda k: raw[index[k]].strip() if k in index and index[k] < len(raw) else ""
            rows.append({k: get(k) for k in ROSTER_HEADER})
        return rows


def load_roster(config_dir: Path) -> Roster:
    from .balance import parse_roles  # local import: balance imports this module

    path = config_dir / ROSTER_FILE
    roster = Roster()
    for line, row in enumerate(read_roster_rows(path), start=2):
        name = row["name"]
        if not name:
            continue
        if name not in roster.names:
            roster.names.append(name)
        for alias in [name, *split_names(row["ingame_names"])]:
            key = normalise(alias)
            if key in roster.canonical and roster.canonical[key] != name:
                raise ValueError(f"{ROSTER_FILE} line {line}: '{alias}' is already listed "
                                 f"under {roster.canonical[key]}")
            roster.canonical[key] = name
        if row["roles"]:
            try:
                roster.roles[name] = parse_roles(row["roles"])
            except ValueError as exc:
                raise ValueError(f"{ROSTER_FILE} line {line}: {exc}") from None
    return roster


def append_players(config_dir: Path, names: list[str]) -> Path:
    """Add new rows to players.csv, creating it with a header if needed."""
    path = config_dir / ROSTER_FILE
    new_file = not path.exists() or not path.read_text(encoding="utf-8-sig").strip()
    with path.open("a", encoding="utf-8", newline="") as fh:
        if not new_file and not path.read_text(encoding="utf-8").endswith("\n"):
            fh.write("\n")
        writer = csv.writer(fh)
        if new_file:
            writer.writerow(ROSTER_HEADER)
        for n in names:
            writer.writerow([n, n, ""])
    return path
