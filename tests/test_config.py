import json

import pytest

from discord_overlay.config import SCHEMA_VERSION, CharacterProfile, Settings, TimerBoard
from discord_overlay.models import Region
from discord_overlay.paths import settings_path
from discord_overlay.triggers import Trigger, TriggerCondition


def test_fresh_settings_have_a_placeholder_character(app_data):
    settings = Settings()
    assert settings.character_names() == ["Default"]
    assert settings.player_name == "You"
    settings.save()
    loaded = Settings.load()
    assert loaded.player_name == "You" and loaded.schema_version == SCHEMA_VERSION
    assert settings_path().is_file()


def test_missing_and_corrupt_files_fall_back_to_defaults(app_data):
    assert Settings.load().scan_interval == 0.22
    settings_path().parent.mkdir(parents=True)
    settings_path().write_text("{not json", encoding="utf-8")
    assert Settings.load().scan_interval == 0.22
    settings_path().write_text("[]", encoding="utf-8")
    assert Settings.load().scan_interval == 0.22


def test_full_round_trip(app_data):
    settings = Settings(
        keep_running_totals=True, setup_completed=True, performance_profile="Fast",
        benchmark_ocr_ms=245.5, benchmark_capture_ms=4.2, benchmark_provider="CUDAExecutionProvider",
        actor_filter_enabled=True, allowed_actor_names=["Klog", "Aernulo"],
        timer_layout="independent", timer_visual_size="compact",
        overlay_close_enabled=True, overlay_close_modifier1="alt", overlay_close_modifier2="control",
        timer_boards=[TimerBoard(name="Raid Timers", geometry="520x300+50+60", positioned=True, columns=3,
                                 visual_size="compact", opacity=0.8, sort_order="remaining",
                                 growth_direction="columns")],
        speech_voice="Test Voice", speech_rate=2, speech_volume=75, speech_queue_mode="interrupt",
        active_trigger_profile="Raid", region=Region(100, 120, 800, 260),
        region_history=[Region(10, 20, 640, 180), Region(100, 120, 800, 260)],
        events_column_order=["type", "time"],
        triggers=[Trigger(
            name="Raid warning", folder="Bosses", profile="Raid", logic="any",
            conditions=[TriggerCondition("begins casting"), TriggerCondition("fizzles", negate=True)],
            use_combat_region=False, region=Region(10, 20, 640, 180), sound="builtin:Warning", volume=0.65,
            overlay_enabled=True, overlay_text="{spell} on {target}", timer_board="Raid Timers",
            overlay_layout="independent", overlay_size="compact", overlay_opacity=0.72,
            overlay_geometry="250x80+900+300", overlay_positions={"Raan": "250x80+300+400"},
            timer_seconds=24, timer_key_template="{target}", retrigger_mode="replace",
            ending_sound="builtin:Chime", expiration_sound="builtin:Pulse", start_speech="{spell} landed",
            ending_speech="{spell} ending", expiration_speech="{spell} expired",
            end_pattern=r"(?P<target>\w+) has worn off", end_mode="regex",
        )],
    )
    settings.save()
    loaded = Settings.load()

    assert loaded.keep_running_totals and loaded.setup_completed
    assert (loaded.performance_profile, loaded.benchmark_ocr_ms, loaded.benchmark_provider) == (
        "Fast", 245.5, "CUDAExecutionProvider")
    assert loaded.allowed_actor_names == ["Klog", "Aernulo"] and loaded.actor_filter_enabled
    assert (loaded.timer_layout, loaded.timer_visual_size) == ("independent", "compact")
    assert (loaded.overlay_close_modifier1, loaded.overlay_close_modifier2) == ("alt", "control")
    board = loaded.timer_boards[0]
    assert (board.name, board.columns, board.visual_size, board.opacity, board.sort_order, board.growth_direction) == (
        "Raid Timers", 3, "compact", 0.8, "remaining", "columns")
    assert (loaded.speech_voice, loaded.speech_rate, loaded.speech_volume, loaded.speech_queue_mode) == (
        "Test Voice", 2, 75, "interrupt")
    assert loaded.active_trigger_profile == "Raid"
    assert loaded.region == Region(100, 120, 800, 260)
    assert loaded.region_history == [Region(10, 20, 640, 180), Region(100, 120, 800, 260)]
    assert loaded.events_column_order == ["type", "time"]
    trigger = loaded.triggers[0]
    assert (trigger.name, trigger.folder, trigger.profile, trigger.logic) == ("Raid warning", "Bosses", "Raid", "any")
    assert trigger.region == Region(10, 20, 640, 180) and trigger.conditions[1].negate
    assert (trigger.volume, trigger.overlay_opacity, trigger.timer_seconds) == (0.65, 0.72, 24)
    assert trigger.overlay_positions == {"Raan": "250x80+300+400"}
    assert (trigger.ending_sound, trigger.expiration_sound, trigger.end_mode) == ("builtin:Chime", "builtin:Pulse", "regex")


def test_recent_regions_are_deduplicated_and_bounded():
    settings = Settings()
    regions = [Region(index * 10, index * 10, 640, 180) for index in range(10)]
    for region in regions:
        settings.remember_region(region)
    settings.remember_region(regions[5])
    settings.remember_region(Region(0, 0, 10, 10))  # too small, ignored
    assert len(settings.region_history) == 8
    assert settings.region_history[0] == regions[5]
    assert settings.region_history.count(regions[5]) == 1


def test_invalid_values_are_sanitized(app_data):
    settings_path().parent.mkdir(parents=True)
    settings_path().write_text(json.dumps({
        "scan_interval": 99, "timer_layout": "sideways", "timer_visual_size": "huge",
        "overlay_close_modifier1": "shift", "overlay_close_modifier2": "shift",
        "speech_queue_mode": "loud", "timer_boards": [],
        "triggers": [{"name": "T", "timer_board": "Ghost board", "conditions": [{"pattern": "x"}]}],
        "region": {"left": 0, "top": 0, "width": 5, "height": 5},
    }), encoding="utf-8")
    loaded = Settings.load()
    assert loaded.scan_interval == 5.0
    assert (loaded.timer_layout, loaded.timer_visual_size) == ("docked", "standard")
    assert (loaded.overlay_close_modifier1, loaded.overlay_close_modifier2) == ("shift", "none")
    assert loaded.speech_queue_mode == "queue"
    assert loaded.timer_boards[0].name == "Default"
    assert loaded.triggers[0].timer_board == "Default"
    assert loaded.region is None


def test_character_profiles_switch_and_persist(app_data):
    settings = Settings(active_character="Klog", region=Region(10, 20, 640, 180),
                        timer_boards=[TimerBoard(name="Klog board", columns=3)], active_trigger_profile="Melee")
    settings.save()
    assert settings.character_names() == ["Klog"] and settings.player_name == "Klog"

    settings.add_character("Aernulo", copy_current=False)
    assert settings.switch_character("Aernulo")
    assert settings.player_name == "Aernulo" and settings.region is None
    assert settings.timer_boards[0].name == "Default"
    settings.region = Region(5, 6, 300, 100)
    settings.timer_boards = [TimerBoard(name="Healer board", columns=2)]
    settings.save()

    loaded = Settings.load()
    assert (loaded.active_character, loaded.player_name) == ("Aernulo", "Aernulo")
    assert loaded.timer_boards[0].name == "Healer board"
    assert loaded.switch_character("Klog")
    assert loaded.player_name == "Klog" and loaded.region == Region(10, 20, 640, 180)
    assert loaded.timer_boards[0].columns == 3 and loaded.active_trigger_profile == "Melee"
    assert loaded.scan_interval == settings.scan_interval  # shared settings stay shared
    assert not loaded.switch_character("Nobody")


def test_character_rename_and_delete():
    settings = Settings(active_character="Klog")
    settings.add_character("Alt")
    settings.rename_character("Klog", "Main")
    assert (settings.active_character, settings.player_name) == ("Main", "Main")
    with pytest.raises(ValueError):
        settings.add_character("main")
    with pytest.raises(ValueError):
        settings.add_character("   ")
    settings.switch_character("Alt")
    assert settings.player_name == "Alt"
    settings.delete_character("Alt")
    assert (settings.active_character, settings.player_name) == ("Main", "Main")
    with pytest.raises(ValueError):
        settings.delete_character("Main")
    with pytest.raises(ValueError):
        settings.rename_character("Main", "")
    settings.rename_character("Main", "default")
    assert settings.player_name == "You"


def test_missing_active_character_falls_back_to_first(app_data):
    settings = Settings(characters=[CharacterProfile("Solo", {})], active_character="Ghost")
    assert settings.active_character == "Solo"
    settings.save()
    assert Settings.load().active_character == "Solo"


def test_parsesight_settings_are_imported_once(app_data):
    legacy = app_data / "ParseSight" / "config" / "settings.json"
    legacy.parent.mkdir(parents=True)
    legacy.write_text(json.dumps({
        "schema_version": 17, "player_name": "Klog", "active_character": "Klog", "scan_interval": 0.3,
        "audio_triggers": [{"name": "Imported", "conditions": [{"pattern": "hit"}]}],
        "characters": [{"name": "Klog", "data": {
            "region": {"left": 1, "top": 2, "width": 400, "height": 300},
            "overlay_geometry": "ignored", "timer_layout": "independent",
            "timer_boards": [{"name": "Raid", "columns": 2}],
        }}],
        "update_last_check": 123, "include_group_damage": True,
    }), encoding="utf-8")

    loaded = Settings.load()

    assert (loaded.player_name, loaded.scan_interval) == ("Klog", 0.3)
    assert loaded.triggers[0].name == "Imported"
    assert loaded.region == Region(1, 2, 400, 300)
    assert loaded.timer_layout == "independent" and loaded.timer_boards[0].name == "Raid"
    assert loaded.triggers[0].timer_board == "Raid"
    assert settings_path().is_file()
    assert "update_last_check" not in json.loads(settings_path().read_text(encoding="utf-8"))


def test_legacy_player_name_seeds_the_first_character(app_data):
    settings_path().parent.mkdir(parents=True)
    settings_path().write_text(json.dumps({"player_name": "Raan"}), encoding="utf-8")
    loaded = Settings.load()
    assert loaded.character_names() == ["Raan"] and loaded.player_name == "Raan"


def test_trigger_and_board_helpers():
    settings = Settings(triggers=[Trigger(id="a", name="A", profile="Raid", conditions=[TriggerCondition("x")]),
                                  Trigger(id="b", name="B", profile="Solo", conditions=[TriggerCondition("y")])])
    assert settings.trigger_profiles() == ["Default", "Raid", "Solo"]
    assert [t.id for t in settings.triggers_in_profile("raid")] == ["a"]
    assert settings.trigger_by_id("b").name == "B" and settings.trigger_by_id("zzz") is None
    settings.upsert_trigger(Trigger(id="a", name="A2", conditions=[TriggerCondition("x")]))
    assert settings.trigger_by_id("a").name == "A2" and len(settings.triggers) == 2
    settings.remove_trigger("a")
    assert [t.id for t in settings.triggers] == ["b"]
    board = settings.ensure_board("Buffs")
    assert settings.ensure_board("buffs") is board
    assert settings.timer_board("BUFFS") is board and settings.timer_board("nope") is settings.timer_boards[0]
    assert settings.board_names() == ["Default", "Buffs"]
