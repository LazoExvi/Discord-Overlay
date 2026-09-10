import numpy as np

from discord_overlay.models import OCRLine
from discord_overlay.parser import CombatTextParser
from discord_overlay.problem_frames import ProblemFrameSaver, problem_reason


def _line(text, conf=0.95, y=10.0):
    return OCRLine(text, conf, y)


def test_problem_reasons():
    p = CombatTextParser("Crit")
    good = _line("You crush a rat for 5 points of damage.")
    assert problem_reason(good, p.parse(good.text)) is None
    flavour = _line("Arne is renewed by ancestral healing")
    assert problem_reason(flavour, p.parse(flavour.text)) is None
    fused = _line("Your Feint IV hits a Plagueborn myrmidon for 107 pond for 56 points of damage.")
    assert problem_reason(fused, p.parse(fused.text)) == "two messages fused into one line"
    garbled = _line("crusllaguPlagueboyrmidomiith youh offhand for 68 points of damage.")
    assert problem_reason(garbled, p.parse(garbled.text)) == "actor or target unreadable"


def test_saver_writes_frame_and_report_only_for_problem_frames(tmp_path):
    p = CombatTextParser("Crit")
    saver = ProblemFrameSaver(tmp_path / "problem-frames", min_interval=0.0)
    frame = np.zeros((20, 40, 3), dtype=np.uint8)

    clean = [_line("You crush a rat for 5 points of damage.")]
    for line in clean:
        saver.note(line, p.parse(line.text))
    assert saver.flush(frame, clean, now=1.0) is None

    lines = [_line("You crush a rat for 5 points of damage.", y=10),
             _line("Your Feint IV hits a rat for 107 pond for 56 points of damage.", 0.88, y=30)]
    for line in lines:
        saver.note(line, p.parse(line.text))
    png = saver.flush(frame, lines, now=2.0)
    assert png is not None and png.exists()
    report = png.with_suffix(".txt").read_text(encoding="utf-8")
    assert "two messages fused into one line" in report and "y=  30.0" in report and "conf=0.88" in report


def test_saver_rate_limits_and_caps(tmp_path):
    saver = ProblemFrameSaver(tmp_path, max_files=2, min_interval=1.0)
    frame = np.zeros((4, 4, 3), dtype=np.uint8)
    bad = _line("for 74 points of damage.")
    for now, expected in ((1.0, True), (1.2, False), (3.0, True), (9.0, False)):
        saver.note(bad, None)
        assert (saver.flush(frame, [bad], now=now) is not None) is expected, now
