from pathlib import Path

from discord_overlay.models import EventKind, OCRLine
from discord_overlay.parser import CombatTextParser
from discord_overlay.paths import character_slug
from discord_overlay.repair import LineRepairer, bundled_grammar, event_names
from discord_overlay.scanner import repair_line

ROOT = Path(__file__).resolve().parents[1]
CLEAN = [
    "Sean punches a snake for 501 points of damage",
    "Sean punches a snake for 505 points of damage",
    "Sean punches a snake for 540 points of damage",
    "A snake bites YOU for 40 points of damage",
    "You heal Sean for 120 Health",
]
REAL_LINES = [
    line.strip() for line in (ROOT / "scripts" / "grammar-samples.txt").read_text(encoding="utf-8").splitlines()
    if line.strip() and not line.startswith("#")
]


def _trained() -> LineRepairer:
    repairer = LineRepairer()
    for line in CLEAN:
        repairer.observe(line)
    return repairer


def _seeded() -> LineRepairer:
    repairer = LineRepairer()
    assert repairer.load_seed_text(bundled_grammar()) > 300
    return repairer


def test_split_word_under_cursor_is_restored_with_original_number():
    fix = _trained().repair("Sean pun hes a snake for 777 points of damage")
    assert fix.text == "Sean punches a snake for 777 points of damage"
    assert fix.replaced == (("pun hes", "punches"),)


def test_symbol_noise_and_split_target_are_restored():
    repairer = _trained()
    assert repairer.repair("Sean pun~hes a snake for 12 points of damage").text == "Sean punches a snake for 12 points of damage"
    assert repairer.repair("Sean punches a sn ke for 33 points of damage").text == "Sean punches a snake for 33 points of damage"
    assert repairer.repair("A snake bi es YOU for 9 points of damage").text == "A snake bites YOU for 9 points of damage"
    assert repairer.repair("You he l Sean for 5 Health").text == "You heal Sean for 5 Health"
    assert repairer.repair("Sean punches ~ a snake for 5 points of damage").text == "Sean punches a snake for 5 points of damage"


def test_numbers_are_never_guessed():
    repairer = _trained()
    assert repairer.repair("Sean punches a snake for 5 5 points of damage") is None
    assert repairer.repair("Sean punches a snake for 5O5 points of damage") is None
    assert repairer.rejected >= 1


def test_legitimate_new_words_are_left_alone():
    repairer = _trained()
    assert repairer.repair("Sean kicks a snake for 40 points of damage") is None
    assert repairer.repair("Sean smashes a snake for 40 points of damage") is None
    assert repairer.repair("Sean punches a rat for 40 points of damage") is None
    assert repairer.repair("Sean punches a bat for 40 points of damage") is None
    assert repairer.repair("Sean punches a snake for 999 points of damage") is None


def test_fully_erased_word_needs_degraded_parse():
    repairer = _trained()
    text = "Sean a snake for 55 points of damage"
    assert repairer.repair(text, degraded=False) is None
    assert repairer.repair(text, degraded=True).text == "Sean punches a snake for 55 points of damage"


def test_ambiguous_templates_are_rejected():
    repairer = LineRepairer()
    repairer.observe("Sean slashes a snake for 10 points of damage")
    repairer.observe("Sean smashes a snake for 10 points of damage")
    assert repairer.repair("Sean s?ashes a snake for 10 points of damage") is None


def test_capacity_forgets_old_templates_and_their_words():
    repairer = LineRepairer(capacity=2)
    repairer.observe("Sean punches a snake for 1 points of damage")
    repairer.observe("A snake bites YOU for 2 points of damage")
    repairer.observe("You heal Sean for 3 Health")
    assert len(repairer) == 2
    assert repairer.repair("Sean pun hes a snake for 4 points of damage") is None


def test_repair_hook_marks_events_and_learns_clean_lines():
    repairer = LineRepairer()
    parser = CombatTextParser("Sean")
    for text in CLEAN:
        event, used = repair_line(repairer, parser, OCRLine(text, 0.9), parser.parse(text, 0.9))
        assert used == text and not event.repaired
    assert len(repairer) == 6  # 3 exact templates (digits masked) plus 3 name-masked variants

    line = OCRLine("Sean pun hes a snake for 505 points of damage", 0.9)
    event, used = repair_line(repairer, parser, line, parser.parse(line.text, 0.9))
    assert used == "Sean punches a snake for 505 points of damage"
    assert event.repaired and event.raw_text == line.text and event.confidence <= 0.85
    assert (event.kind, event.actor, event.target, event.amount) == (EventKind.DAMAGE_OUT, "Sean", "snake", 505)


def test_masked_templates_generalize_to_new_targets_and_contain_no_names():
    repairer = LineRepairer()
    parser = CombatTextParser("Sean")
    for text in CLEAN:
        event = parser.parse(text, 0.9)
        repairer.observe(text, (event.actor, event.target))
    fix = repairer.repair("Sean pun hes a caiman for 88 points of damage", degraded=True)
    assert fix.text == "Sean punches a caiman for 88 points of damage" and "@" in fix.template
    assert repairer.repair("Sean punches a sn ke for 88 points of damage").text == "Sean punches a snake for 88 points of damage"
    shareable = [line for line in repairer.masked_templates() if "@" in line]
    assert shareable and all("Sean" not in line and "snake" not in line for line in shareable)


def test_seed_dictionary_repairs_without_any_learning():
    repairer = _seeded()
    assert len(repairer) == 0
    fix = repairer.repair("Klog cru hes a scarred zealot for 47 points of damage", degraded=True)
    assert fix.text == "Klog crushes a scarred zealot for 47 points of damage"
    fix = repairer.repair("Ssssteve's Damage Shi~ld hits a skeletal cleric for 5 points of damage", degraded=True)
    assert fix.text == "Ssssteve's Damage Shield hits a skeletal cleric for 5 points of damage"
    assert repairer.repair("Klog crushes a scarred zealot for 4? points of damage", degraded=True) is None


def test_templates_persist_per_file(tmp_path):
    repairer = LineRepairer()
    parser = CombatTextParser("Sean")
    for text in CLEAN:
        event = parser.parse(text, 0.9)
        repairer.observe(text, (event.actor, event.target))
    assert repairer.dirty
    path = tmp_path / "templates" / "sean.json"
    repairer.save(path)
    assert not repairer.dirty
    restored = LineRepairer()
    assert restored.load(path) == len(repairer) and not restored.dirty
    assert restored.repair("Sean pun hes a snake for 5 points of damage").text == "Sean punches a snake for 5 points of damage"
    assert LineRepairer().load(tmp_path / "missing.json") == 0
    for payload in ('{"templates": 5}', '{"templates": null}', '[]', '{"templates": [1, {"tokens": 3}]}'):
        (tmp_path / "t.json").write_text(payload, encoding="utf-8")
        assert LineRepairer().load(tmp_path / "t.json") == 0


def test_helpers():
    assert "@ punches @ for # points of damage" in bundled_grammar()
    assert character_slug("Klog the Bold!") == "klog-the-bold"
    assert character_slug("   ") == "default"
    parser = CombatTextParser("Snubert")
    spell = parser.parse("Training's Celestial Strike hits a fire beetle for 5 points of damage.")
    assert event_names(spell) == ("Training", "fire beetle", "Celestial Strike")
    melee = parser.parse("Training punches a fire beetle for 2 points of damage.")
    assert event_names(melee) == ("Training", "fire beetle")
    repairer = LineRepairer()
    repairer.observe(spell.raw_text, event_names(spell))
    assert "@ @ hits a @ for # points of damage" in repairer.masked_templates()


def test_clean_real_lines_are_never_rewritten_by_the_seed():
    repairer = _seeded()
    parser = CombatTextParser("Snubert")
    rewritten = []
    for text in REAL_LINES:
        event = parser.parse(text, 0.9)
        if event is None:
            continue
        fixed, used = repair_line(repairer, parser, OCRLine(text, 0.9), event)
        if used != text or fixed.repaired:
            rewritten.append((text, used))
    assert rewritten == []
    assert len(repairer) > 0


def test_split_and_merge_need_evidence_of_damage():
    repairer = _seeded()
    assert repairer.repair("You punch a desert bat for 1 point of damage.") is None
    assert repairer.repair("Raan bites a rotten sharpshooter for 42 points of damage.", True) is None
    assert repairer.repair("Ouch crushes a rotten sharpshooter for 77 points of damage.", True) is None
    assert repairer.repair("Klog cru hes a scarred zealot for 47 points of damage", degraded=True).text == (
        "Klog crushes a scarred zealot for 47 points of damage")
    assert repairer.repair("Youcrush a scarred zealot for 41 points of damage").text == (
        "You crush a scarred zealot for 41 points of damage")


def test_known_lines_skip_alignment_entirely():
    repairer = _trained()
    calls = []
    original = repairer._align
    repairer._align = lambda *args, **kwargs: calls.append(1) or original(*args, **kwargs)
    assert repairer.repair("Sean punches a snake for 12 points of damage") is None
    assert calls == []
