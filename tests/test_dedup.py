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


def test_identical_line_entering_as_another_scrolls_off_is_new():
    # Second Wind ticks "66 Health" every 2s; with a short chat window the oldest
    # tick scrolls off exactly as the newest appears, so the visible count is
    # unchanged. The new tick must still be reported.
    tick = "Crit's Second Wind heals you for 66 Health."
    dedup = ScrollingTextDeduplicator()
    dedup.new_lines(lines(tick, "Lonaner slashes Bone Construct for 4 points of damage.", "You crush Bone Construct for 15 points of damage."))
    fresh = dedup.new_lines(lines("Lonaner slashes Bone Construct for 4 points of damage.", "You crush Bone Construct for 15 points of damage.", tick))
    assert texts(fresh) == [tick]
    # Two ticks leaving and two identical ones arriving in the same frame both count.
    dedup = ScrollingTextDeduplicator()
    dedup.new_lines(lines(tick, tick, "filler one", "filler two"))
    assert texts(dedup.new_lines(lines("filler one", "filler two", tick, tick))) == [tick, tick]


def test_reset_reprimes_and_empty_input_is_ignored():
    dedup = ScrollingTextDeduplicator()
    dedup.new_lines(lines("a"))
    assert dedup.new_lines([]) == []
    dedup.reset()
    assert dedup.new_lines(lines("a", "b")) == []
    assert line_key("  You Crush, a Rat!! ") == "you crush a rat"


def test_scrolling_back_through_history_counts_nothing():
    dedup = ScrollingTextDeduplicator()
    mobs = ["rat", "bat", "wolf", "bear", "snake", "ghoul", "zombie", "spider", "beetle", "crab",
            "lion", "tiger", "hawk", "eagle", "boar", "elk", "moose", "yak", "goat", "hound",
            "imp", "wisp", "golem", "troll", "ogre", "gnoll", "kobold", "orc", "harpy", "wraith",
            "lich", "drake", "wyrm", "hydra", "basilisk", "manticore", "griffin", "sphinx", "naga"]
    history = [f"Klog hits a {mob} for {(n * 37) % 90 + 10} points of damage." for n, mob in enumerate(mobs)]
    dedup.new_lines(lines(*history[:5]))
    for start in range(1, 35):
        dedup.new_lines(lines(*history[start:start + 5]))      # normal scrolling, each line counted once
    # The user drags the chat back to lines seen long ago: no overlap with the last viewport.
    assert dedup.new_lines(lines(*history[2:7])) == []
    # Scrolling forward to genuinely new lines still counts only the new one.
    assert texts(dedup.new_lines(lines(*history[35:39], "Klog hits a phoenix for 99 points of damage."))) == [
        "Klog hits a phoenix for 99 points of damage."]


def test_line_key_ignores_digit_lookalike_jitter():
    assert line_key("You crush a rat for 5O points of damage.") == line_key("You crush a rat for 50 points of damage.")
    assert line_key("Klog hits a rat for l2 points of damage.") == line_key("Klog hits a rat for 12 points of damage.")
    # Words are left alone: "boil" must not become "8011".
    assert line_key("Klog's Boil hits a rat for 12 points of damage.") == "klog s boil hits a rat for 12 points of damage"
    dedup = ScrollingTextDeduplicator()
    dedup.new_lines(lines("one", "You crush a rat for 5O points of damage."))
    assert dedup.new_lines(lines("one", "You crush a rat for 50 points of damage.")) == []
