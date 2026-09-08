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
    # A single lowercase letter is a clipped name, not a combatant; two letters are kept
    # so the display-time merge can fold "om" into "Tom".
    assert parse("r slashes a Plagueborn myrmidon for 40 points of damage.").actor == "Unknown"
    assert parse("om's Greater Fireball hits a sandy broodling for 2030 points of Fire").actor == "om"


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


def test_misread_or_unknown_verbs_still_split_actor_from_target():
    assert closest_combat_verb("erushes") == "crushes"  # first letter misread
    assert closest_combat_verb("heals") is None
    event = parse("Bone Construct erushes YOU for 120 points of damage.")
    assert (event.actor, event.action, event.target, event.kind) == ("Bone Construct", "Crushes", "Raan", EventKind.DAMAGE_IN)
    event = parse("Bone Construct wallops YOU for 120 points of damage.")
    assert (event.actor, event.action, event.target, event.kind) == ("Bone Construct", "Wallops", "Raan", EventKind.DAMAGE_IN)
    event = parse("a rat nibbles a zealot for 3 points of damage.")
    assert (event.actor, event.action, event.target, event.kind) == ("rat", "Nibbles", "zealot", EventKind.DAMAGE_OTHER)


def test_apostrophe_misread_as_letter_still_credits_the_ability_owner():
    for text in ("Entrarils Slice VI hits Bone Construct for 72 points of Bleed Damage.",
                 "EntrariIs Stab VI hits Bone Construct for 374 points of damage.",
                 "Entrari1s Backstab VI hits a skeletal servant for 490 points of damage. (Critical)",
                 "Entraris Slice VI hits Bone Construct for 72 points of damage."):
        event = parse(text)
        assert event.actor == "Entrari", text
        assert event.action.split()[0] in {"Slice", "Stab", "Backstab"}, text
    # Names that merely end in s, or capitalized multi-word mobs, are left alone.
    assert parse("Nils hits a rat for 10 points of damage.").actor == "Nils"
    assert parse("Xerxes Construct hits Raan for 10 points of damage.").actor == "Xerxes Construct"
    assert parse("Your Slice VI hits a rat for 10 points of damage.").actor == "Raan"


def test_heal_lines_seen_in_real_logs():
    # Ability names containing "Heal" must not steal the target.
    event = parse("Arne's Sublime Heal heals you for 1365 Health.")
    assert (event.actor, event.target, event.amount) == ("Arne", "Raan", 1365)
    event = parse("Arne's Sublime Heal heals Entrari for 1365 Health.")
    assert (event.actor, event.target, event.amount) == ("Arne", "Entrari", 1365)
    # "heals them" is a self-heal on the caster.
    event = parse("Entrari's Life Sap heals them for 38 Health.")
    assert (event.actor, event.target, event.amount) == ("Entrari", "Entrari", 38)
    # No digits means no amount: a flavour line is not a 1-point heal.
    assert parse("Tiberous is renewed by ancestral healing") is None
    assert parse_amount("l") == 0
    assert parse_amount("I8O") == 180


def test_spreading_disease_damage_credits_the_disease_not_the_carrier():
    event = parse("Calvin spreads their Spreading Plague to Raan. Raan takes 400 points of damage!", name="Crit")
    assert (event.kind, event.actor, event.target, event.action, event.amount) == (
        EventKind.DAMAGE_OTHER, "Spreading Plague", "Raan", "Spread by Calvin", 400)
    event = parse("Ouch spreads their Disease to you. YOU take 400 points of damage!", name="Crit")
    assert (event.kind, event.actor, event.target) == (EventKind.DAMAGE_IN, "Disease", "Crit")
    # A passive "takes" line without a source credits nobody, and a bare verb is not a name.
    event = parse("Tom takes 400 points of damage!")
    assert (event.kind, event.actor, event.target) == (EventKind.DAMAGE_OTHER, "Unknown", "Tom")
    assert parse("takes 400 points of damage!").actor == "Unknown"
    # The existing "You take N from <source>" path is untouched.
    event = parse("You take 40 points of damage from a poison trap.")
    assert (event.kind, event.actor, event.target) == (EventKind.DAMAGE_IN, "poison trap", "Raan")


def test_ocr_glue_and_mangled_absorbed_words_are_repaired():
    event = parse("a tomb knight hics YOU for-407 points of damage (45 sbsorbed). (Critical)", name="Crit")
    assert (event.actor, event.target, event.action, event.amount, event.absorbed, event.critical) == (
        "tomb knight", "Crit", "Hits", 407, 45, True)
    event = parse("Fangkeeper's Savage Strike I hitsia rattlesnake for 20 points of damage.")
    assert (event.actor, event.target, event.action, event.amount) == ("Fangkeeper", "rattlesnake", "Savage Strike I", 20)
    assert repair_ocr_spacing("Sirobae's Staggering Winds hits Whiplash for 9") == "Sirobae's Staggering Winds hits Whiplash for 9"


def test_lines_clipped_at_the_region_edge_still_count():
    cases = {
        "Saranukes's Exceptional Fire Volley hits Bone Construct for 117 points of Fire":
            ("Saranukes", "Exceptional Fire Volley", "Bone Construct", 117),
        "Janantik punches a rotten sharpshooter with their offhand for 4 points of":
            ("Janantik", "Punches (Offhand)", "rotten sharpshooter", 4),
        "Saranukes's Exceptional Lightning Surge hits Bone Construct for 1455 points of":
            ("Saranukes", "Exceptional Lightning Surge", "Bone Construct", 1455),
        "Longjonn bites Pustulax the Avatar of Plagues with their offhand for 89 points o damage. (Critical)":
            ("Longjonn", "Bites (Offhand)", "Pustulax the Avatar of Plagues", 89),
        "Advisor Sargolin hits YOU for 59 polnts of damage (7 absorbed). (Critical)":
            ("Advisor Sargolin", "Hits", "Crit", 59),
        "Adviser Sargolin hits YOU for 59 points ąf damage (7 absorbed). (Critical)":
            ("Adviser Sargolin", "Hits", "Crit", 59),
        "Walkback's SliceIhits Whiplash for 8 points of damage.": ("Walkback", "Slice I", "Whiplash", 8),
        "Klog throws at a bone archer for 27 points of damage.": ("Klog", "Throws", "bone archer", 27),
    }
    for text, expected in cases.items():
        event = parse(text, name="Crit")
        assert event is not None, text
        assert (event.actor, event.action, event.target, event.amount) == expected, text
    assert parse("You gain 5 points of experience.") is None
    assert parse("Klog hits a rat for 5 points") is None  # no "of": not a damage line


def test_names_ending_in_a_verb_are_not_split():
    for name in ("Whiplash", "Backstab", "Bitesize"):
        event = parse(f"{name} crushes a rat for 5 points of damage.")
        assert event.actor == name, name
        event = parse(f"{name}'s Fireball hits a rat for 5 points of damage.")
        assert event.actor == name, name
    # The glued-verb repair still fires when the line has no other verb.
    assert repair_ocr_spacing("Klogpunches a zealot for 5 points of damage.").startswith("Klog punches")


def test_right_edge_clipping_keeps_criticals_and_miss_targets_drop_offhand():
    event = parse("You slash Blightcaller Torvak with your offhand for 76 points of damage. (Cr", name="Crit")
    assert (event.target, event.action, event.amount, event.critical) == ("Blightcaller Torvak", "Slash (Offhand)", 76, True)
    event = parse("Klog's Flying Kick V hits Blightcaller Torvak for 153 points of damage. (Cri")
    assert (event.actor, event.action, event.critical) == ("Klog", "Flying Kick V", True)
    assert not parse("Klog hits a rat for 5 points of damage.").critical
    # A Crippling Blow is the fighter's low-health critical.
    assert parse("You crush a pestilent ghoul for 46 points of damage. (Crippling Blow)").critical
    miss = parse("You try to slash Magistrate Sivash with your offhand, but miss!", name="Crit")
    assert (miss.kind, miss.actor, miss.target) == (EventKind.MISS, "Crit", "Magistrate Sivash")


def test_small_font_misreads_of_your_and_offhand():
    # At small font sizes "Your" reads as "Yowr"/"Youwr" and "offhand" as "offband".
    event = parse("Yowr Frenzy hits a Plagueborn drake for 89 points of damage.", name="Crit")
    assert (event.kind, event.actor, event.action) == (EventKind.DAMAGE_OUT, "Crit", "Frenzy")
    event = parse("Youwr Frenzy hits a Plagueborn drake for 104 points of damage.", name="Crit")
    assert (event.kind, event.actor, event.action) == (EventKind.DAMAGE_OUT, "Crit", "Frenzy")
    event = parse("You slash a Plagueborn drake with your offband for 77 points of damage.", name="Crit")
    assert (event.target, event.action) == ("Plagueborn drake", "Slash (Offhand)")
    # Real names that merely start with "Yo" are untouched.
    assert parse("Yowler bites YOU for 5 points of damage.").actor == "Yowler"
    assert parse("Youngblood's Slice VI hits a rat for 5 points of damage.").actor == "Youngblood"


def test_bow_suffix_and_clipped_critical_lines():
    event = parse("Firstedition pierces Lord Ga'Duuz with their bow for 34 points of damage.", name="Crit")
    assert (event.actor, event.target, event.action, event.amount) == ("Firstedition", "Lord Ga'Duuz", "Pierces (Bow)", 34)
    event = parse("Remco's Exceptional Fire Volley hits Lord Ga'Duuz for 166 points of Fire (Critical)", name="Crit")
    assert (event.actor, event.target, event.amount, event.critical) == ("Remco", "Lord Ga'Duuz", 166, True)


def test_another_creatures_pet_is_one_actor():
    event = parse("a Plagueborn runescribe's pet hits Player for 2 points of damage.", name="Crit")
    assert (event.kind, event.actor, event.target, event.action) == (
        EventKind.DAMAGE_OTHER, "Plagueborn runescribe's pet", "Player", "Hits")
    shield = parse("a Plagueborn runescribe's pet's Damage Shield hits YOU for 14 points of damage.", name="Crit")
    assert (shield.actor, shield.target, shield.is_damage_shield) == ("Plagueborn runescribe's pet", "Crit", True)
    ability = parse("a Pyrmos mercenary's pet's Strike hits a restless skeleton for 6 points of damage.", name="Crit")
    assert (ability.actor, ability.action, ability.target) == ("Pyrmos mercenary's pet", "Strike", "restless skeleton")
    # Your own pet is still yours.
    mine = parse("Raan's pet hits a rat for 5 points of damage.")
    assert (mine.kind, mine.actor, mine.is_pet) == (EventKind.DAMAGE_OUT, "Pet", True)


def test_faith_answers_heal_credits_owner_and_self_target():
    event = parse("Ebola's faith answers, healing them for 375 Health.")
    assert (event.actor, event.target, event.amount) == ("Ebola", "Ebola", 375)
    event = parse("Your faith answers, healing you for 750 Health!", name="Crit")
    assert (event.actor, event.target, event.amount) == ("Crit", "Crit", 750)
