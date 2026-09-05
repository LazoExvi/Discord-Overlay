from discord_overlay.models import EventKind
from discord_overlay.parser import CombatTextParser, closest_combat_verb, parse_amount, repair_ocr_spacing


def parse(text, name="Raan", confidence=0.95):
    return CombatTextParser(name).parse(text, confidence, 10.0)


def test_melee_outgoing():
    event = parse("You crush a comely courtesan for 81 points of damage.")
    assert (event.kind, event.actor, event.target, event.amount) == (
        EventKind.DAMAGE_OUT, "Raan", "comely courtesan", 81)


def test_ability_critical():
    event = parse("Your Feint IV hits a comely courtesan for 123 points of damage. (Critical)")
    assert (event.kind, event.action, event.amount, event.critical) == (EventKind.DAMAGE_OUT, "Feint IV", 123, True)


def test_incoming_absorbed():
    event = parse("a comely courtesan crushes YOU for 382 points of damage (43 absorbed). (Critical)")
    assert (event.kind, event.actor, event.target, event.amount, event.absorbed, event.critical) == (
        EventKind.DAMAGE_IN, "comely courtesan", "Raan", 382, 43, True)


def test_damage_to_your_pet_counts_as_incoming():
    event = parse("a grave magus hits your pet for 143 points of Shadow Damage.")
    assert (event.kind, event.actor, event.target, event.amount) == (EventKind.DAMAGE_IN, "grave magus", "Pet", 143)
    glued = parse("a grave magus hits yourpet for 81 points of damage.")
    assert (glued.kind, glued.target) == (EventKind.DAMAGE_IN, "Pet")


def test_heal():
    event = parse("Crit's Second Wind heals you for 63 Health.")
    assert (event.kind, event.actor, event.target, event.amount) == (EventKind.HEAL, "Crit", "Raan", 63)


def test_ocr_number_corrections():
    assert parse("You hit a rat for I8O points of damage.", "You").amount == 180
    assert parse_amount("1,234") == 1234
    assert parse_amount("5O5") == 505
    assert parse_amount(None) == 0


def test_offhand_target_is_clean():
    event = parse("You slash a comely courtesan with your offhand for 64 points of damage.")
    assert (event.target, event.action) == ("comely courtesan", "Slash (Offhand)")


def test_incoming_miss():
    event = parse("a comely courtesan tries to crush YOU, but misses!")
    assert (event.kind, event.actor, event.target) == (EventKind.MISS, "comely courtesan", "Raan")


def test_group_ability_is_other_actor():
    event = parse("Pitborn's Greater Smite hits a grave magus for 516 points of damage.")
    assert (event.kind, event.actor, event.action, event.target) == (
        EventKind.DAMAGE_OTHER, "Pitborn", "Greater Smite", "grave magus")


def test_configured_player_name_is_an_alias_for_you():
    event = parse("Raan's Ice Blast hits a grave magus for 516 points of Cold Damage.")
    assert (event.kind, event.actor, event.action, event.target) == (
        EventKind.DAMAGE_OUT, "Raan", "Ice Blast", "grave magus")


def test_your_pet_spell_and_melee():
    spell = parse("Your pet's Fire Blast hits a grave magus for 216 points of Fire Damage.")
    assert (spell.kind, spell.actor, spell.action, spell.target, spell.amount, spell.is_pet) == (
        EventKind.DAMAGE_OUT, "Pet", "Fire Blast", "grave magus", 216, True)
    assert not spell.is_damage_shield
    melee = parse("Your pet punches a scarred zealot for 47 points of damage.")
    assert (melee.kind, melee.actor, melee.action, melee.is_pet) == (EventKind.DAMAGE_OUT, "Pet", "Punches", True)


def test_named_pet_melee_spell_and_offhand():
    melee = parse("Your pet Aernulo pierces a skeletal cleric for 11 points of damage.")
    assert (melee.actor, melee.action, melee.target, melee.amount, melee.is_pet) == (
        "Aernulo", "Pierces", "skeletal cleric", 11, True)
    spell = parse("Your pet Aernulo's Staggering Winds hits a skeletal cleric for 15 points of Magic Damage.")
    assert (spell.actor, spell.action, spell.target, spell.amount, spell.is_pet) == (
        "Aernulo", "Staggering Winds", "skeletal cleric", 15, True)
    offhand = parse("Your pet Aernulo pierces a skeletal cleric with their offhand for 1 point of damage.")
    assert (offhand.actor, offhand.action, offhand.target, offhand.amount) == (
        "Aernulo", "Pierces (Offhand)", "skeletal cleric", 1)


def test_learned_pet_context_carries_to_later_lines():
    parser = CombatTextParser("Raan")
    parser.observe("Your pet Ssssteve pierces a skeletal cleric for 11 points of damage.")
    event = parser.parse("Ssssteve's Frenzy hits a skeletal cleric for 100 points of Slashing Damage.", 0.95, 10.0)
    assert (event.kind, event.actor, event.action, event.amount, event.is_pet) == (
        EventKind.DAMAGE_OUT, "Ssssteve", "Frenzy", 100, True)

    parser = CombatTextParser("Raan")
    parser.observe("a skeletal cleric looks angrily at Your pet Ssssteve.")
    melee = parser.parse("Ssssteve pierces a skeletal cleric for 7 points of damage.", 0.93, 10.0)
    assert (melee.kind, melee.actor, melee.is_pet) == (EventKind.DAMAGE_OUT, "Ssssteve", True)
    shield = parser.parse("Ssssteve's Damage Shield hits a skeletal cleric for 5 points of damage.", 0.92, 10.0)
    assert (shield.kind, shield.actor, shield.is_pet, shield.is_damage_shield) == (
        EventKind.DAMAGE_OUT, "Ssssteve", True, True)


def test_multiword_charmed_pet_name_is_learned():
    parser = CombatTextParser("Raan")
    first = parser.parse("Your pet a cursed plague rat bites a carrion beetle for 12 points of damage.", 0.95, 10.0)
    later = parser.parse("a cursed plague rat's Frenzy hits a carrion beetle for 40 points of damage.", 0.95, 11.0)
    assert (first.actor, first.is_pet) == ("a cursed plague rat", True)
    assert (later.actor, later.kind, later.is_pet) == ("cursed plague rat", EventKind.DAMAGE_OUT, True)

    parser = CombatTextParser("Raan")
    parser.observe("a carrion beetle looks angrily at Your pet a cursed plague rat.")
    event = parser.parse("a cursed plague rat bites a carrion beetle for 12 points of damage.", 0.95, 10.0)
    assert (event.kind, event.is_pet) == (EventKind.DAMAGE_OUT, True)


def test_damage_shield_attribution():
    mine = parse("Your Damage Shield hits a grave magus for 38 points of Fire Damage.")
    assert (mine.kind, mine.actor, mine.action, mine.is_damage_shield) == (
        EventKind.DAMAGE_OUT, "Raan", "Damage Shield", True)
    other = parse("Aernulo's Damage Shield hits a skeletal cleric for 5 points of damage.")
    assert (other.kind, other.actor, other.action, other.target, other.amount, other.is_damage_shield) == (
        EventKind.DAMAGE_OTHER, "Aernulo", "Damage Shield", "skeletal cleric", 5, True)
    passive = parse("a grave magus is scorched by YOUR damage shield for 38 points of Fire Damage.")
    assert (passive.kind, passive.actor, passive.target, passive.action, passive.amount) == (
        EventKind.DAMAGE_OUT, "Raan", "grave magus", "Damage Shield", 38)
    alternate = parse("a grave magus takes 38 Fire Damage from YOUR damage shield.")
    assert (alternate.kind, alternate.actor, alternate.target, alternate.amount, alternate.is_damage_shield) == (
        EventKind.DAMAGE_OUT, "Raan", "grave magus", 38, True)


def test_unknown_verbs_still_count():
    out = parse("Your Arcane Lance vaporizes a grave magus for 250 points of Arcane Damage.")
    assert (out.kind, out.amount) == (EventKind.DAMAGE_OUT, 250)
    incoming = parse("a grave magus eviscerates YOU for 99 points of damage.")
    assert (incoming.kind, incoming.target, incoming.amount) == (EventKind.DAMAGE_IN, "Raan", 99)


def test_generic_healing_wordings():
    restore = parse("A restorative aura restores you for 80 Health.")
    assert (restore.kind, restore.target, restore.amount) == (EventKind.HEAL, "Raan", 80)
    grants = parse("Second Wind grants you 80 Health.")
    assert (grants.kind, grants.target, grants.amount) == (EventKind.HEAL, "Raan", 80)


def test_possessive_names_ending_in_s():
    assert (lambda e: (e.actor, e.action))(parse("James' Fireball hits a grave magus for 200 points of damage.")) == (
        "James", "Fireball")
    assert parse("James' Second Wind heals you for 63 Health.").actor == "James"
    snubert = CombatTextParser("Snubert")
    event = snubert.parse("Matchacakes's Flameburst hits a rotting skeleton for 5 points of Fire Damage.")
    assert (event.actor, event.action, event.target, event.amount) == ("Matchacakes", "Flameburst", "rotting skeleton", 5)
    event = snubert.parse("Vekis's Round Kick hits a large rat for 8 points of damage.")
    assert (event.actor, event.action, event.target) == ("Vekis", "Round Kick", "large rat")
    event = snubert.parse("James'Fireball hits a grave magus for 200 points of damage.")
    assert (event.actor, event.action) == ("James", "Fireball")


def test_phantom_heals_prefix_is_collapsed_but_named_self_heal_is_kept():
    parser = CombatTextParser("Raan")
    for name in ("Evollate", "Evolhate"):
        event = parser.parse(f"heals {name} heals you for 63 Health.", 0.78, 10.0)
        assert (event.kind, event.actor, event.target) == (EventKind.HEAL, name, "Raan")
    event = parse("Evollate heals Evollate for 63 Health.")
    assert (event.actor, event.target) == ("Evollate", "Evollate")


def test_glued_and_fuzzy_ocr_repairs():
    event = parse("klogpunches a scarred zealot for 47 points of damage.", confidence=0.81)
    assert (event.actor, event.action, event.target) == ("klog", "Punches", "scarred zealot")
    event = parse("Youcrush a scarred zealot for 41 points of damage.", confidence=0.81)
    assert (event.kind, event.actor) == (EventKind.DAMAGE_OUT, "Raan")
    event = parse("Klog'sFireball hits a scarred zealot for 90 points of damage.", confidence=0.81)
    assert (event.actor, event.action) == ("Klog", "Fireball")
    event = parse("Klog curshs a cryptic weaver for 48 points of damage.", confidence=0.72)
    assert (event.actor, event.action, event.target) == ("Klog", "Crushes", "cryptic weaver")
    event = parse("Klog curshsa cryptic weaver for 48 points of damage.", confidence=0.68)
    assert (event.actor, event.action, event.target) == ("Klog", "Crushes", "cryptic weaver")
    event = parse("a cryptic weaver curshes YOU for 101 points of damage.", confidence=0.70)
    assert (event.kind, event.actor, event.target) == (EventKind.DAMAGE_IN, "cryptic weaver", "Raan")


def test_repair_helpers_are_conservative():
    assert repair_ocr_spacing("Youcrush a rat") == "You crush a rat"
    assert repair_ocr_spacing("Klog punches a rat") == "Klog punches a rat"
    assert closest_combat_verb("curshs") == "crushes"
    assert closest_combat_verb("zzz") is None
    assert closest_combat_verb("hits") == "hits"


def test_elemental_spell_damage_and_absorb():
    event = parse("Your iceblast hits a Plagueborn patrolman for 717 points of Cold Damage.", confidence=0.99)
    assert (event.kind, event.actor, event.action, event.target, event.amount) == (
        EventKind.DAMAGE_OUT, "Raan", "iceblast", "Plagueborn patrolman", 717)
    event = parse("a pyromancer burns YOU for 320 points of Fire Damage (20 absorbed). (Critical)")
    assert (event.kind, event.amount, event.absorbed, event.critical) == (EventKind.DAMAGE_IN, 320, 20, True)


def test_offhand_phrase_is_not_part_of_the_target():
    parser = CombatTextParser("Ebola")
    event = parser.parse("Ebola slashes a rotten sharpshooter with their offhand for 30 points of damage.")
    assert (event.target, event.action) == ("rotten sharpshooter", "Slashes (Offhand)")
    event = parser.parse("Raan bites a rotten sharpshooter with their offhand for 56 points of damage.")
    assert (event.actor, event.target) == ("Raan", "rotten sharpshooter")


def test_real_capture_lines_parse_with_expected_parties():
    parser = CombatTextParser("Snubert")
    cases = {
        "a rotting skeleton's Strike hits Snubert for 1 point of damage.": ("rotting skeleton", "Strike", "Snubert", 1),
        "a large rat claws Snubert for 3 points of damage.": ("large rat", "Claws", "Snubert", 3),
        "Player's Censuring Strike V hits a rotten sharpshooter for 88 points of damage.": (
            "Player", "Censuring Strike V", "rotten sharpshooter", 88),
        "Your Rend VI hits a rotten sharpshooter for 120 points of damage.": (
            "Snubert", "Rend VI", "rotten sharpshooter", 120),
    }
    for text, expected in cases.items():
        event = parser.parse(text)
        assert (event.actor, event.action, event.target, event.amount) == expected, text


def test_lines_missing_their_actor_are_credited_to_unknown():
    truncated = parse("hits a rat for 5 points of damage.")
    assert (truncated.actor, truncated.target, truncated.kind) == ("Unknown", "rat", EventKind.DAMAGE_OTHER)
    assert parse("5 points of damage.").actor == "Unknown"
    assert parse("a hits a rat for 5 points of damage.").actor == "Unknown"
    assert parse(". crushes YOU for 9 points of damage.").actor == "Unknown"
    assert parse("heals you for 20 Health.").actor == "Unknown"
    # Real names are untouched, including short ones.
    assert parse("Ax hits a rat for 5 points of damage.").actor == "Ax"


def test_backtick_apostrophes_and_players_pet_are_understood():
    event = parse("Ssssteve`s Frenzy hits a rat for 5 points of damage.")
    assert (event.actor, event.action) == ("Ssssteve", "Frenzy")
    event = parse("Raan`s pet hits a rat for 3 points of damage.")
    assert (event.kind, event.actor, event.is_pet) == (EventKind.DAMAGE_OUT, "Pet", True)
    event = parse("a rat bites Raan's pet for 3 points of damage.")
    assert (event.kind, event.target) == (EventKind.DAMAGE_IN, "Pet")


def test_configured_pet_names_and_learned_pet_announcements():
    parser = CombatTextParser("Raan", pet_names=["Xanartik"])
    event = parser.parse("Xanartik hits a rat for 10 points of damage.")
    assert (event.kind, event.is_pet) == (EventKind.DAMAGE_OUT, True)
    assert parser.pop_new_pets() == []  # configured names are not announced
    parser.parse("Ssssteve hits a rat for 10 points of damage.")
    parser.parse("Your pet Ssssteve bites a rat for 4 points of damage.")
    assert parser.pop_new_pets() == ["Ssssteve"]
    assert parser.pop_new_pets() == []


def test_environmental_damage_is_ignored_and_passive_self_damage_is_incoming():
    assert parse("You take 65 points of damage from falling.") is None
    assert parse("you take 65 damage from falling") is None
    assert parse("You take 12 points of damage from drowning!") is None
    assert parse("You suffer 30 fall damage.") is None
    trap = parse("You take 40 points of damage from a poison trap.")
    assert (trap.kind, trap.actor, trap.target, trap.amount) == (EventKind.DAMAGE_IN, "poison trap", "Raan", 40)
    unknown = parse("You take 9 points of damage.")
    assert (unknown.kind, unknown.actor, unknown.target) == (EventKind.DAMAGE_IN, "Unknown", "Raan")


def test_non_combat_lines_are_ignored():
    for text in ("Starting to attack.", "a spiderling loses interest in Quorion.", "Matchacakes begins casting Flameburst."):
        assert parse(text) is None
    assert parse("You hit a rat for 0 points of damage.") is None
