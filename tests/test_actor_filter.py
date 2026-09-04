from datetime import datetime

from discord_overlay.actor_filter import actor_event_allowed, normalize_actor_name
from discord_overlay.models import CombatEvent, EventKind


def _event(kind, actor, target="scarred zealot", *, is_pet=False):
    return CombatEvent(timestamp=10.0, wall_time=datetime.now(), kind=kind, actor=actor,
                       target=target, amount=100, is_pet=is_pet)


def test_names_match_case_and_punctuation_but_not_partial_names():
    assert normalize_actor_name(" K'Log ") == "klog"
    assert normalize_actor_name("a Crocodile") == "crocodile"
    assert normalize_actor_name("Klogger") != normalize_actor_name("Klog")


def test_disabled_filter_keeps_everything():
    assert actor_event_allowed(_event(EventKind.DAMAGE_OTHER, "Nearbyplayer"), "Raan", False, [])


def test_enabled_filter_keeps_personal_and_listed_activity():
    assert actor_event_allowed(_event(EventKind.DAMAGE_OUT, "Raan"), "Raan", True, [])
    assert actor_event_allowed(_event(EventKind.DAMAGE_OUT, "Ssssteve", is_pet=True), "Raan", True, [])
    assert actor_event_allowed(_event(EventKind.DAMAGE_IN, "skeletal cleric", "Raan"), "Raan", True, [])
    assert actor_event_allowed(_event(EventKind.DAMAGE_OTHER, "KLOG"), "Raan", True, ["Klog"])
    assert not actor_event_allowed(_event(EventKind.DAMAGE_OTHER, "Nearbyplayer"), "Raan", True, ["Klog"])


def test_misses_at_player_or_pet_are_retained():
    assert actor_event_allowed(_event(EventKind.MISS, "skeletal cleric", "Raan"), "Raan", True, [])
    assert actor_event_allowed(_event(EventKind.MISS, "skeletal cleric", "Pet"), "Raan", True, [])


def test_both_sides_of_group_fights_are_kept_and_strangers_dropped():
    names = ["Snubert", "Matchacakes"]
    assert actor_event_allowed(_event(EventKind.DAMAGE_OTHER, "rotting skeleton", "Snubert"), "Training", True, names)
    assert actor_event_allowed(_event(EventKind.DAMAGE_OTHER, "Snubert", "rotting skeleton"), "Training", True, names)
    assert not actor_event_allowed(_event(EventKind.DAMAGE_OTHER, "Willmont", "spiderling"), "Training", True, names)
    assert not actor_event_allowed(_event(EventKind.DAMAGE_OTHER, "spiderling", "Willmont"), "Training", True, names)
