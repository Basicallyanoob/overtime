import shutil
from pathlib import Path

from overtime.cli import main

ROOT = Path(__file__).resolve().parents[1]


def test_build_demo_site(tmp_path):
    out = tmp_path / "site"
    assert main(["--logs", str(ROOT / "logs"), "--config", str(ROOT / "config"),
                 "build", "--out", str(out)]) == 0
    index = (out / "index.html").read_text(encoding="utf-8")
    assert "Leaderboard" in index and "Kestrel" in index
    assert (out / "players" / "pike.html").exists()
    # Pike's alt account is folded into one profile by players.yaml.
    assert not (out / "players" / "pikeonalt.html").exists()
    assert "Also plays as PikeOnAlt" in (out / "players" / "pike.html").read_text(encoding="utf-8")
    assert len(list((out / "matches").glob("Log-*.html"))) == len(list((ROOT / "logs").glob("*.txt")))
    assert (out / "fonts" / "fonts.css").exists()


def test_build_with_no_logs_fails_clearly(tmp_path, capsys):
    empty = tmp_path / "logs"
    empty.mkdir()
    assert main(["--logs", str(empty), "--config", str(ROOT / "config"), "build",
                 "--out", str(tmp_path / "site")]) == 1
    assert "No usable logs" in capsys.readouterr().err


def test_teams_command(tmp_path, capsys):
    csv = tmp_path / "signups.csv"
    csv.write_text("player,roles\nKestrel,damage\nMarrow,tank\nLumen,support\nQuill,damage>support\n"
                   "PikeOnAlt,any\nRook,tank\nVesper,dps\nHalcyon,damage/support\nTidal,support\n"
                   "Juniper,support>tank\n", encoding="utf-8")
    assert main(["--logs", str(ROOT / "logs"), "--config", str(ROOT / "config"), "teams", str(csv)]) == 0
    out = capsys.readouterr().out
    assert "Option 1" in out and "Pike" in out and "PikeOnAlt" not in out
