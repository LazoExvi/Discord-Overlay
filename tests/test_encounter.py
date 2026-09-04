import csv
from datetime import datetime

from discord_overlay.encounter import COMBATANT_COLUMNS, LOG_COLUMNS, EncounterTracker
from discord_overlay.models import CombatEvent, EventKind


def _event(actor, amount, kind=EventKind.DAMAGE_OTHER, target="scarred zealot", timestamp=10.0, **extra):
    return CombatEvent(timestamp=timestamp, wall_time=datetime.now(), kind=kind, actor=actor,
                       target=target, amount=amount, **extra)


def _heal(actor, amount, target="Raan", timestamp=10.0):
    return _event(actor, amount, EventKind.HEAL, target, timestamp)


def rows(tracker, **kw):
    return [row.as_tuple() for row in tracker.actor_totals(**kw)]


def test_actor_breakdown_merges_ocr_case_variants():
    tracker = EncounterTracker()
    tracker.add(_event("klog", 20))
    tracker.add(_event("Klog", 30))
    assert rows(tracker, now=10.5) == [("Klog", "OTHER", 50, 100.0, 50.0, 50.0, 2, 0, 0, 0.0)]


def test_completed_encounter_values_remain_through_idle_time():
    tracker = EncounterTracker(timeout=8.0)
    tracker.add(_event("Klog", 100, EventKind.DAMAGE_OUT, timestamp=10.0))
    tracker.add(_event("Klog", 50, EventKind.DAMAGE_OUT, timestamp=12.0))
    completed = tracker.snapshot(now=25.0)
    much_later = tracker.snapshot(now=500.0)
    assert not completed.active
    assert completed.total_out == much_later.total_out == 150
    assert completed.duration == much_later.duration == 2.0
    assert completed.dps == much_later.dps == 75.0


def test_new_encounter_replaces_completed_values_and_reset_clears_them():
    tracker = EncounterTracker(timeout=8.0)
    tracker.add(_event("Klog", 100, EventKind.DAMAGE_OUT, timestamp=10.0))
    tracker.snapshot(now=20.0)
    tracker.add(_event("Klog", 40, EventKind.DAMAGE_OUT, timestamp=30.0))
    assert tracker.snapshot(now=30.5).total_out == 40
    assert len(tracker.history) == 1
    tracker.reset()
    cleared = tracker.snapshot(now=31.0)
    assert (cleared.total_out, cleared.duration, cleared.dps) == (0, 0.0, 0.0)


def test_dps_does_not_decay_during_timeout_grace_period():
    tracker = EncounterTracker(timeout=8.0)
    tracker.add(_event("Klog", 100, EventKind.DAMAGE_OUT, timestamp=10.0))
    tracker.add(_event("Klog", 50, EventKind.DAMAGE_OUT, timestamp=12.0))
    immediately, during, completed = (tracker.snapshot(now=t) for t in (12.1, 19.9, 20.1))
    assert immediately.active and during.active and not completed.active
    assert immediately.duration == during.duration == completed.duration == 2.0
    assert immediately.dps == during.dps == completed.dps == 75.0


def test_next_damage_advances_frozen_encounter_clock():
    tracker = EncounterTracker(timeout=8.0)
    tracker.add(_event("Klog", 100, EventKind.DAMAGE_OUT, timestamp=10.0))
    assert tracker.snapshot(now=14.0).duration == 0.0
    tracker.add(_event("Klog", 100, EventKind.DAMAGE_OUT, timestamp=15.0))
    snapshot = tracker.snapshot(now=16.0)
    assert (snapshot.duration, snapshot.dps) == (5.0, 40.0)


def test_pet_damage_combined_or_separate():
    combined = EncounterTracker(player_name="Raan")
    combined.add(_event("Pet", 216, EventKind.DAMAGE_OUT, is_pet=True))
    snapshot = combined.snapshot(now=10.5)
    assert (snapshot.total_out, snapshot.hits) == (216, 1)
    assert combined.actor_totals()[0].actor == "Raan"

    separate = EncounterTracker(player_name="Raan", combine_pet_damage=False)
    separate.add(_event("Raan", 100, EventKind.DAMAGE_OUT))
    separate.add(_event("Pet", 216, EventKind.DAMAGE_OUT, is_pet=True))
    assert separate.snapshot(now=10.5).total_out == 100
    assert {row.actor for row in separate.actor_totals()} == {"Raan", "Pet"}


def test_damage_shields_toggle_between_wearer_and_separate_entity():
    def shield(actor, amount, kind=EventKind.DAMAGE_OUT):
        return _event(actor, amount, kind, is_damage_shield=True)

    by_wearer = EncounterTracker(player_name="Raan", damage_shields_by_wearer=True)
    by_wearer.add(shield("Raan", 38))
    assert by_wearer.actor_totals()[0].actor == "Raan"

    default = EncounterTracker(player_name="Raan")
    default.add(shield("Raan", 38))
    default.add(shield("Pitborn", 22, EventKind.DAMAGE_OTHER))
    assert rows(default, now=10.5) == [("Damage Shield", "DAMAGE SHIELD", 60, 100.0, 60.0, 60.0, 2, 0, 0, 0.0)]


def test_heal_only_actor_has_healing_and_hps_breakdown():
    tracker = EncounterTracker(player_name="Raan")
    tracker.add(_heal("Raan", 80))
    assert rows(tracker, now=10.5) == [("Raan", "PLAYER", 0, 0.0, 0.0, 0.0, 0, 0, 80, 80.0)]


def test_actor_totals_can_be_scoped_to_one_target():
    tracker = EncounterTracker()
    tracker.add(_event("Raan", 100, target="a werewolf", timestamp=10.0))
    tracker.add(_event("Klog", 300, target="A Werewolf", timestamp=12.0))
    tracker.add(_event("Raan", 900, target="a caiman", timestamp=15.0))
    scoped = tracker.actor_totals(now=15.5, target="a werewolf")
    assert [row.actor for row in scoped] == ["Klog", "Raan"]
    assert scoped[0].as_tuple()[2:6] == (300, 75.0, 150.0, 150.0)
    assert scoped[1].as_tuple()[2:6] == (100, 25.0, 50.0, 50.0)


def test_target_scope_ranks_healers_and_lists_case_variants_once():
    tracker = EncounterTracker()
    for actor, amount, target in (("Raan", 80, "Den Mother"), ("Klog", 140, "den mother"), ("Raan", 500, "Ssssteve")):
        tracker.add(_heal(actor, amount, target))
    scoped = tracker.actor_totals(now=10.5, target="Den Mother")
    assert tracker.encounter_targets() == ["Den Mother", "Ssssteve"]
    assert [(row.actor, row.healing) for row in scoped] == [("Klog", 140), ("Raan", 80)]


def test_pet_critical_appears_in_breakdown_when_pet_is_separate():
    tracker = EncounterTracker(player_name="Raan", combine_pet_damage=False)
    tracker.add(_event("Ssssteve", 100, EventKind.DAMAGE_OUT, is_pet=True, critical=True))
    row = tracker.actor_totals(now=10.5)[0]
    assert tracker.snapshot(now=10.5).crits == 1
    assert (row.actor, row.crits) == ("Ssssteve", 1)


def test_csv_exports_combatants_and_log_and_preserves_pet_source(tmp_path):
    tracker = EncounterTracker(player_name="Raan", combine_pet_damage=True)
    tracker.add(_event("Pet", 216, EventKind.DAMAGE_OUT, is_pet=True))
    tracker.export_csv(tmp_path / "combatants.csv", "combatants")
    tracker.export_csv(tmp_path / "log.csv", "log")
    with (tmp_path / "combatants.csv").open(encoding="utf-8-sig", newline="") as handle:
        combatants = list(csv.reader(handle))
    with (tmp_path / "log.csv").open(encoding="utf-8-sig", newline="") as handle:
        events = list(csv.reader(handle))
    assert combatants[0] == list(COMBATANT_COLUMNS)
    assert (combatants[1][0], combatants[1][2]) == ("Raan", "216")
    assert events[0] == list(LOG_COLUMNS)
    assert (events[1][2], events[1][3]) == ("Raan", "Pet")


def test_unknown_export_type_is_rejected(tmp_path):
    import pytest

    with pytest.raises(ValueError):
        EncounterTracker().export_csv(tmp_path / "x.csv", "xlsx")


def test_incoming_combines_damage_to_player_and_pet_and_ranks_enemies():
    tracker = EncounterTracker(player_name="Raan")
    tracker.add(_event("a skeletal cleric", 100, EventKind.DAMAGE_IN, target="Raan"))
    tracker.add(_event("a caiman", 300, EventKind.DAMAGE_IN, target="Pet"))
    assert tracker.snapshot(now=10.5).total_in == 400
    assert [(r.actor, r.actor_type, r.damage, r.share) for r in tracker.actor_totals(now=10.5)] == [
        ("a caiman", "ENEMY", 300, 75.0), ("a skeletal cleric", "ENEMY", 100, 25.0)]


def test_incoming_and_outgoing_shares_use_separate_direction_totals():
    tracker = EncounterTracker(player_name="Raan")
    tracker.add(_event("Raan", 200, EventKind.DAMAGE_OUT))
    tracker.add(_event("a caiman", 50, EventKind.DAMAGE_IN, target="Raan"))
    assert [(r.actor, r.share) for r in tracker.actor_totals(now=10.5)] == [("Raan", 100.0), ("a caiman", 100.0)]


def test_you_target_scope_includes_every_attacker_and_healer_targeting_player():
    tracker = EncounterTracker(player_name="Raan")
    tracker.add(_event("a crocodile", 100, EventKind.DAMAGE_IN, target="Raan", timestamp=10.0))
    tracker.add(_event("a caiman", 300, EventKind.DAMAGE_IN, target="Raan", timestamp=12.0))
    tracker.add(_heal("Klog", 200, target="You", timestamp=11.0))
    tracker.add(_event("a basilisk", 900, EventKind.DAMAGE_IN, target="Pet"))
    scoped = tracker.actor_totals(now=12.5, target="You")
    assert tracker.encounter_targets() == ["Pet", "You"]
    assert [(r.actor, r.damage, r.healing) for r in scoped] == [("a caiman", 300, 0), ("a crocodile", 100, 0), ("Klog", 0, 200)]


def test_all_targets_is_catch_all_for_every_damage_and_healing_actor():
    tracker = EncounterTracker(player_name="Raan")
    tracker.add(_event("Raan", 200, EventKind.DAMAGE_OUT))
    tracker.add(_event("Klog", 300))
    tracker.add(_event("a werewolf", 400, EventKind.DAMAGE_IN, target="Raan"))
    tracker.add(_heal("Den Mother", 500))
    assert {(r.actor, r.damage, r.healing) for r in tracker.actor_totals(now=10.5)} == {
        ("Raan", 200, 0), ("Klog", 300, 0), ("a werewolf", 400, 0), ("Den Mother", 0, 500)}


def test_fixed_timeline_combat_math_audit():
    tracker = EncounterTracker(player_name="Raan", rolling_window=10.0, combine_pet_damage=True)
    events = [
        _event("Raan", 100, EventKind.DAMAGE_OUT, timestamp=100.0),
        _event("Ssssteve", 50, EventKind.DAMAGE_OUT, timestamp=104.0, is_pet=True, critical=True),
        _event("a large rat", 80, EventKind.DAMAGE_IN, target="Raan", timestamp=106.0),
        _heal("Raan", 300, timestamp=110.0),
        _event("Raan", 200, EventKind.DAMAGE_OUT, timestamp=112.0),
    ]
    for event in events:
        tracker.add(event)
    snapshot = tracker.snapshot(now=112.0)
    assert (snapshot.duration, snapshot.total_out, snapshot.total_in, snapshot.total_heal) == (12.0, 350, 80, 300)
    assert snapshot.dps == 350 / 12
    assert snapshot.rolling_dps == 250 / 10
    assert snapshot.hps == 300 / 10
    assert (snapshot.hits, snapshot.crits) == (3, 1)


def test_healing_extends_activity_and_uses_its_own_hps_clock():
    tracker = EncounterTracker(timeout=8.0, player_name="Raan")
    tracker.add(_event("Raan", 100, EventKind.DAMAGE_OUT, timestamp=10.0))
    tracker.add(_heal("Raan", 120, timestamp=16.0))
    snapshot = tracker.snapshot(now=20.0)
    assert snapshot.active
    assert (snapshot.duration, snapshot.dps, snapshot.hps) == (0.0, 100.0, 20.0)


def test_same_name_enemy_and_pet_are_separate_rows():
    tracker = EncounterTracker(player_name="Raan", combine_pet_damage=False)
    tracker.add(_event("a cursed plague rat", 90, EventKind.DAMAGE_IN, target="Raan"))
    tracker.add(_event("a cursed plague rat", 40, EventKind.DAMAGE_OUT, is_pet=True))
    assert {(r.actor, r.actor_type, r.damage, r.share) for r in tracker.actor_totals(now=10.5)} == {
        ("a cursed plague rat", "ENEMY", 90, 100.0), ("a cursed plague rat", "PET", 40, 100.0)}


def test_running_totals_combine_fights_without_counting_idle_time():
    tracker = EncounterTracker(timeout=5.0, player_name="Raan", keep_running_totals=True)
    tracker.add(_event("Raan", 100, EventKind.DAMAGE_OUT, timestamp=10.0))
    tracker.add(_heal("Raan", 60, timestamp=11.0))
    tracker.add(_event("Raan", 50, EventKind.DAMAGE_OUT, timestamp=12.0))
    tracker.update(now=20.0)
    tracker.add(_event("Raan", 200, EventKind.DAMAGE_OUT, timestamp=30.0))
    tracker.add(_heal("Raan", 120, timestamp=33.0))
    tracker.add(_event("Raan", 100, EventKind.DAMAGE_OUT, timestamp=34.0))
    snapshot = tracker.snapshot(now=34.0)
    assert (snapshot.total_out, snapshot.total_heal, snapshot.duration) == (450, 180, 6.0)
    assert (snapshot.dps, snapshot.hps, snapshot.rolling_dps) == (75.0, 45.0, 75.0)

    tracker.reset()
    cleared = tracker.snapshot(now=40.0)
    assert (cleared.total_out, cleared.duration, cleared.dps) == (0, 0.0, 0.0)
