import importlib.util
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _demo_module():
    spec = importlib.util.spec_from_file_location("make_demo_logs", ROOT / "scripts" / "make_demo_logs.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="session")
def demo_logs(tmp_path_factory):
    """An invented season of logs, the same every run."""
    folder = tmp_path_factory.mktemp("logs")
    _demo_module().main(folder, seed=7)
    return folder


@pytest.fixture
def config(tmp_path):
    """The real config folder, with a roster that folds Pike's alt into one profile."""
    folder = tmp_path / "config"
    shutil.copytree(ROOT / "config", folder)
    (folder / "players.csv").write_text(
        "name,ingame_names,roles\nPike,Pike#2211;PikeOnAlt,tank>support\nNewbie,Newbie#1,support\n",
        encoding="utf-8")
    return folder
