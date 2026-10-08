from overtime.cli import main


def build(logs, config, out):
    return main(["--logs", str(logs), "--config", str(config), "build", "--out", str(out)])


def test_build_site(demo_logs, config, tmp_path):
    out = tmp_path / "site"
    assert build(demo_logs, config, out) == 0
    index = (out / "index.html").read_text(encoding="utf-8")
    assert "DUES Overwatch" in index and "Kestrel" in index
    assert (out / "logo.png").exists() and 'rel="icon"' in index
    pike = (out / "players" / "pike.html").read_text(encoding="utf-8")
    assert "Also plays as PikeOnAlt" in pike
    assert not (out / "players" / "pikeonalt.html").exists()
    assert len(list((out / "matches").glob("Log-*.html"))) == len(list(demo_logs.glob("*.txt")))
    # Roster members with no maps yet can still be picked in the team builder.
    assert '"Newbie"' in (out / "builder.html").read_text(encoding="utf-8")


def test_build_with_no_logs_shows_how_to_start(config, tmp_path, capsys):
    empty = tmp_path / "logs"
    empty.mkdir()
    out = tmp_path / "site"
    assert build(empty, config, out) == 0
    assert "No maps yet" in (out / "index.html").read_text(encoding="utf-8")
    assert "No maps in" in capsys.readouterr().out


def test_teams_command_uses_roster_roles(demo_logs, config, tmp_path, capsys):
    csv = tmp_path / "signups.csv"
    csv.write_text("player,roles\nKestrel,damage\nMarrow,tank\nLumen,support\nQuill,damage>support\n"
                   "PikeOnAlt,\nRook,tank\nVesper,dps\nHalcyon,damage/support\nTidal,support\n"
                   "Juniper,support>tank\n", encoding="utf-8")
    assert main(["--logs", str(demo_logs), "--config", str(config), "teams", str(csv)]) == 0
    out = capsys.readouterr().out
    assert "Option 1" in out and "Pike" in out and "PikeOnAlt" not in out
