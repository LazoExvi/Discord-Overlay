"""Smaller modules: audio, backend, OCR text helpers, paths, performance, trigger packs."""
import wave

import numpy as np

from discord_overlay.audio import DEFAULT_SOUNDS, ensure_default_sounds
from discord_overlay.backend import classify_gpu
from discord_overlay.models import OCRLine, Region
from discord_overlay.ocr_engine import CombatOCREngine
from discord_overlay.paths import app_root, ensure_app_directories, template_path_for
from discord_overlay.performance import (CapabilityResult, faster_result, recommend_profile,
                                         representative_combat_frame)
from discord_overlay.trigger_packs import PACK_FORMAT, build_trigger_pack, parse_trigger_pack
from discord_overlay.triggers import Trigger, TriggerCondition


def test_default_sounds_are_generated_once(app_data):
    paths = ensure_default_sounds()
    assert set(paths) == set(DEFAULT_SOUNDS)
    for path in paths.values():
        with wave.open(str(path)) as handle:
            assert handle.getframerate() == 44_100 and handle.getnframes() > 1000
    stamps = {name: path.stat().st_mtime_ns for name, path in paths.items()}
    assert {name: path.stat().st_mtime_ns for name, path in ensure_default_sounds().items()} == stamps


def test_gpu_classification():
    assert classify_gpu(["NVIDIA GeForce RTX 4070"]) == "nvidia"
    assert classify_gpu(["AMD Radeon RX 7800 XT"]) == "directml"
    assert classify_gpu(["Intel(R) Arc(TM) A770 Graphics"]) == "directml"
    assert classify_gpu(["Intel(R) UHD Graphics 770", "NVIDIA GeForce RTX 3060"]) == "nvidia"
    assert classify_gpu(["Microsoft Basic Display Adapter"]) == "cpu"
    assert classify_gpu([]) == "cpu"


def test_ocr_text_cleanup_and_continuation_join():
    assert CombatOCREngine.clean_text(" You hit | a rat for 1O5 points ") == "You hit I a rat for 105 points"
    assert CombatOCREngine.clean_text("for 1I8 points") == "for 118 points"
    joined = CombatOCREngine._join_continuations([
        OCRLine("a caiman crushes YOU for 382 points of damage.", 0.9, 10),
        OCRLine("(Critical)", 0.7, 30),
        OCRLine("Your iceblast hits a crocodile for 717 points of Cold", 0.95, 50),
        OCRLine("Damage.", 0.8, 70),
        OCRLine("You crush a rat for 5 points of damage.", 0.9, 90),
    ])
    assert [line.text for line in joined] == [
        "a caiman crushes YOU for 382 points of damage. (Critical)",
        "Your iceblast hits a crocodile for 717 points of Cold Damage.",
        "You crush a rat for 5 points of damage.",
    ]
    assert joined[0].confidence == 0.7


def test_text_mask_and_signature_pick_up_glyph_pixels():
    frame = representative_combat_frame(300, 200)
    mask = CombatOCREngine.text_mask(frame)
    assert mask.shape == (200, 300) and mask.sum() > 500
    assert CombatOCREngine.text_signature(frame).shape == (90, 160)
    assert CombatOCREngine.text_signature(np.zeros((200, 300, 3), dtype=np.uint8)).sum() == 0


def test_app_directories_and_template_paths(app_data):
    ensure_app_directories()
    assert app_root() == app_data / "DiscordOverlay"
    for name in ("config", "data", "data/sounds", "data/templates", "trigger-packs", "diagnostics"):
        assert (app_root() / name).is_dir()
    assert template_path_for("Klog the Bold").name == "klog-the-bold.json"


def test_region_validation_and_helpers():
    assert Region(0, 0, 80, 60).valid() and not Region(0, 0, 79, 60).valid()
    assert Region.from_dict({"left": "1", "top": 2, "width": 100, "height": 100}) == Region(1, 2, 100, 100)
    assert Region.from_dict({"left": 1}) is None and Region.from_dict("x") is None
    assert Region(10, 10, 100, 100).contains(50, 50) and not Region(10, 10, 100, 100).contains(5, 50)
    assert Region(1, 2, 3, 4).as_mss() == {"left": 1, "top": 2, "width": 3, "height": 4}


def test_performance_profiles_and_comparison():
    assert recommend_profile(200)[:2] == ("Ultra", 0.20)
    assert recommend_profile(350)[:2] == ("Fast", 0.30)
    assert recommend_profile(550)[:2] == ("Balanced", 0.50)
    assert recommend_profile(850)[:2] == ("Limited", 0.75)
    assert recommend_profile(1500)[:2] == ("Low", 1.20)
    assert recommend_profile(200)[2] == ""
    assert "miss" in recommend_profile(850)[2].casefold()
    frame = representative_combat_frame(652, 477)
    assert frame.shape == (477, 652, 3) and frame.max() > 200
    common = dict(gpu_names=[], unchanged_check_ms=10, recognized_lines=10, profile="Balanced", recommended_interval=0.5)
    gpu = CapabilityResult(provider="GPU", provider_detail="DmlExecutionProvider", ocr_ms=600, capture_ms=5, **common)
    cpu = CapabilityResult(provider="CPU", provider_detail="CPUExecutionProvider", ocr_ms=450, capture_ms=6, **common)
    assert faster_result(gpu, cpu) is cpu and faster_result(cpu, gpu) is cpu
    assert round(cpu.full_scan_fps, 2) == round(1000 / 456, 2)


def test_trigger_pack_round_trip_rekeys_conflicts_and_reports_invalid_items():
    raid = Trigger(id="same-id", name="Curse", folder="Bosses", profile="Raid", conditions=[TriggerCondition("curse")],
                   overlay_enabled=True, timer_seconds=20, timer_key_template="{target}")
    solo = Trigger(name="Solo", profile="Solo", conditions=[TriggerCondition("hit")])
    payload = build_trigger_pack("Raid", [raid, solo])
    assert payload["format"] == PACK_FORMAT
    imported, skipped = parse_trigger_pack(payload)
    assert not skipped and len(imported) == 1
    assert (imported[0].folder, imported[0].timer_seconds, imported[0].timer_key_template) == ("Bosses", 20, "{target}")

    imported, skipped = parse_trigger_pack({"triggers": [payload["triggers"][0], {"name": "Broken", "conditions": []}, "x"]},
                                           {"same-id"})
    assert len(imported) == 1 and imported[0].id != "same-id" and len(skipped) == 2
    try:
        parse_trigger_pack({"triggers": "nope"})
    except ValueError:
        pass
    else:  # pragma: no cover
        raise AssertionError("expected ValueError")
