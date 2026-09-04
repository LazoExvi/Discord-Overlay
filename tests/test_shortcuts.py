import sys

import pytest

from discord_overlay import shortcuts


def test_launch_target_points_at_this_checkout_when_not_frozen():
    program, arguments = shortcuts.launch_target()
    assert program.lower().endswith(("python.exe", "pythonw.exe"))
    assert arguments.endswith('main.py"')


@pytest.mark.skipif(sys.platform != "win32", reason="Windows shell shortcuts")
def test_create_and_remove_shortcut(tmp_path):
    link = shortcuts.create_shortcut(tmp_path)
    assert link.is_file() and link.name == "Discord Overlay.lnk"
    assert shortcuts.shortcut_exists(tmp_path)
    assert shortcuts.shortcut_target(tmp_path).lower() == shortcuts.launch_target()[0].lower()
    assert shortcuts.repair_shortcuts() == []  # not frozen: nothing to do
    assert shortcuts.remove_shortcut(tmp_path)
    assert shortcuts.shortcut_target(tmp_path) is None
    assert not shortcuts.shortcut_exists(tmp_path)
    assert not shortcuts.remove_shortcut(tmp_path)
