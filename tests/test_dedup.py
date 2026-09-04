from discord_overlay.dedup import ScrollingTextDeduplicator, line_key
from discord_overlay.models import OCRLine


def lines(*values):
    return [OCRLine(value, 0.9, i * 20) for i, value in enumerate(values)]


def texts(fresh):
    return [line.text for line in fresh]


def test_primes_without_counting_old_visible_history():
    assert ScrollingTextDeduplicator().new_lines(lines("old one", "old two")) == []


def test_finds_appended_line_with_and_without_scroll():
    dedup = ScrollingTextDeduplicator()
    dedup.new_lines(lines("one", "two"))
    assert texts(dedup.new_lines(lines("one", "two", "three"))) == ["three"]
    assert texts(dedup.new_lines(lines("two", "three", "four"))) == ["four"]


def test_tolerates_minor_ocr_jitter():
    dedup = ScrollingTextDeduplicator()
    dedup.new_lines(lines("You crush a rat for 18 points of damage.", "second line"))
    fresh = dedup.new_lines(lines("You crush a rat for 1B points of damage", "second line", "new line"))
    assert texts(fresh) == ["new line"]


def test_does_not_merge_similar_combat_lines_with_different_targets():
    crocodile = "Your iceblast hits a crocodile for 717 points of Cold Damage."
    caiman = "Your iceblast hits a caiman for 717 points of Cold Damage."
    dedup = ScrollingTextDeduplicator()
    dedup.new_lines(lines("older line", crocodile))
    assert texts(dedup.new_lines(lines(crocodile, caiman))) == [caiman]

    dedup = ScrollingTextDeduplicator()
    dedup.new_lines(lines("older line", "a crocodile hits YOU for 10 points of damage."))
    fresh = dedup.new_lines(lines("a crocodile hits YOU for 10 points of damage.",
                                  "a caiman hits YOU for 10 points of damage."))
    assert texts(fresh) == ["a caiman hits YOU for 10 points of damage."]


def test_new_bottom_line_survives_mostly_unchanged_static_viewport():
    dedup = ScrollingTextDeduplicator()
    dedup.new_lines(lines("one", "two", "three", "a crocodile attacks"))
    assert texts(dedup.new_lines(lines("one", "two", "three", "a caiman attacks"))) == ["a caiman attacks"]


def test_lost_overlap_does_not_replay_a_still_visible_line():
    dedup = ScrollingTextDeduplicator()
    dedup.new_lines(lines("old baseline", "Your Rage Grows"))
    fresh = dedup.new_lines(lines("unrelated replacement", "Your Rage Grows"))
    assert texts(fresh) == ["unrelated replacement"]


def test_an_additional_identical_line_is_still_new_when_count_increases():
    dedup = ScrollingTextDeduplicator()
    dedup.new_lines(lines("Your Rage Grows"))
    assert texts(dedup.new_lines(lines("Your Rage Grows", "Your Rage Grows"))) == ["Your Rage Grows"]


def test_reset_reprimes_and_empty_input_is_ignored():
    dedup = ScrollingTextDeduplicator()
    dedup.new_lines(lines("a"))
    assert dedup.new_lines([]) == []
    dedup.reset()
    assert dedup.new_lines(lines("a", "b")) == []
    assert line_key("  You Crush, a Rat!! ") == "you crush a rat"
