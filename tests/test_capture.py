import pytest


def test_geometry_helpers_handle_monitors_left_of_the_primary(monkeypatch):
    from discord_overlay import capture
    from discord_overlay.models import Region

    assert capture.tk_geometry(2560, 1440, -2560, -139) == "2560x1440+-2560+-139"
    assert capture.parse_geometry("340x230+-2560+-139") == (340, 230, -2560, -139)
    assert capture.parse_geometry("340x230+40+80") == (340, 230, 40, 80)
    assert capture.parse_geometry("garbage") is None
    pytest.importorskip("customtkinter")
    from discord_overlay.ui.overlays import offset_geometry
    assert offset_geometry("190x52+-2500+100", 2) == "190x52+-2444+156"

    monkeypatch.setattr(capture, "monitor_rects", lambda: [
        {"left": 0, "top": 0, "width": 1920, "height": 1080},
        {"left": -2560, "top": -139, "width": 2560, "height": 1440},
    ])
    assert capture.region_on_screen(Region(-2000, 500, 800, 500))
    assert capture.region_on_screen(Region(100, 100, 800, 500))
    # Straddles the seam between monitors / hangs below both: not usable.
    assert not capture.region_on_screen(Region(-136, 1089, 775, 508))
    assert not capture.region_on_screen(Region(1500, 900, 800, 500))


def test_saved_overlay_positions_off_every_monitor_are_rejected(monkeypatch):
    from discord_overlay import capture

    monkeypatch.setattr(capture, "monitor_rects", lambda: [
        {"left": 0, "top": 0, "width": 1920, "height": 1080},
        {"left": -2560, "top": -139, "width": 2560, "height": 1440},
    ])
    assert capture.geometry_on_screen("340x230+100+550")
    assert capture.geometry_on_screen("280x514+-2400+62")
    # Positions from the old layout, right of a primary that no longer has a neighbour there.
    assert not capture.geometry_on_screen("340x230+1982+550")
    assert not capture.geometry_on_screen("280x514+2136+62")
    assert not capture.geometry_on_screen("")
