"""Valorant inhouses: fetch custom games from the HenrikDev API, store and load them.

Valorant has no log file like ScrimTime's, so games come from match history.
The unofficial HenrikDev API (https://docs.henrikdev.xyz) returns an account's
recent games with full scoreboards, custom games included. `fetch` checks the
accounts in config/valorant.yaml, keeps finished custom games with enough
players, and saves a trimmed copy of each in valorant/, one folder per night.

Games can also be typed in from the end-of-game scoreboard as a CSV
(see examples/valorant-scoreboard.csv) and dropped in the same folder.
"""
from __future__ import annotations

import csv
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .config import Roster, ValorantSettings, normalise_riot

API = "https://api.henrikdev.xyz/valorant/v4/matches/{region}/pc/{name}/{tag}"
PAGE = 10  # games per API request
TEAMS = ("Blue", "Red")  # team 1 and team 2, matching the site's blue and red
TIMEZONE = "Europe/Dublin"


class ValorantError(Exception):
    """A problem worth telling the person running the import about, in plain words."""


@dataclass
class ValPlayer:
    puuid: str
    riot_name: str
    tag: str
    team: int  # 1 = Blue, 2 = Red
    agent: str
    score: float  # combat score summed over the game; ACS = score / rounds
    kills: int
    deaths: int
    assists: int
    headshots: int | None = None
    bodyshots: int | None = None
    legshots: int | None = None
    damage: int | None = None
    first_bloods: int | None = None
    name: str = ""  # club display name, filled in by the season builder

    @property
    def riot_id(self) -> str:
        return f"{self.riot_name}#{self.tag}" if self.tag else self.riot_name


@dataclass
class ValMatch:
    id: str
    map_name: str
    played_at: datetime  # local time, naive, like the Overwatch logs
    duration: float  # seconds
    score: tuple[int, int]  # rounds won by team 1 (Blue), team 2 (Red)
    players: list[ValPlayer]
    source: str = "api"  # or "manual"
    path: Path | None = None
    complete: bool = True
    team_names: tuple[str, str] = TEAMS

    @property
    def rounds(self) -> int:
        return sum(self.score)

    @property
    def winner(self) -> int:
        a, b = self.score
        return 1 if a > b else (2 if b > a else 0)

    @property
    def map_type(self) -> str:
        return f"{self.rounds} rounds"

    def team(self, t: int) -> list[ValPlayer]:
        return [p for p in self.players if p.team == t]


# ---------- reading the API's match format ----------

def is_inhouse(raw: dict, min_players: int) -> tuple[bool, str]:
    """Whether a match from the API counts, and if not, why not."""
    md = raw.get("metadata") or {}
    queue = md.get("queue") or {}
    qid, qname = (queue.get("id") or "").lower(), (queue.get("name") or "").lower()
    if not (qname.startswith("custom") or qid == "custom" or (qid == "" and not qname)):
        return False, f"a {queue.get('name') or queue.get('id') or 'non-custom'} game"
    if not md.get("is_completed", True):
        return False, "not finished"
    teams = {t.get("team_id") for t in raw.get("teams") or []}
    if teams != set(TEAMS):
        return False, "not a Blue against Red game"
    n = len(raw.get("players") or [])
    if n < min_players:
        return False, f"only {n} player{'s' if n != 1 else ''}"
    return True, ""


def trim(raw: dict) -> dict:
    """Keep what the site uses from an API match (about 3% of its size)."""
    md = raw["metadata"]
    first = {}
    for rnd in raw.get("rounds") or []:
        fb = rnd.get("first_blood") or {}
        if fb.get("puuid"):
            first[fb["puuid"]] = first.get(fb["puuid"], 0) + 1
    teams = {t["team_id"]: (t.get("rounds") or {}).get("won", 0) for t in raw["teams"]}
    players = []
    for p in raw["players"]:
        st = p.get("stats") or {}
        dmg = st.get("damage") or {}
        players.append({
            "puuid": p.get("puuid", ""), "name": p.get("name", ""), "tag": p.get("tag", ""),
            "team": p.get("team_id"), "agent": (p.get("agent") or {}).get("name") or "Unknown",
            "score": st.get("score", 0), "kills": st.get("kills", 0), "deaths": st.get("deaths", 0),
            "assists": st.get("assists", 0), "headshots": st.get("headshots"),
            "bodyshots": st.get("bodyshots"), "legshots": st.get("legshots"),
            "damage": dmg.get("dealt"), "first_bloods": first.get(p.get("puuid"), 0),
        })
    return {
        "format": "overtime-valorant-1", "source": "henrikdev", "id": md["match_id"],
        "map": (md.get("map") or {}).get("name") or "Unknown map",
        "started_at": md["started_at"], "length_ms": md.get("game_length_in_ms", 0),
        "server": md.get("cluster") or "", "rounds": teams, "players": players,
    }


def _local(started_at: str) -> datetime:
    when = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    try:
        from zoneinfo import ZoneInfo
        return when.astimezone(ZoneInfo(TIMEZONE)).replace(tzinfo=None)
    except Exception:  # no time zone database (Windows without tzdata): show UTC
        return when.astimezone(timezone.utc).replace(tzinfo=None)


def from_trimmed(data: dict, path: Path | None = None) -> ValMatch:
    side = {name: i + 1 for i, name in enumerate(TEAMS)}
    players = [ValPlayer(p["puuid"], p["name"], p.get("tag", ""), side[p["team"]], p["agent"],
                         p["score"], p["kills"], p["deaths"], p["assists"], p.get("headshots"),
                         p.get("bodyshots"), p.get("legshots"), p.get("damage"), p.get("first_bloods"))
               for p in data["players"]]
    return ValMatch(data["id"], data["map"], _local(data["started_at"]), data.get("length_ms", 0) / 1000,
                    (data["rounds"].get("Blue", 0), data["rounds"].get("Red", 0)), players,
                    data.get("source", "henrikdev"), path)


# ---------- scoreboards typed in by hand ----------

_CSV_COLUMNS = {
    "date": {"date", "time", "date and time", "played", "played at"},
    "map": {"map"},
    "team": {"team", "side"},
    "rounds": {"rounds", "rounds won", "score", "team score"},
    "player": {"player", "name", "riot id", "riot_id"},
    "agent": {"agent"},
    "acs": {"acs", "combat score", "average combat score"},
    "kills": {"k", "kills"},
    "deaths": {"d", "deaths"},
    "assists": {"a", "assists"},
    "first_bloods": {"fb", "first bloods", "first_bloods", "first kills"},
}
_TEAM_WORDS = {"blue": 1, "a": 1, "1": 1, "team a": 1, "defenders": 1,
               "red": 2, "b": 2, "2": 2, "team b": 2, "attackers": 2}


def parse_scoreboard_csv(path: Path) -> ValMatch:
    """One map typed in from the scoreboard: a row per player.

    Columns: date, map, team, rounds (won by that team), player, agent,
    acs, kills, deaths, assists, and optionally first_bloods.
    """
    with path.open(encoding="utf-8-sig", newline="") as fh:
        rows = [r for r in csv.reader(fh) if any(c.strip() for c in r) and not r[0].lstrip().startswith("#")]
    if not rows:
        raise ValorantError(f"{path.name}: empty")
    header = [h.strip().lower() for h in rows[0]]
    col = {}
    for ours, names in _CSV_COLUMNS.items():
        col[ours] = next((i for i, h in enumerate(header) if h in names), None)
    missing = [c for c in ("date", "map", "team", "rounds", "player", "agent", "acs", "kills", "deaths", "assists")
               if col[c] is None]
    if missing:
        raise ValorantError(f"{path.name}: missing column{'s' if len(missing) > 1 else ''} {', '.join(missing)}")
    get = lambda r, c: r[col[c]].strip() if col[c] is not None and col[c] < len(r) else ""
    body = rows[1:]
    if len(body) < 2:
        raise ValorantError(f"{path.name}: needs a row for each player")

    def num(r, c, line):
        v = get(r, c)
        try:
            return float(v) if "." in v else int(v)
        except ValueError:
            raise ValorantError(f"{path.name} line {line}: {c} '{v}' is not a number") from None

    first = body[0]
    when_text = get(first, "date")
    try:
        played = datetime.fromisoformat(when_text.replace("/", "-"))
    except ValueError:
        raise ValorantError(f"{path.name}: date '{when_text}' should look like 2026-10-14 19:30") from None
    score = {1: None, 2: None}
    players = []
    for line, r in enumerate(body, start=2):
        team = _TEAM_WORDS.get(get(r, "team").lower())
        if team is None:
            raise ValorantError(f"{path.name} line {line}: team '{get(r, 'team')}' should be Blue or Red")
        won = num(r, "rounds", line)
        if score[team] is not None and score[team] != won:
            raise ValorantError(f"{path.name} line {line}: {TEAMS[team - 1]} has two different round scores")
        score[team] = won
        players.append([r, team, line])
    if None in score.values():
        raise ValorantError(f"{path.name}: needs players on both Blue and Red")
    rounds = score[1] + score[2]
    out = []
    for r, team, line in players:
        name, _, tag = get(r, "player").partition("#")
        fb = get(r, "first_bloods")
        out.append(ValPlayer(f"manual:{normalise_riot(get(r, 'player'))}", name.strip(), tag.strip(), team,
                             get(r, "agent") or "Unknown", num(r, "acs", line) * rounds,
                             num(r, "kills", line), num(r, "deaths", line), num(r, "assists", line),
                             first_bloods=int(fb) if fb.isdigit() else None))
    return ValMatch(f"manual-{_slug(path.parent.name)}-{_slug(path.stem)}", get(first, "map") or "Unknown map", played, 0,
                    (score[1], score[2]), out, "manual", path)


# ---------- loading a folder ----------

def load_folder(folder: Path) -> tuple[list[ValMatch], list[str]]:
    """Every stored game, oldest first, and a note for each file that could not be read."""
    folder = Path(folder)
    matches, warnings, seen = [], [], set()
    if not folder.is_dir():
        return matches, warnings
    for path in sorted(folder.rglob("*")):
        if path.suffix.lower() not in (".json", ".csv") or not path.is_file():
            continue
        try:
            if path.suffix.lower() == ".json":
                m = from_trimmed(json.loads(path.read_text(encoding="utf-8")), path)
            else:
                m = parse_scoreboard_csv(path)
        except ValorantError as exc:
            warnings.append(str(exc))
            continue
        except (KeyError, TypeError, ValueError) as exc:
            warnings.append(f"{path.name}: not a game file this site can read ({exc})")
            continue
        if m.id in seen:
            continue
        seen.add(m.id)
        matches.append(m)
    matches.sort(key=lambda m: m.played_at)
    return matches, warnings


def stored_ids(folder: Path) -> set[str]:
    ids = set()
    for path in Path(folder).rglob("*.json"):
        try:
            ids.add(json.loads(path.read_text(encoding="utf-8"))["id"])
        except (ValueError, KeyError, TypeError):
            pass
    return ids


# ---------- importing ----------

@dataclass
class ValImportReport:
    added: list[Path] = field(default_factory=list)
    duplicates: int = 0
    skipped: dict[str, int] = field(default_factory=dict)  # reason -> games
    new_ids: dict[str, int] = field(default_factory=dict)  # Riot ID not on the roster -> games
    checked: list[str] = field(default_factory=list)  # accounts looked at
    errors: list[str] = field(default_factory=list)


def _slug(text: str) -> str:
    return "".join(c if c.isalnum() else "-" for c in text.lower()).strip("-") or "map"


def save_matches(raws: list[dict], dest: Path, settings: ValorantSettings, roster: Roster,
                 report: ValImportReport | None = None) -> ValImportReport:
    report = report or ValImportReport()
    have = stored_ids(dest)
    for raw in raws:
        mid = (raw.get("metadata") or {}).get("match_id")
        if not mid:
            continue
        if mid in have:
            report.duplicates += 1
            continue
        ok, why = is_inhouse(raw, settings.min_players)
        if not ok:
            report.skipped[why] = report.skipped.get(why, 0) + 1
            continue
        data = trim(raw)
        when = _local(data["started_at"])
        target = dest / when.date().isoformat() / f"{when:%H%M}-{_slug(data['map'])}-{mid[:8]}.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        have.add(mid)
        report.added.append(target)
        for p in data["players"]:
            if roster.resolve_riot(p["name"], p["tag"]) is None:
                rid = f"{p['name']}#{p['tag']}"
                report.new_ids[rid] = report.new_ids.get(rid, 0) + 1
    return report


def matches_in(payload) -> list[dict]:
    """Matches from an API response, a list of matches, or one match."""
    if isinstance(payload, dict) and "data" in payload:
        payload = payload["data"]
    if isinstance(payload, dict):
        payload = [payload]
    return [m for m in payload or [] if isinstance(m, dict) and "metadata" in m]


def import_files(paths: list[Path], dest: Path, settings: ValorantSettings, roster: Roster) -> ValImportReport:
    """Import API responses saved from a browser, e.g. the test link's page saved as JSON."""
    raws = []
    for path in paths:
        if not path.is_file():
            raise FileNotFoundError(f"{path} does not exist")
        try:
            raws += matches_in(json.loads(path.read_text(encoding="utf-8-sig")))
        except ValueError:
            raise ValorantError(f"{path.name} is not JSON from the HenrikDev API") from None
    return save_matches(raws, dest, settings, roster)


def _get(url: str, key: str, opener=urllib.request.urlopen) -> dict:
    req = urllib.request.Request(url, headers={"Authorization": key, "Accept": "application/json",
                                               "User-Agent": "overtime-inhouse-stats"})
    for attempt in range(3):
        try:
            with opener(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code == 429 and attempt < 2:
                time.sleep(int(exc.headers.get("Retry-After") or 30))
                continue
            if exc.code in (401, 403):
                raise ValorantError("the API key was refused. Check HENRIKDEV_API_KEY, or make a new key "
                                    "on the HenrikDev dashboard") from None
            if exc.code == 404:
                raise ValorantError("account not found: check the name, tag and region") from None
            raise ValorantError(f"the API answered {exc.code} {exc.reason}") from None
        except urllib.error.URLError as exc:
            raise ValorantError(f"could not reach the API ({exc.reason})") from None
    raise ValorantError("the API is rate limiting this key; try again in a minute")


def fetch_history(account: str, settings: ValorantSettings, key: str, opener=urllib.request.urlopen) -> list[dict]:
    name, _, tag = account.partition("#")
    base = API.format(region=urllib.parse.quote(settings.region, safe=""),
                      name=urllib.parse.quote(name.strip(), safe=""), tag=urllib.parse.quote(tag.strip(), safe=""))
    out = []
    for start in range(0, max(settings.history, 1), PAGE):
        size = min(PAGE, settings.history - start)
        page = matches_in(_get(f"{base}?size={size}&start={start}", key, opener))
        out += page
        if len(page) < size:
            break
    return out


def fetch(settings: ValorantSettings, key: str, dest: Path, roster: Roster,
          accounts: list[str] | None = None, opener=urllib.request.urlopen) -> ValImportReport:
    accounts = accounts or settings.accounts
    if not accounts:
        raise ValorantError("no accounts to check: list the host's Riot ID under accounts in config/valorant.yaml")
    if not key:
        raise ValorantError("no API key: set HENRIKDEV_API_KEY (on GitHub, as a repository secret)")
    report = ValImportReport()
    raws = []
    for account in accounts:
        try:
            raws += fetch_history(account, settings, key, opener)
            report.checked.append(account)
        except ValorantError as exc:
            if "API key" in str(exc):
                raise
            report.errors.append(f"{account}: {exc}")
    return save_matches(raws, dest, settings, roster, report)
