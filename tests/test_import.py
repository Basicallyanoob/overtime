import shutil
import zipfile

import pytest

from overtime.cli import main
from overtime.config import load_roster, normalise


def test_roster_reads_spreadsheet_exports(tmp_path):
    (tmp_path / "players.csv").write_text(
        "﻿Player,BattleTag,Preferred roles,Year\n"
        "Aoife,Aoife#1234; aoife_alt,Support>DPS,2\n"
        "Cian,CianOW#99,flex,3\n", encoding="utf-8")
    r = load_roster(tmp_path)
    assert r.resolve("AOIFE") == "Aoife" and r.resolve("aoife_alt") == "Aoife"
    assert r.resolve("CianOW") == "Cian"  # BattleTag number is not in the logs
    assert r.roles == {"Aoife": ["support", "damage"], "Cian": ["tank", "damage", "support"]}
    assert normalise("Name#12345") == "name"


def test_roster_rejects_a_name_listed_twice(tmp_path):
    (tmp_path / "players.csv").write_text("name,ingame_names\nA,shared\nB,shared\n", encoding="utf-8")
    with pytest.raises(ValueError, match="already listed under A"):
        load_roster(tmp_path)


def test_import_files_by_night_and_skips_repeats(demo_logs, config, tmp_path, capsys):
    workshop = tmp_path / "Workshop"
    workshop.mkdir()
    logs = sorted(demo_logs.glob("*.txt"))
    for f in logs[:4]:
        shutil.copy(f, workshop)
    (workshop / "Log-2026-10-01-12-00-00.txt").write_text("some other workshop mode\n")
    dest = tmp_path / "logs"
    args = ["--logs", str(dest), "--config", str(config), "import", str(workshop)]
    assert main(args) == 0
    out = capsys.readouterr().out
    assert "Added 4 new maps" in out and "ignored 1" in out
    nights = sorted(p.name for p in dest.iterdir())
    assert nights == ["2026-09-02"]
    assert "Kestrel" in out  # not on the roster yet
    # Running again adds nothing.
    assert main(args) == 0
    assert "Added 0 new maps, skipped 4 already imported" in capsys.readouterr().out


def test_import_from_zip_and_add_players(demo_logs, config, tmp_path, capsys):
    archive = tmp_path / "night.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        for f in sorted(demo_logs.glob("*.txt"))[:2]:
            zf.write(f, f"exported/{f.name}")
    dest = tmp_path / "logs"
    assert main(["--logs", str(dest), "--config", str(config), "import", str(archive), "--add"]) == 0
    assert "Added 2 new maps" in capsys.readouterr().out
    roster = load_roster(config)
    assert len(roster.names) >= 10  # Pike and Newbie, plus everyone new in those two maps
    # Nothing left to add afterwards.
    assert main(["--logs", str(dest), "--config", str(config), "players"]) == 0
    assert "Every in-game name" in capsys.readouterr().out
