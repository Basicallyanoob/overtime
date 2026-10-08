"""Copy new ScrimTime logs into the repository, one folder per club night.

Accepts the game's Workshop folder, any other folder, single files, or a .zip.
Files that are not ScrimTime logs, and maps already in logs/, are skipped, so
pointing it at the whole Workshop folder every week is safe.
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from .config import Roster
from .parse import LogError, fingerprint, parse_file, parse_folder


def workshop_folders() -> list[Path]:
    """Where Overwatch saves Workshop logs on Windows (the game is Windows-only)."""
    home = Path.home()
    candidates = [home / "Documents" / "Overwatch" / "Workshop",
                  home / "OneDrive" / "Documents" / "Overwatch" / "Workshop"]
    if os.environ.get("OneDrive"):
        candidates.append(Path(os.environ["OneDrive"]) / "Documents" / "Overwatch" / "Workshop")
    return [p for p in dict.fromkeys(candidates) if p.is_dir()]


@dataclass
class ImportReport:
    added: list[Path] = field(default_factory=list)
    duplicates: int = 0
    not_logs: list[str] = field(default_factory=list)
    unfinished: list[str] = field(default_factory=list)
    new_names: dict[str, int] = field(default_factory=dict)  # in-game name -> maps


def _candidates(sources: list[Path], scratch: Path) -> list[Path]:
    files = []
    for src in sources:
        if src.is_dir():
            files += sorted(src.rglob("*.txt"))
        elif src.suffix.lower() == ".zip":
            with zipfile.ZipFile(src) as zf:
                for member in zf.namelist():
                    if member.lower().endswith(".txt") and not member.startswith("__MACOSX"):
                        target = scratch / Path(member).name
                        target.write_bytes(zf.read(member))
                        files.append(target)
        elif src.is_file():
            files.append(src)
        else:
            raise FileNotFoundError(f"{src} does not exist")
    return files


def import_logs(sources: list[Path], dest: Path, roster: Roster) -> ImportReport:
    dest.mkdir(parents=True, exist_ok=True)
    existing, _ = parse_folder(dest)
    seen = {fingerprint(m) for m in existing}
    report = ImportReport()
    with tempfile.TemporaryDirectory() as tmp:
        for path in _candidates(sources, Path(tmp)):
            try:
                m = parse_file(path)
            except (LogError, UnicodeError, OSError):
                report.not_logs.append(path.name)
                continue
            fp = fingerprint(m)
            if fp in seen:
                report.duplicates += 1
                continue
            seen.add(fp)
            night = dest / m.played_at.date().isoformat()
            night.mkdir(exist_ok=True)
            target = night / path.name
            n = 2
            while target.exists():
                target = night / f"{path.stem}-{n}{path.suffix}"
                n += 1
            shutil.copy2(path, target)
            report.added.append(target)
            if not m.complete:
                report.unfinished.append(path.name)
            for p in m.players:
                if not roster.knows(p.name):
                    report.new_names[p.name] = report.new_names.get(p.name, 0) + 1
    return report


def unknown_names(logs: Path, roster: Roster) -> dict[str, int]:
    """In-game names in the logs that players.csv does not cover, with map counts."""
    maps, _ = parse_folder(logs)
    counts: dict[str, int] = {}
    for m in maps:
        for p in m.players:
            if not roster.knows(p.name):
                counts[p.name] = counts.get(p.name, 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0].casefold())))


def default_sources() -> list[Path]:
    found = workshop_folders()
    if not found:
        where = "Documents/Overwatch/Workshop" if sys.platform.startswith("win") else \
            "the Workshop folder copied from the host's PC"
        raise FileNotFoundError(f"No Workshop folder found. Pass the folder or files to import, "
                                f"e.g. overtime import {where}")
    return found
