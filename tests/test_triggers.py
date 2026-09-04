from discord_overlay.models import Region
from discord_overlay.triggers import Trigger, TriggerCondition, TriggerEngine, normalize_regex


def rule(*conditions, **values):
    return Trigger(name="Test", conditions=list(conditions),
                   cooldown_seconds=values.pop("cooldown_seconds", 0), **values)


def test_all_requires_every_positive_condition_on_same_line():
    engine = TriggerEngine([rule(TriggerCondition("begins to cast"), TriggerCondition("cataclysm"), logic="all")])
    assert engine.process("The boss begins to cast something", "combat", now=1) == []
    assert [m.trigger_name for m in engine.process("The boss begins to cast Cataclysm", "combat", now=2)] == ["Test"]


def test_any_and_not_boolean_conditions():
    engine = TriggerEngine([rule(TriggerCondition("enraged"), TriggerCondition("frenzied"),
                                 TriggerCondition("no longer", negate=True), logic="any")])
    assert len(engine.process("The creature is frenzied!", "combat", now=1)) == 1
    assert engine.process("The creature is no longer enraged.", "combat", now=2) == []


def test_regex_exact_and_case_sensitivity():
    regex = rule(TriggerCondition(r"hits YOU for \d+", mode="regex"))
    exact = rule(TriggerCondition("DANGER", mode="exact"), case_sensitive=True)
    assert len(TriggerEngine([regex]).process("a caiman hits YOU for 72 damage", "combat", 1)) == 1
    assert TriggerEngine([exact]).process("danger", "combat", 1) == []
    assert len(TriggerEngine([exact]).process("DANGER", "combat", 1)) == 1


def test_all_can_match_across_lines_inside_window_and_consumes_match():
    engine = TriggerEngine([rule(TriggerCondition("begins casting"), TriggerCondition("the room shakes"),
                                 logic="all", window_seconds=3)])
    assert engine.process("The boss begins casting", "combat", now=10) == []
    assert len(engine.process("the room shakes violently", "combat", now=12)) == 1
    assert engine.process("an unrelated line", "combat", now=13) == []


def test_cross_line_match_expires_and_negative_condition_blocks_window():
    engine = TriggerEngine([rule(TriggerCondition("begins casting"), TriggerCondition("the room shakes"),
                                 TriggerCondition("spell fizzles", negate=True), logic="all", window_seconds=2)])
    engine.process("begins casting", "combat", now=1)
    assert engine.process("the room shakes", "combat", now=4) == []
    engine.process("begins casting", "combat", now=5)
    engine.process("spell fizzles", "combat", now=5.5)
    assert engine.process("the room shakes", "combat", now=6) == []


def test_cooldown_prevents_repeat_until_elapsed():
    engine = TriggerEngine([rule(TriggerCondition("warning"), cooldown_seconds=5)])
    assert len(engine.process("warning", "combat", now=10)) == 1
    assert engine.process("warning", "combat", now=14.9) == []
    assert len(engine.process("warning", "combat", now=15)) == 1


def test_dedicated_region_only_matches_its_own_source():
    trigger = rule(TriggerCondition("tell"), use_combat_region=False, region=Region(10, 20, 300, 100))
    engine = TriggerEngine([trigger])
    assert engine.process("a tell arrives", "combat", now=1) == []
    assert len(engine.process("a tell arrives", trigger.source_key(), now=1)) == 1
    assert trigger.source_key() == "region:10:20:300:100"
    assert rule(TriggerCondition("x"), use_combat_region=False).source_key() == "missing"


def test_disabled_and_invalid_triggers_are_skipped():
    disabled = rule(TriggerCondition("x"), enabled=False)
    invalid = rule(TriggerCondition("[", mode="regex"))
    assert TriggerEngine([disabled, invalid]).triggers == []


def test_validation_messages():
    assert any("positive" in e for e in rule(TriggerCondition("ignore", negate=True)).validate())
    assert any("regex" in e for e in rule(TriggerCondition("[", mode="regex")).validate())
    errors = rule(TriggerCondition("starts"), overlay_enabled=True, bar_color="amber",
                  retrigger_mode="unknown", end_pattern="[", end_mode="regex").validate()
    assert any("Bar color" in e for e in errors)
    assert any("Retrigger" in e for e in errors)
    assert any("Early-ending regex" in e for e in errors)
    assert rule(TriggerCondition("ok")).validate() == []


def test_named_regex_captures_and_numbered_groups():
    trigger = rule(TriggerCondition(r"(?P<spell>[A-Za-z ]+) lands on (?P<target>\w+)", mode="regex"))
    match = TriggerEngine([trigger]).process("Withering Curse lands on Raan", "combat", now=1)[0]
    assert (match.captures["spell"], match.captures["target"]) == ("Withering Curse", "Raan")
    assert match.captures["$1"] == "Withering Curse"


def test_windowed_regex_captures_are_combined():
    engine = TriggerEngine([rule(TriggerCondition(r"Spell: (?P<spell>.+)", mode="regex"),
                                 TriggerCondition(r"Target: (?P<target>\w+)", mode="regex"),
                                 logic="all", window_seconds=3)])
    assert engine.process("Spell: Withering Curse", "combat", now=1) == []
    match = engine.process("Target: Raan", "combat", now=2)[0]
    assert (match.captures["spell"], match.captures["target"]) == ("Withering Curse", "Raan")


def test_early_end_regex_emits_targeted_end_signal():
    trigger = rule(TriggerCondition("curse lands"), end_pattern=r"Curse fades from (?P<target>\w+)", end_mode="regex")
    signal = TriggerEngine([trigger]).process("Curse fades from Raan", "combat", now=1)[0]
    assert (signal.action, signal.captures["target"]) == ("end", "Raan")


def test_gina_dotnet_syntax_is_supported():
    trigger = rule(TriggerCondition(r"^(?<spell>.+?) lands on (?<target>[A-Za-z'-]+)[.!]?$", mode="regex"))
    match = TriggerEngine([trigger]).process("Withering Curse lands on Raan.", "combat", now=1)[0]
    assert (match.captures["spell"], match.captures["target"]) == ("Withering Curse", "Raan")

    tokens = rule(TriggerCondition(r"^{S1} hits YOU for {N} points of damage[.]?$", mode="regex"))
    match = TriggerEngine([tokens]).process("a cursed plague rat hits YOU for 1,234 points of damage.", "combat", now=1)[0]
    assert (match.captures["s1"], match.captures["n"], match.captures["$1"]) == (
        "a cursed plague rat", "1,234", "a cursed plague rat")
    assert normalize_regex(r"(?'name'x)\k'name'") == r"(?P<name>x)(?P=name)"
    assert normalize_regex(r"a{2,4}") == r"a{2,4}"


def test_diagnostics_explain_window_blockers_and_cooldown():
    trigger = rule(TriggerCondition("begins"), TriggerCondition("erupts"), TriggerCondition("fizzles", negate=True),
                   logic="all", window_seconds=3, cooldown_seconds=5)
    engine = TriggerEngine([trigger])
    engine.process("begins", "combat", now=10)
    first = engine.last_diagnostics[0]
    assert first.conditions[0].active and not first.conditions[1].active and not first.condition_met
    engine.process("fizzles", "combat", now=11)
    assert engine.last_diagnostics[0].blocked

    engine = TriggerEngine([trigger])
    engine.process("begins", "combat", now=20)
    engine.process("erupts", "combat", now=21)
    assert engine.last_diagnostics[0].fired
    engine.process("begins and erupts", "combat", now=22)
    assert engine.last_diagnostics[0].cooldown_remaining == 4
    engine.process("anything", "other-source", now=23)
    assert not engine.last_diagnostics[0].source_matches


def test_from_dict_tolerates_bad_values():
    trigger = Trigger.from_dict({"name": "X", "window_seconds": "nope", "region": {"left": 1},
                                 "overlay_positions": "bad", "conditions": [{"pattern": "a"}, 5]})
    assert trigger.window_seconds == 0.0 and trigger.region is None and trigger.overlay_positions == {}
    assert len(trigger.conditions) == 1
