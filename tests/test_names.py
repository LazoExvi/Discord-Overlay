from discord_overlay.encounter import EncounterTracker
from discord_overlay.models import CombatEvent, EventKind
from discord_overlay.names import known_npc, known_npcs, merge_similar_names, snap_to_known_npc
from datetime import datetime


def _event(actor, amount, kind=EventKind.DAMAGE_OTHER, target="scarred zealot"):
    return CombatEvent(timestamp=10.0, wall_time=datetime.now(), kind=kind, actor=actor, target=target, amount=amount)


def test_shipped_npc_list_loads_and_ignores_articles():
    assert len(known_npcs()) > 1000
    assert known_npc("Bone Construct") == "Bone Construct"
    assert known_npc("a bone construct") == "Bone Construct"
    assert known_npc("Playername") is None


def test_misread_of_a_known_npc_snaps_even_when_never_read_correctly():
    assert snap_to_known_npc("bone construet") == "bone construct"
    assert snap_to_known_npc("bone construct") == "bone construct"
    assert snap_to_known_npc("xyzzy") is None
    merged = merge_similar_names(["bone construet", "playername", "playername"])
    assert merged["bone construet"] == "bone construct"
    assert merged["playername"] == "playername"


def test_tracker_shows_the_shipped_spelling_for_a_snapped_name():
    tracker = EncounterTracker(player_name="Playername")
    tracker.add(_event("Bone Construet", 40))
    tracker.add(_event("Playername", 10, EventKind.DAMAGE_OUT))
    assert {r.actor for r in tracker.actor_totals(now=10.5)} == {"Bone Construct", "Playername"}


def test_frequent_spellings_and_player_names_are_not_snapped_to_npcs():
    # A spelling read many times is trusted as-is; only rare readings snap.
    merged = merge_similar_names(["bone construet"] * 10)
    assert merged["bone construet"] == "bone construet"
    # A player whose name is one letter from an NPC keeps their name.
    merged = merge_similar_names(["bone construet"], protected=["bone construet"])
    assert merged["bone construet"] == "bone construet"
